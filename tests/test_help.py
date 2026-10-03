# 5tar5ystem MMH3 Character Sheet Builder - the in-node guide and its live file check.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The Help tab is documentation, and documentation goes stale silently.

So the claims that can be checked are checked here: the file names the guide recommends must
be the names the bundled example workflow loads, the loader it names for each file must be a
loader the example actually has, every link must be a real URL, and the requirements check
must survive an install that has none of the files (it reports, it never raises - the guide
has to render on a machine where nothing is set up yet, because that is when it is read).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from h3cs import face_blur, help as help_mod
from h3cs.nodes import sheet as sheet_node


def _example_workflow() -> dict:
    root = Path(sheet_node.__file__).resolve().parents[2]
    return json.loads((root / help_mod.EXAMPLE_WORKFLOW).read_text())


def _example_widgets(node_type: str) -> list[list]:
    return [n["widgets_values"] for n in _example_workflow()["nodes"] if n["type"] == node_type]


def _all_links() -> list[help_mod.HelpLink]:
    links = [link for section in help_mod.SECTIONS for link in section.links]
    links += [link for requirement in help_mod.REQUIREMENTS for link in requirement.links]
    return links


# --------------------------------------------------------------------------- #
# the guide
# --------------------------------------------------------------------------- #
def test_every_section_has_something_to_read():
    assert help_mod.SECTIONS, "a Help tab with no sections is not help"
    for section in help_mod.SECTIONS:
        assert section.id and section.id.islower(), section.id
        assert section.title, section.id
        assert section.intro or section.steps or section.bullets or section.kind == "files", section.id


def test_section_ids_are_unique_and_in_a_reading_order():
    ids = [section.id for section in help_mod.SECTIONS]
    assert len(ids) == len(set(ids))
    # The file check has to come before the advice about the face blur, which depends on it.
    assert ids.index("files") < ids.index("faceblur") < ids.index("tips")


def test_the_quick_start_is_actually_a_sequence():
    """A "quick start" with one step, or none, is a heading pretending to be a guide."""
    quick = next(section for section in help_mod.SECTIONS if section.id == "quickstart")
    assert len(quick.steps) >= 5
    assert any("Queue" in step for step in quick.steps), "it has to say how to actually render"


def test_the_guide_mentions_the_panel_it_lives_in():
    """Every tab the guide tells you to use must be a real tab."""
    text = " ".join(
        [
            " ".join([section.title, section.intro, *section.steps, *section.bullets])
            for section in help_mod.SECTIONS
        ]
    )
    for tab in ("References", "Cells", "Results", "Settings"):
        assert tab in text, f"the guide never mentions the {tab} tab"
    assert "Rebuild sheet" in text, "the no-GPU re-composite is the trick worth documenting"


def test_the_help_payload_is_json_serialisable():
    payload = help_mod.help_payload()
    json.dumps(payload)
    assert payload["project"] == help_mod.PROJECT
    assert payload["example"]["title"] == help_mod.EXAMPLE_WORKFLOW_TITLE
    assert [section["id"] for section in payload["sections"]] == [s.id for s in help_mod.SECTIONS]
    assert len(payload["requirements"]) == len(help_mod.REQUIREMENTS)


# --------------------------------------------------------------------------- #
# every link
# --------------------------------------------------------------------------- #
def test_every_link_is_a_real_url_with_a_label():
    links = _all_links()
    assert links, "the guide has to link somewhere"
    for link in links:
        assert link.label and link.url, link
        assert link.url.startswith("https://"), f"{link.url} is not https"
        assert link.note, f"{link.label} should say what to do with it"


def test_the_sources_the_user_asked_for_are_the_sources_we_link():
    """The exact pages that were specified: the checkpoint, the text encoders, the VAEs."""
    urls = {link.url for link in _all_links()}
    assert "https://huggingface.co/TenStrip/10Eros-Max/tree/main" in urls
    assert "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders" in urls
    assert "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae" in urls
    assert "https://huggingface.co/Bingsu/adetailer/tree/main" in urls


def test_the_checkpoint_link_says_why_a_turbo_file_matters():
    """8 steps is only right for a TURBO build - the link note has to carry that."""
    checkpoint = next(req for req in help_mod.REQUIREMENTS if req.id == "unet")
    note = " ".join(link.note for link in checkpoint.links)
    assert "turbo" in note.lower()
    assert "w4a8" in note.lower() or "14gb" in note.lower(), "name the size tiers"
    assert checkpoint.note, "and the 'any H3 checkpoint works' caveat"

    links = checkpoint.links[0]
    assert "TURBO" in links.note, "the download itself has to be the TURBO one"


