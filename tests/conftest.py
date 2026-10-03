# ComfyUI-H3-Character-Sheet - test configuration.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Make the pack's tests runnable from any CWD, with or without ComfyUI present.

* The checkout directory is named ``ComfyUI-H3-Character-Sheet`` (not a valid
  module name), so the pack is aliased as ``h3cs`` for imports - the same trick
  every ComfyUI custom-node repo needs when it tests itself.
* ``folder_paths`` is a ComfyUI core module. When ComfyUI is not on ``sys.path``
  the tests that only touch the sheet store/tools need a small stand-in.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

_PACK_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_PACK_ROOT)


def _alias_pack() -> None:
    if "h3cs" not in sys.modules:
        alias = types.ModuleType("h3cs")
        alias.__path__ = [str(_PACK_ROOT / "h3_character_sheet")]
        alias.__package__ = "h3cs"
        sys.modules["h3cs"] = alias


_alias_pack()


def _ensure_folder_paths() -> None:
    try:
        import folder_paths  # noqa: F401

        return
    except Exception:  # noqa: BLE001 - ComfyUI absent
        stub = types.ModuleType("folder_paths")
        stub.get_output_directory = lambda: "/tmp/h3-character-sheet-output"  # type: ignore[attr-defined]
        stub.get_input_directory = lambda: "/tmp/h3-character-sheet-input"  # type: ignore[attr-defined]
        stub.get_filename_list = lambda *args, **kwargs: []  # type: ignore[attr-defined]
        sys.modules["folder_paths"] = stub


_ensure_folder_paths()


@pytest.fixture(autouse=True)
def _contain_stub_leakage():
    """Drop stub modules a test installed so a later test gets the real one."""
    before = dict(sys.modules)
    yield
    for name, module in list(sys.modules.items()):
        if name in before:
            continue
        if isinstance(module, types.ModuleType) and getattr(module, "__spec__", None) is None:
            del sys.modules[name]
