# ComfyUI-H3-Character-Sheet - the LoRA stack: spec, files, Civitai, routes.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""The LoRAs tab's backend: a stack on the sheet, and the facts a user needs about each file.

Four things are checked here, in the order a LoRA travels:

* the **payload** -> the spec's stack (clamping, deduping, the cap, the round-trip);
* the **file** -> the digest Civitai is asked about (computed once per version of the file);
* **Civitai** -> the answer the panel's card shows, including the two answers that are not
  answers: a hash Civitai does not know, and a machine that cannot reach it. Neither may raise:
  the tab has to render on a box that is offline.
* the **model** -> every enabled entry loaded in order, switched-off ones skipped, and one bad
  file be a warning rather than a lost sheet.

No test here touches the network: ``_get_json`` is the single seam every Civitai call goes
through, and the files are bytes in a temp folder.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import types
import urllib.error

import pytest

from h3cs import lora_library as lib
from h3cs import sheet_routes, sheet_spec as ss


# --------------------------------------------------------------------------- #
# fixtures: a temp loras folder and a temp metadata store
# --------------------------------------------------------------------------- #
@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the metadata store at a temp file (nothing touches the user's own store)."""
    monkeypatch.setattr(lib, "store_path", lambda: tmp_path / "loras.json")
    return tmp_path


@pytest.fixture()
def loras(store, monkeypatch):
    """Two fake LoRA files, visible to ``lora_path`` / ``lora_files``."""
    alpha = store / "Minimax/alpha.safetensors"
    beta = store / "beta.safetensors"
    alpha.parent.mkdir(parents=True, exist_ok=True)
    alpha.write_bytes(b"a" * 4096)
    beta.write_bytes(b"b" * 2048)
    mapping = {"Minimax/alpha.safetensors": alpha, "beta.safetensors": beta}
    monkeypatch.setattr(lib, "lora_path", lambda name: mapping.get(str(name or "").strip()))
    monkeypatch.setattr(lib, "lora_files", lambda **kwargs: list(mapping))
    return mapping


@pytest.fixture()
def fake_comfy(monkeypatch):
    """Stand in for the two ComfyUI calls the stack makes (no weights, no CUDA)."""
    sd = pytest.importorskip("comfy.sd")
    utils = pytest.importorskip("comfy.utils")
    calls: dict[str, list] = {"files": [], "apply": []}

    def load_torch_file(path, safe_load=True):
        calls["files"].append(str(path))
        return {"from": str(path)}

    def load_lora_for_models(model, clip, lora, strength_model, strength_clip, lora_metadata=None):
        calls["apply"].append((model, lora.get("from"), strength_model))
        return f"patched<{model}|{strength_model}>", None

    monkeypatch.setattr(sd, "load_lora_for_models", load_lora_for_models)
    monkeypatch.setattr(utils, "load_torch_file", load_torch_file)
    return calls


def _stack(*pairs) -> list[ss.SheetLora]:
    return [ss.SheetLora(file=name, strength=strength) for name, strength in pairs]


# --------------------------------------------------------------------------- #
# the payload -> the spec's stack
# --------------------------------------------------------------------------- #
def test_the_stack_is_parsed_clamped_and_deduped():
    spec = ss.parse_sheet_spec({
        "loras": [
            {"file": "Minimax/alpha.safetensors", "strength": 0.8},
            {"file": "Minimax/alpha.safetensors", "strength": 1.5},   # a repeat: the last wins
            {"file": "beta.safetensors", "strength": 99, "on": False},  # clamped, switched off
        ]
    })
    assert [(entry.file, entry.strength, entry.on) for entry in spec.loras] == [
        ("Minimax/alpha.safetensors", 1.5, True),
        ("beta.safetensors", ss.LORA_STRENGTH_RANGE[1], False),
    ]
    # One LoRA, one entry: a stack that names the same file twice is a strength typo.
    assert len({entry.file for entry in spec.loras}) == len(spec.loras)


def test_a_hand_written_stack_may_be_a_string():
    spec = ss.parse_sheet_spec({"loras": "Minimax/alpha.safetensors@0.65, beta.safetensors"})
    assert [(entry.file, entry.strength) for entry in spec.loras] == [
        ("Minimax/alpha.safetensors", 0.65),
        ("beta.safetensors", ss.DEFAULT_LORA_STRENGTH),
    ]
    # A loader widget writes the file's own name: a Windows-style separator and a leading "./"
    # are the same file, and the node has to look it up the way folder_paths does.
    spec = ss.parse_sheet_spec({"loras": [{"file": ".\\Minimax\\alpha.safetensors"}]})
    assert spec.loras[0].file == "Minimax/alpha.safetensors"


def test_a_stack_longer_than_the_cap_is_refused_with_a_warning():
    spec = ss.parse_sheet_spec({
        "loras": [{"file": f"lora{i}.safetensors"} for i in range(ss.MAX_LORAS + 4)]
    })
    assert len(spec.loras) == ss.MAX_LORAS
    assert any("more than" in line and "loras" in line for line in spec.warnings), spec.warnings


def test_nothing_in_the_payload_means_no_stack():
    for raw in (None, "", [], {}, "   ", 7):
        spec = ss.parse_sheet_spec({"loras": raw} if raw is not None else {})
        assert spec.loras == [], raw


def test_the_round_trip_keeps_the_stack():
    spec = ss.parse_sheet_spec({"loras": [{"file": "beta.safetensors", "strength": 0.5, "on": False}]})
    payload = spec.to_dict()
    assert payload["loras"] == [{"file": "beta.safetensors", "strength": 0.5, "on": False}]
    again = ss.parse_sheet_spec(payload)
    assert [(entry.file, entry.strength, entry.on) for entry in again.loras] == [
        ("beta.safetensors", 0.5, False)
    ]


def test_a_lora_entry_labels_itself_without_its_extension():
    entry = ss.SheetLora(file="Minimax/MM-H3 - Fingering v4.safetensors")
    assert entry.label() == "MM-H3 - Fingering v4"


# --------------------------------------------------------------------------- #
# the file -> the digest
# --------------------------------------------------------------------------- #
def test_the_digest_is_the_digest_of_the_file(loras):
    answer = lib.file_hash("beta.safetensors")
    assert answer["ok"] is True
    assert answer["sha256"] == hashlib.sha256(loras["beta.safetensors"].read_bytes()).hexdigest()
    assert answer["sha256"] == lib.sha256_of(loras["beta.safetensors"])


def test_the_digest_is_computed_once_per_version_of_the_file(loras, monkeypatch):
    reads: list[str] = []
    real = lib.sha256_of

    def counted(path, *, chunk=lib.HASH_CHUNK):
        reads.append(str(path))
        return real(path, chunk=chunk)

    monkeypatch.setattr(lib, "sha256_of", counted)
    assert lib.file_hash("beta.safetensors")["cached"] is False
    assert lib.file_hash("beta.safetensors")["cached"] is True
    assert len(reads) == 1, "a cached digest must not re-read the file"
    # A replaced file is a different file: the digest has to be taken again.
    loras["beta.safetensors"].write_bytes(b"b" * 4096)
    assert lib.file_hash("beta.safetensors")["cached"] is False
    assert len(reads) == 2


def test_hashing_something_that_is_not_installed_is_an_answer(loras):
    answer = lib.file_hash("nope.safetensors")
    assert answer["ok"] is False and "not in models/loras" in answer["error"]


# --------------------------------------------------------------------------- #
# the metadata the panel owns
# --------------------------------------------------------------------------- #
def test_the_metadata_keeps_the_fields_the_panel_owns_and_drops_the_rest(loras):
    saved = lib.save_metadata("beta.safetensors", {
        "name": "Fingering - Minimax H3 v4",
        "strengthMin": -9,
        "strengthMax": "1.75",
        "notes": "  trained on 4s clips  ",
        "somethingElse": "ignore me",
    })
    assert saved["ok"] is True
    record = lib.record_for("beta.safetensors")
    assert record["name"] == "Fingering - Minimax H3 v4"
    assert record["strengthMin"] == ss.LORA_STRENGTH_RANGE[0]
    assert record["strengthMax"] == 1.75
    assert record["notes"] == "trained on 4s clips"
    assert "somethingElse" not in record
    # A later save of one field leaves the others alone: the card's fields are edited one by one.
    lib.save_metadata("beta.safetensors", {"notes": "second pass"})
    assert lib.record_for("beta.safetensors")["name"] == "Fingering - Minimax H3 v4"
    assert lib.record_for("beta.safetensors")["notes"] == "second pass"


def test_a_file_the_panel_wrote_text_for_is_still_bounded(loras):
    lib.save_metadata("beta.safetensors", {"name": "x" * 400, "notes": "y" * 9000})
    record = lib.record_for("beta.safetensors")
    assert len(record["name"]) == lib.MAX_NAME_LENGTH
    assert len(record["notes"]) == lib.MAX_NOTE_LENGTH


def test_the_listing_carries_the_metadata_and_marks_a_file_that_is_gone(loras):
    lib.save_metadata("beta.safetensors", {"name": "Beta", "notes": "n"})
    lib.save_metadata("gone.safetensors", {"name": "Gone"})  # metadata without a file on disk
    answer = lib.listing()
    by_file = {item["file"]: item for item in answer["items"]}
    assert set(by_file) == {"Minimax/alpha.safetensors", "beta.safetensors", "gone.safetensors"}
    assert by_file["beta.safetensors"]["name"] == "Beta"
    assert by_file["beta.safetensors"]["label"] == "Beta"
    assert by_file["Minimax/alpha.safetensors"]["label"] == "alpha"
    assert by_file["Minimax/alpha.safetensors"]["folder"] == "Minimax"
    assert by_file["gone.safetensors"]["missing"] is True
    assert answer["missing"] == 1 and answer["count"] == 3
    json.dumps(answer)  # the panel parses this


# --------------------------------------------------------------------------- #
# Civitai
# --------------------------------------------------------------------------- #
_CIVITAI_ANSWER = {
    "id": 1234567,
    "modelId": 7654321,
    "name": "v4",
    "baseModel": "MiniMax H3",
    "description": "<p>Great for <b>close-ups</b>.<br />Use at 0.8.</p>",
    "trainedWords": ["fingering", "pov"],
    "tags": ["lora", "hands"],
    "model": {"id": 7654321, "name": "Fingering - Minimax H3", "type": "LORA", "nsfw": False,
              "tags": ["lora"]},
    "creator": {"username": "someone"},
    "images": [{"url": "https://image.civitai.com/a.jpeg"}, {"url": "https://image.civitai.com/b.jpeg"}],
}

_DIGEST = hashlib.sha256(b"x").hexdigest()


def test_a_civitai_answer_is_shaped_for_the_panel(monkeypatch):
    monkeypatch.setattr(lib, "_get_json", lambda url, **kwargs: dict(_CIVITAI_ANSWER))
    info = lib.civitai_lookup(_DIGEST)
    assert info["found"] is True
    assert info["modelName"] == "Fingering - Minimax H3"
    assert info["versionName"] == "v4"
    assert info["baseModel"] == "MiniMax H3"
    assert info["creator"] == "someone"
    assert info["trainedWords"] == ["fingering", "pov"]
    assert info["tags"] == ["lora", "hands"]
    assert info["url"] == "https://civitai.com/models/7654321?modelVersionId=1234567"
    # The description is HTML in, readable text out: the card is a card, not a web view.
    assert "<" not in info["description"] and "close-ups" in info["description"]
    assert info["lookupUrl"].endswith(_DIGEST)
    json.dumps(info)


def test_a_page_whose_samples_are_loops_still_gives_the_card_a_still(monkeypatch):
    """Civitai's LoRA samples are often .mp4 loops, and an <img> of one draws nothing."""
    answer = dict(_CIVITAI_ANSWER)
    answer["images"] = [
        {"url": "https://image.civitai.com/loop.mp4"},
        {"url": "https://image.civitai.com/still.jpeg"},
        {"url": "https://image.civitai.com/another.png"},
    ]
    monkeypatch.setattr(lib, "_get_json", lambda url, **kwargs: answer)
    info = lib.civitai_lookup(_DIGEST)
    assert info["images"] == [
        "https://image.civitai.com/still.jpeg", "https://image.civitai.com/another.png"
    ], "a still is preferred for the thumbnail"
    assert info["videos"] == ["https://image.civitai.com/loop.mp4"], "the loop is kept, as a video"


def test_a_hash_civitai_does_not_know_is_an_answer_not_an_error(monkeypatch):
    def missing(url, **kwargs):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(lib, "_get_json", missing)
    info = lib.civitai_lookup(_DIGEST)
    assert info["found"] is False and "no model version" in info["error"]


def test_being_offline_is_an_answer_too(monkeypatch):
    def offline(url, **kwargs):
        raise OSError("Name or service not known")

    monkeypatch.setattr(lib, "_get_json", offline)
    info = lib.civitai_lookup(_DIGEST)
    assert info["found"] is False and "Could not reach Civitai" in info["error"]
    assert lib.civitai_lookup("not-a-hash")["found"] is False


def test_fetch_info_remembers_the_answer_and_can_be_forced(loras, monkeypatch):
    calls: list[str] = []

    def answer(url, **kwargs):
        calls.append(url)
        return dict(_CIVITAI_ANSWER)

    monkeypatch.setattr(lib, "_get_json", answer)
    first = lib.fetch_info("beta.safetensors")
    assert first["civitai"]["found"] is True and first["cached"] is False
    second = lib.fetch_info("beta.safetensors")
    assert second["cached"] is True and len(calls) == 1, "a stored answer is not re-fetched"
    forced = lib.fetch_info("beta.safetensors", force=True)
    assert forced["cached"] is False and len(calls) == 2
    # And the panel's card can read it back from the listing without another request.
    item = next(entry for entry in lib.listing()["items"] if entry["file"] == "beta.safetensors")
    assert item["civitai"]["modelName"] == "Fingering - Minimax H3"
    assert item["sha256"] == lib.file_hash("beta.safetensors")["sha256"]


def test_a_file_civitai_does_not_have_says_so_and_is_not_asked_again(loras, monkeypatch):
    monkeypatch.setattr(lib, "civitai_lookup", lambda digest: {"found": False, "error": "nothing"})
    lib.fetch_info("beta.safetensors")
    item = next(entry for entry in lib.listing()["items"] if entry["file"] == "beta.safetensors")
    assert item["civitai"] is None and item["civitaiError"] == "nothing"


# --------------------------------------------------------------------------- #
# the stack -> the model
# --------------------------------------------------------------------------- #
def test_the_stack_is_applied_in_order_with_the_strengths_it_carries(loras, fake_comfy):
    model, lines, warnings = lib.apply_stack(
        "MODEL", _stack(("Minimax/alpha.safetensors", 0.8), ("beta.safetensors", 1.25))
    )
    assert warnings == []
    assert [call[2] for call in fake_comfy["apply"]] == [0.8, 1.25], "each entry keeps its strength"
    assert fake_comfy["apply"][0][0] == "MODEL", "the first LoRA loads onto the model that came in"
    assert fake_comfy["apply"][1][0] == "patched<MODEL|0.8>", "and the next onto the result"
    assert model == "patched<patched<MODEL|0.8>|1.25>"
    assert lines == ["LoRA stack: Minimax/alpha.safetensors@0.8, beta.safetensors@1.25"]
    assert [str(path) for path in fake_comfy["files"]] == [
        str(loras["Minimax/alpha.safetensors"]), str(loras["beta.safetensors"])
    ]


def test_a_switched_off_entry_and_a_zero_strength_are_not_loaded(loras, fake_comfy):
    stack = [
        ss.SheetLora(file="Minimax/alpha.safetensors", strength=0.8),
        ss.SheetLora(file="beta.safetensors", strength=1.0, on=False),
    ]
    model, lines, warnings = lib.apply_stack("MODEL", stack)
    assert [call[1] for call in fake_comfy["apply"]] == [str(loras["Minimax/alpha.safetensors"])]
    assert model == "patched<MODEL|0.8>" and warnings == []
    _, _, warnings = lib.apply_stack("MODEL", [ss.SheetLora(file="beta.safetensors", strength=0.0)])
    assert fake_comfy["apply"][-1][1] == str(loras["Minimax/alpha.safetensors"]), "strength 0 loads nothing"
    assert warnings == []


def test_a_missing_file_and_a_broken_file_are_warnings_not_failures(loras, fake_comfy, monkeypatch):
    sd = pytest.importorskip("comfy.sd")

    def explode(model, clip, lora, strength_model, strength_clip, lora_metadata=None):
        raise RuntimeError("not a LoRA")

    monkeypatch.setattr(sd, "load_lora_for_models", explode)
    model, lines, warnings = lib.apply_stack(
        "MODEL",
        [ss.SheetLora(file="nope.safetensors"), ss.SheetLora(file="beta.safetensors")],
    )
    assert model == "MODEL", "a render with a bad stack still renders"
    assert any("not in models/loras" in line for line in warnings), warnings
    assert any("could not be loaded" in line for line in warnings), warnings
    assert lines == warnings, "the report says the same thing the panel was warned about"


def test_an_empty_stack_leaves_the_model_alone(fake_comfy):
    model, lines, warnings = lib.apply_stack("MODEL", [])
    assert (model, lines, warnings) == ("MODEL", [], [])
    assert fake_comfy["apply"] == []


# --------------------------------------------------------------------------- #
# the routes
# --------------------------------------------------------------------------- #
class _Request:
    """Bare minimum of an aiohttp request: a JSON body and a query string."""

    def __init__(self, body=None, params=None):
        self._body = body if body is not None else {}
        self.rel_url = types.SimpleNamespace(query=params or {})

    async def json(self):
        return self._body


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status


@pytest.fixture(autouse=True)
def _stub_responses(monkeypatch):
    monkeypatch.setattr(
        sheet_routes.web, "json_response", lambda payload, status=200: _Response(payload, status)
    )


def _action(body):
    return asyncio.run(sheet_routes.sheet_action(_Request(body)))


def test_the_lora_actions_are_registered():
    """An action the dispatcher does not know is a 400 in the user's face."""
    for name in ("lora-info", "lora-save"):
        assert name in sheet_routes._ACTIONS, name


def test_the_lora_list_route_answers_the_panel(loras):
    response = asyncio.run(sheet_routes.sheet_lora_list(_Request(params={})))
    assert response.status == 200
    assert response.payload["ok"] is True
    assert {item["file"] for item in response.payload["items"]} == {
        "Minimax/alpha.safetensors", "beta.safetensors"
    }


def test_the_info_action_hashes_first_and_only_asks_civitai_when_told(loras, monkeypatch):
    monkeypatch.setattr(lib, "civitai_lookup", lambda digest: {"found": True, "hash": digest})
    hashed = _action({"action": "lora-info", "file": "beta.safetensors"}).payload
    assert hashed["ok"] is True and hashed["sha256"] and hashed["civitai"] is None
    assert hashed["fetched"] is False
    fetched = _action({"action": "lora-info", "file": "beta.safetensors", "fetch": True}).payload
    assert fetched["civitai"]["found"] is True and fetched["fetched"] is True
    # A file that is not installed is a normal answer for a row that points at nothing.
    broken = _action({"action": "lora-info", "file": "nope.safetensors"})
    assert broken.status == 400 and broken.payload["ok"] is False
    assert _action({"action": "lora-info"}).status == 400


def test_the_save_action_stores_the_fields_the_card_edits(loras):
    saved = _action({
        "action": "lora-save",
        "file": "beta.safetensors",
        "name": "Beta v2",
        "strengthMin": 0.25,
        "strengthMax": 1.5,
        "notes": "needs 8 steps",
    }).payload
    assert saved["ok"] is True and saved["action"] == "lora-save"
    assert saved["record"]["name"] == "Beta v2"
    assert lib.record_for("beta.safetensors")["notes"] == "needs 8 steps"
    assert _action({"action": "lora-save"}).status == 400