# --------------------------------------------------------------------------- #
# the file names, pinned to the workflow that uses them
# --------------------------------------------------------------------------- #
def test_the_text_encoder_and_vaes_are_the_files_the_example_loads():
    clip = _example_widgets("CLIPLoader")[0]
    vaes = [values[0] for values in _example_widgets("VAELoader")]
    by_id = {req.id: req for req in help_mod.REQUIREMENTS}

    # `match` holds substrings (versions change, the stem does not) - so the workflow's file
    # has to CONTAIN one of them, and the human-facing text has to name it in full.
    for name, requirement_id in [(clip[0], "clip"), *zip(vaes, ("video_vae", "audio_vae"))]:
        requirement = by_id[requirement_id]
        assert any(token in name.lower() for token in requirement.match), (
            f"{requirement_id} would not recognise {name}"
        )
        prose = " ".join([requirement.what, *(link.note for link in requirement.links)])
        assert name in prose, f"{requirement_id} should spell out {name}"
    assert clip[1] == "minimax", "CLIPLoader's type is minimax"
    assert "minimax" in by_id["clip"].what.lower()


def test_every_requirement_names_a_loader_the_example_uses():
    used = {node["type"] for node in _example_workflow()["nodes"]}
    for requirement in help_mod.REQUIREMENTS:
        if requirement.node.startswith("("):
            continue  # loaded inside the node, not a graph node
        assert requirement.node in used, f"{requirement.node} is not in the example workflow"


def test_the_files_go_where_comfyui_looks():
    for requirement in help_mod.REQUIREMENTS:
        if requirement.resolve == "face_model":
            assert requirement.folder == "ultralytics/bbox"
            assert requirement.where.startswith("ComfyUI/models/ultralytics/bbox/")
            continue
        assert f"ComfyUI/models/{requirement.folder}/" in requirement.where
        assert requirement.match, requirement.id


# --------------------------------------------------------------------------- #
# the live check
# --------------------------------------------------------------------------- #
def test_the_face_detector_check_uses_the_packs_own_lookup(monkeypatch, tmp_path):
    """One definition of "where is the face model": face_blur's candidate list."""
    monkeypatch.setattr(face_blur, "model_path", lambda: tmp_path / "face_yolov8m.pt")
    state = {item["id"]: item for item in help_mod.check_requirements()}["face_model"]
    assert state["ok"] is True
    assert "ultralytics/bbox/face_yolov8m.pt" in state["where"]


def test_a_missing_face_model_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(face_blur, "model_path", lambda: None)
    state = {item["id"]: item for item in help_mod.check_requirements()}["face_model"]
    assert state["ok"] is False
    assert "models/ultralytics/bbox" in state["looked"], (
        "it has to say where it looked, or the answer is not actionable"
    )
    assert state["links"], "and still offer the download"


def test_an_empty_install_reports_every_file_missing(monkeypatch):
    """The state this tab is read in first: nothing downloaded yet."""
    monkeypatch.setattr(face_blur, "model_path", lambda: None)
    monkeypatch.setattr(help_mod, "_resolve_names", lambda folder: [])
    monkeypatch.setattr(help_mod, "_resolve_paths", lambda folder: "")
    payload = help_mod.help_payload()
    assert payload["ready"] is False
    assert len(payload["missing"]) == len(help_mod.REQUIREMENTS)
    for item in payload["requirements"]:
        assert item["ok"] is False
        assert item["where"], "every ✗ has to say where the file goes"
        assert item["links"], "and where to get it"


def test_a_file_in_a_subfolder_still_counts(monkeypatch):
    """Model managers nest things: Minimax/x.safetensors is a normal layout."""
    monkeypatch.setattr(
        help_mod, "_resolve_names",
        lambda folder: ["Minimax/10Eros_Max_h3_TURBO-hybrid_beta5_w4a8_14gb_optimized.safetensors"]
        if folder == "diffusion_models" else [],
    )
    monkeypatch.setattr(help_mod, "_resolve_paths", lambda folder: f"/models/{folder}")
    monkeypatch.setattr(face_blur, "model_path", lambda: None)
    state = {item["id"]: item for item in help_mod.check_requirements()}["unet"]
    assert state["ok"] is True
    assert "ComfyUI/models/diffusion_models/" in state["where"]


