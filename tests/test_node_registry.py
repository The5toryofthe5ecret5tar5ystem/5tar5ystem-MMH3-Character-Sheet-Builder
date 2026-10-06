# ComfyUI-H3-Character-Sheet - the node registry ComfyUI actually reads.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""``NODE_CLASS_MAPPINGS`` is the list ComfyUI executes from - and it is hand-written.

That list lives in ``h3_character_sheet/__init__.py`` and is NOT the same object as
``h3cs.nodes.__all__``, which is what the graph tests import. So an internal node can be perfectly
importable, correctly inserted into a graph, pass every graph test - and still be missing from the
registry, because the two lists are written in two files. The executor then dies with
``KeyError: 'H3SheetJoin'`` on the first prompt that uses it, *after* a full model load and a suite
expansion (which is exactly what happened on 2026-10-06, with a suite that had already built its
four boards and printed them).

Three directions, so this cannot recur quietly:

* every class the ``nodes`` package exports is in the registry;
* every node type the three expansions can produce is in the registry - asked of the graphs
  themselves, so it covers a node nobody thought to list here;
* every registered class still builds its own schema, and answers to the name it is filed under
  (a class whose ``define_schema()`` raises at import is a node the server silently drops).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from comfy_execution.graph_utils import GraphBuilder

from h3cs import nodes as node_package
from h3cs import one_pass as op
from h3cs import sheet_spec as ss
from h3cs import suite as suite_mod
from h3cs.nodes import sheet as sheet_node
from h3cs.planner import cell_work_items, grid_payload, reference_plan

from tests.test_sheet_one_pass import _spec
from tests.test_sheet_suite import _suite_spec

_PACK_ROOT = Path(__file__).resolve().parent.parent

#: Registry keys that are aliases of another node (a prompt queued before a rename still names
#: them). They answer to their target's schema, not to their own key.
LEGACY_ALIASES = {"H3SheetDraftSink": "H3SheetOnePassSink"}


@pytest.fixture(scope="module")
def pack_module():
    """The pack imported AS A PACKAGE - the way ComfyUI imports it (``NODE_CLASS_MAPPINGS``)."""
    if str(_PACK_ROOT) not in sys.path:
        sys.path.insert(0, str(_PACK_ROOT))
    return importlib.import_module("h3_character_sheet")


@pytest.fixture(scope="module")
def registry(pack_module) -> dict:
    return dict(pack_module.NODE_CLASS_MAPPINGS)


def _node_types(graph) -> set[str]:
    return {str(node["class_type"]) for node in graph.finalize().values()}


def _ours(types) -> set[str]:
    """The types in a graph that THIS pack has to provide (core's are core's)."""
    return {name for name in types if name.startswith("H3Sheet") or name == "MiniMaxH3CharacterSheet"}


# --------------------------------------------------------------------------- #
# the two lists must agree
# --------------------------------------------------------------------------- #
def test_every_node_the_nodes_package_exports_is_registered(registry):
    """The internal nodes are exported in one file and registered in another."""
    missing = [name for name in node_package.__all__ if name not in registry]
    assert missing == [], (
        f"{missing} are importable from the nodes package but NOT in the pack's "
        "NODE_CLASS_MAPPINGS - the executor would die with KeyError on the first prompt that "
        "uses them (this is the H3SheetJoin bug)"
    )


def test_every_registered_class_is_the_class_the_nodes_package_exports(registry):
    """A stale registration (a class renamed, moved or replaced) is as bad as a missing one.

    Compared by NAME, not by identity: the tests import the pack twice - as ``h3cs`` (the conftest
    alias every other test uses) and as ``h3_character_sheet`` (the package ComfyUI imports) - so
    the two class objects are different objects for the same file. The name and the module tail
    are what a registration can get wrong.
    """
    for name in node_package.__all__:
        registered = registry[name]
        expected = getattr(node_package, name)
        assert registered.__name__ == expected.__name__, name
        assert registered.__module__.split(".", 1)[-1] == expected.__module__.split(".", 1)[-1], (
            f"{name} is registered from {registered.__module__}, the nodes package exports it from "
            f"{expected.__module__}"
        )


def test_every_expansion_node_has_a_home_in_the_registry(registry):
    """Ask the graphs, not a list: every pack-owned type they build must be registered."""
    per_cell = _spec()
    graph = GraphBuilder()
    sheet_node.build_sheet_graph(
        graph, model="MODEL", clip="CLIP", video_vae="VVAE", audio_vae="AVAE",
        work_items=cell_work_items(per_cell, cell_size=1024, ref_image_size="match",
                                   ref_scope=ss.DEFAULT_REF_SCOPE),
        refs=reference_plan(per_cell), payload=grid_payload(per_cell, name="sheet run"),
        name="sheet run",
    )
    builds = {"per-cell": _node_types(graph)}

    one_pass = _spec()
    graph = GraphBuilder()
    sheet_node.build_one_pass_graph(
        graph, model="MODEL", clip="CLIP", video_vae="VVAE", audio_vae="AVAE",
        plan=op.one_pass_plan(one_pass), refs=reference_plan(one_pass),
        payload=grid_payload(one_pass, name="one-pass sheet"), name="one-pass sheet",
    )
    builds["one-pass"] = _node_types(graph)

    suite_spec = _suite_spec()
    boards, warnings = suite_mod.suite_boards(suite_spec)
    assert not warnings, warnings
    expand, _outputs, _lines = sheet_node.build_suite_graph(
        boards=boards, model="MODEL", clip="CLIP", video_vae="VVAE", audio_vae="AVAE",
        name=str(suite_spec.name),
    )
    builds["suite"] = set(expand_types := {str(node["class_type"]) for node in expand.values()})
    assert expand_types, "the suite expansion is not empty"

    for label, types in builds.items():
        missing = sorted(_ours(types) - set(registry))
        assert missing == [], f"the {label} expansion builds {missing}, which nothing registers"


# --------------------------------------------------------------------------- #
# what a registration has to carry
# --------------------------------------------------------------------------- #
def test_every_registered_node_builds_its_schema_and_answers_to_its_key(registry):
    for name, cls in registry.items():
        assert callable(getattr(cls, "define_schema", None)), f"{name} is not a V3 node"
        schema = cls.define_schema()
        expected = LEGACY_ALIASES.get(name, name)
        assert str(schema.node_id) == expected, (
            f"{name} is filed as {name!r} but its schema calls itself {schema.node_id!r}"
        )
        assert schema.inputs, f"{name} has no inputs"
        assert schema.outputs, f"{name} has no outputs"


def test_every_registered_node_has_a_display_name(pack_module, registry):
    """A node with no display name shows up in the browser as its class name."""
    names = dict(pack_module.NODE_DISPLAY_NAME_MAPPINGS)
    missing = sorted(set(registry) - set(names) - set(LEGACY_ALIASES))
    assert missing == [], f"no display name for {missing}"
    stale = sorted(set(names) - set(registry))
    assert stale == [], f"display names for nodes that are not registered: {stale}"