def test_the_check_reports_the_folder_not_the_files_on_this_machine(monkeypatch):
    """A ✓/✗ per file, and where it belongs - never the names this install happens to hold.

    The Help tab is read by whoever installed the pack: naming one disk's checkpoints is a
    fact about that disk, not an answer. The shipped guide used to print "found: <file>"
    plus "also here:" and the whole list, which reads as gibberish on any other machine.
    """
    names = [
        "Minimax/10Eros_Max_h3_TURBO-hybrid_beta4_int8_convrot.safetensors",
        "Minimax/10Eros_Max_h3_TURBO-hybrid_beta5_int8.safetensors",
        "Minimax/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    ]
    monkeypatch.setattr(
        help_mod, "_resolve_names",
        lambda folder: list(names) if folder == "diffusion_models" else [],
    )
    monkeypatch.setattr(help_mod, "_resolve_paths", lambda folder: f"/models/{folder}")
    state = {item["id"]: item for item in help_mod.check_requirements()}["unet"]
    assert state["ok"] is True, "three matching checkpoint files means the requirement is met"
    payload = json.dumps(state)
    for name in names:
        assert name not in payload, f"{name} is a file on one machine, not a fact about the pack"
    assert "matches" not in state and "match_count" not in state and "found" not in state


def test_the_guide_does_not_pin_one_community_build():
    """Naming one beta as "the good one" ages badly and means nothing to a new reader.

    The numbers on a community model page change; beta3/beta4/beta5 are that page's own
    history, not something this pack can promise about a file in someone else's folder.
    """
    requirement = next(req for req in help_mod.REQUIREMENTS if req.id == "unet")
    text = " ".join(
        [requirement.note, requirement.what]
        + [link.note for link in requirement.links]
        + [part for section in help_mod.SECTIONS for part in (section.intro, *section.bullets)]
    ).lower()
    assert "turbo" in text, "the step count still has to be explained"
    for word in ("beta3", "beta4", "beta_3", "beta_4", "corrupted"):
        assert word not in text, f"the guide should not be about {word}"


def test_the_check_never_raises_when_comfyui_is_absent(monkeypatch):
    """Import-time and runtime: the guide has to render even without folder_paths."""
    def boom(folder):
        raise RuntimeError("no ComfyUI here")

    monkeypatch.setattr(help_mod, "_resolve_names", boom)
    monkeypatch.setattr(help_mod, "_resolve_paths", boom)
    payload = help_mod.help_payload()
    assert payload["missing"], "a broken install is exactly when this tab should speak up"


def test_the_requirements_are_ordered_like_the_workflow():
    """Checkpoint, encoder, VAEs, then the optional face model - the order they are wired."""
    assert [req.id for req in help_mod.REQUIREMENTS] == [
        "unet", "clip", "video_vae", "audio_vae", "face_model",
    ]
    assert help_mod.REQUIREMENTS[-1].label.lower().startswith("face detector"), (
        "the optional one must announce that it is optional"
    )


# --------------------------------------------------------------------------- #
# the face blur needs a package as well as a file
# --------------------------------------------------------------------------- #
def test_the_face_blur_names_the_python_package_it_needs():
    """A model file without `ultralytics` is a ✓ next to a feature that cannot run."""
    requirement = next(req for req in help_mod.REQUIREMENTS if req.id == "face_model")
    assert requirement.packages == ("ultralytics", "cv2"), (
        "face_blur imports ultralytics (the detector) and cv2 (the blur itself)"
    )
    text = " ".join(
        [requirement.note, requirement.what]
        + [link.note for link in requirement.links]
        + [
            part
            for section in help_mod.SECTIONS
            for part in (section.intro, *section.bullets, *section.steps)
        ]
    )
    assert "pip install ultralytics" in text, "the guide has to say how to get it"


def test_a_missing_detector_package_is_reported_beside_the_file(monkeypatch):
    """The file can be right and the feature still dead: say both things."""
    monkeypatch.setattr(face_blur, "model_path", lambda: Path("/m/face_yolov8m.pt"))
    monkeypatch.setattr(help_mod, "_package_state", lambda package: False)
    state = {item["id"]: item for item in help_mod.check_requirements()}["face_model"]
    assert state["file_ok"] is True, "the file really is there"
    assert state["ok"] is False, "but the requirement is not usable"
    assert state["missing_packages"] == ["ultralytics", "cv2"]
    assert [item["name"] for item in state["packages"]] == ["ultralytics", "cv2"]
    payload = help_mod.help_payload()
    assert payload["missing_packages"] == ["cv2", "ultralytics"], "and the header can name them"
    assert payload["ready"] is False


def test_a_package_lookup_can_never_raise():
    """`find_spec` is the cheapest safe probe - a nonsense name must not blow up the tab."""
    assert help_mod._package_state("definitely_not_a_package_xyz") is False
    assert help_mod._package_state("no.such.package") is False


def test_the_node_is_named_for_the_project():
    """The pack's own display name carries the project name (workflows key on the type)."""
    schema = sheet_node.MiniMaxH3CharacterSheet.define_schema()
    assert schema.node_id == "MiniMaxH3CharacterSheet", "the type is a workflow contract"
    assert help_mod.PROJECT.split()[-1] in schema.display_name or "Character Sheet" in schema.display_name


@pytest.mark.parametrize("section_id", [section.id for section in help_mod.SECTIONS])
def test_each_section_renders_into_the_payload(section_id):
    section = next(
        item for item in help_mod.help_payload()["sections"] if item["id"] == section_id
    )
    assert isinstance(section["steps"], list) and isinstance(section["bullets"], list)
    assert isinstance(section["links"], list)
