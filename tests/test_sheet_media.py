# ComfyUI-H3-Character-Sheet - media browser tests.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Tests for the reference picker's folder listing.

The panel's ``Browse`` overlay depends on this contract: relative paths the node
can feed into core loaders, ``/view`` URLs it can render as thumbnails, kinds it
can filter on, and a hard guarantee that a request cannot walk out of the folder
it was pointed at.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from h3cs import sheet_media as sm


@pytest.fixture()
def media_tree(tmp_path: Path) -> Path:
    root = tmp_path / "input"
    (root / "h3_character_sheet").mkdir(parents=True)
    (root / "sub dir").mkdir()
    (root / "face.png").write_bytes(b"png")
    (root / "notes.txt").write_text("not media", encoding="utf-8")
    (root / "clip.mp4").write_bytes(b"mp4")
    (root / "voice.wav").write_bytes(b"wav")
    (root / "h3_character_sheet" / "hero.webp").write_bytes(b"webp")
    (root / "h3_character_sheet" / "walk.mkv").write_bytes(b"mkv")
    (root / "sub dir" / "take2.mp3").write_bytes(b"mp3")
    return root


# --------------------------------------------------------------------------- #
# kinds
# --------------------------------------------------------------------------- #
def test_file_kind_covers_whitelist_and_mimetypes():
    assert sm.file_kind("a.PNG") == "image"
    assert sm.file_kind("a.webp") == "image"
    assert sm.file_kind("a.mkv") == "video"     # not in Python's mimetypes table
    assert sm.file_kind("a.mp4") == "video"
    assert sm.file_kind("a.flac") == "audio"
    assert sm.file_kind("a.txt") is None
    assert sm.file_kind("noextension") is None


def test_allowed_names_filters_by_kind(media_tree: Path):
    names = ["face.png", "clip.mp4", "voice.wav", "notes.txt"]
    assert sm.allowed_names(names, "image") == ["face.png"]
    assert sm.allowed_names(names, "video") == ["clip.mp4"]
    assert sm.allowed_names(names, "audio") == ["voice.wav"]
    assert sm.allowed_names(names, "all") == ["face.png", "clip.mp4", "voice.wav"]


def test_unknown_kind_and_source_fall_back(media_tree: Path):
    assert sm.normalize_kind("banana") == "all"
    assert sm.normalize_source("somewhere") == "inputs"
    payload = sm.list_media("somewhere", "banana", base_dir=media_tree)
    assert payload["source"] == "inputs"
    assert payload["kind"] == "all"


# --------------------------------------------------------------------------- #
# URLs
# --------------------------------------------------------------------------- #
def test_view_url_matches_the_core_shape():
    assert sm.view_url("face.png", "inputs") == "/view?filename=face.png&type=input&subfolder="
    assert sm.view_url("hero.webp", "inputs", "h3_character_sheet") == (
        "/view?filename=hero.webp&type=input&subfolder=h3_character_sheet"
    )
    assert sm.view_url("out.mp4", "outputs", "renders") == (
        "/view?filename=out.mp4&type=output&subfolder=renders"
    )


def test_view_url_escapes_spaces_and_keeps_a_single_filename():
    url = sm.view_url("sub/my clip.mp4", "inputs", "sub folder")
    assert "filename=my%20clip.mp4" in url
    assert "subfolder=sub%20folder" in url
    assert "/" not in url.split("filename=")[1].split("&")[0]


# --------------------------------------------------------------------------- #
# listing
# --------------------------------------------------------------------------- #
def test_shallow_listing_separates_folders_files_and_kinds(media_tree: Path):
    payload = sm.list_media("inputs", "all", base_dir=media_tree)
    assert payload["ok"] is True
    assert [folder["path"] for folder in payload["folders"]] == ["h3_character_sheet", "sub dir"]
    assert [item["name"] for item in payload["items"]] == ["clip.mp4", "face.png", "voice.wav"]
    assert {item["kind"] for item in payload["items"]} == {"video", "image", "audio"}
    face = next(item for item in payload["items"] if item["name"] == "face.png")
    assert face["path"] == "face.png"
    assert face["subfolder"] == ""
    assert face["url"].startswith("/view?filename=face.png&type=input")
    assert face["size"] == 3
    assert face["mtime"] > 0


def test_shallow_listing_filters_by_kind(media_tree: Path):
    payload = sm.list_media("inputs", "audio", base_dir=media_tree)
    assert [item["name"] for item in payload["items"]] == ["voice.wav"]


def test_recursive_listing_finds_subfolders_with_their_paths(media_tree: Path):
    payload = sm.list_media("inputs", "all", recursive=True, base_dir=media_tree)
    # recursive listings are newest-first, so compare as a set
    assert sorted(item["name"] for item in payload["items"]) == [
        "clip.mp4", "face.png", "hero.webp", "take2.mp3", "voice.wav", "walk.mkv",
    ]
    hero = next(item for item in payload["items"] if item["name"] == "hero.webp")
    assert hero["path"] == "h3_character_sheet/hero.webp"
    assert hero["subfolder"] == "h3_character_sheet"
    assert "subfolder=h3_character_sheet" in hero["url"]


def test_recursive_listing_is_newest_first(media_tree: Path):
    newest = media_tree / "h3_character_sheet" / "hero.webp"
    os.utime(newest, (9_000_000_000, 9_000_000_000))
    payload = sm.list_media("inputs", "image", recursive=True, base_dir=media_tree)
    assert [item["name"] for item in payload["items"]] == ["hero.webp", "face.png"]


def test_query_filters_on_the_file_name(media_tree: Path):
    payload = sm.list_media("inputs", "all", query="FA", base_dir=media_tree)
    assert [item["name"] for item in payload["items"]] == ["face.png"]
    recursive = sm.list_media("inputs", "all", query="walk", recursive=True, base_dir=media_tree)
    assert [item["name"] for item in recursive["items"]] == ["walk.mkv"]


def test_subfolder_listing_and_parent(media_tree: Path):
    payload = sm.list_media("inputs", "all", "h3_character_sheet", base_dir=media_tree)
    assert payload["subfolder"] == "h3_character_sheet"
    assert payload["parent"] == ""
    assert [item["path"] for item in payload["items"]] == [
        "h3_character_sheet/hero.webp", "h3_character_sheet/walk.mkv",
    ]


def test_limit_and_truncated_flag(media_tree: Path):
    payload = sm.list_media("inputs", "all", recursive=True, limit=2, base_dir=media_tree)
    assert len(payload["items"]) == 2
    assert payload["truncated"] is True
    payload = sm.list_media("inputs", "all", recursive=True, limit=0, base_dir=media_tree)
    assert payload["truncated"] is False


def test_missing_folder_is_a_clean_error(media_tree: Path):
    payload = sm.list_media("inputs", "all", base_dir=media_tree / "nope")
    assert payload["ok"] is False
    assert "not a folder" in payload["error"]
    assert payload["items"] == []


def test_no_base_dir_is_reported_without_raising(tmp_path: Path):
    payload = sm.list_media("outputs", "all", base_dir=tmp_path / "gone")
    assert payload["ok"] is False
    assert payload["items"] == []


# --------------------------------------------------------------------------- #
# security
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("subfolder", ["..", "../..", "../outside", "/etc", "a/../../.."])
def test_path_traversal_is_refused(media_tree: Path, subfolder: str):
    payload = sm.list_media("inputs", "all", subfolder, base_dir=media_tree)
    assert payload["ok"] is False
    assert payload["items"] == []


def test_a_symlink_out_of_the_tree_is_not_followed(media_tree: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"x")
    link = media_tree / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:  # pragma: no cover - shares without symlink support
        pytest.skip("symlinks unavailable on this filesystem")
    payload = sm.list_media("inputs", "all", "escape", base_dir=media_tree)
    assert payload["ok"] is False


# --------------------------------------------------------------------------- #
# cost: the budget, the cache, and what the walk refuses to follow
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clean_cache():
    """The listing cache is process-wide; a test must not inherit another one's answer."""
    sm.reset_cache()
    yield
    sm.reset_cache()


def test_a_scan_budget_answers_with_what_it_has(media_tree: Path):
    """A cold network share has measured 31s: a picker may not wait for that.

    The deadline is checked between batches of files and between directories, so a tree smaller than
    one batch still finishes - what has to be true is that running out of time is REPORTED, and that
    what it did find is a subset of the real answer.
    """
    capped = sm.list_media("inputs", "all", recursive=True, base_dir=media_tree, budget_ms=0)
    assert capped["partial"] is True
    full = sm.list_media("inputs", "all", recursive=True, base_dir=media_tree)
    assert full["partial"] is False
    assert {item["path"] for item in capped["items"]} <= {item["path"] for item in full["items"]}
    assert len(full["items"]) == 6


def test_the_listing_says_what_it_cost(media_tree: Path):
    payload = sm.list_media("inputs", "all", recursive=True, base_dir=media_tree)
    assert payload["recursive"] is True
    assert isinstance(payload["scanMs"], float) and payload["scanMs"] >= 0
    shallow = sm.list_media("inputs", "all", base_dir=media_tree)
    assert shallow["recursive"] is False
    assert isinstance(shallow["scanMs"], float)


def test_the_walk_does_not_descend_a_symlinked_folder(media_tree: Path, tmp_path: Path):
    """The recursive walk's escape guarantee, now checked per DIRECTORY instead of per file."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"x")
    link = media_tree / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:  # pragma: no cover - shares without symlink support
        pytest.skip("symlinks unavailable on this filesystem")
    payload = sm.list_media("inputs", "all", recursive=True, base_dir=media_tree)
    assert payload["ok"] is True
    assert "link/secret.png" not in [item["path"] for item in payload["items"]]


def test_the_second_listing_is_served_from_the_cache(media_tree: Path, monkeypatch: pytest.MonkeyPatch):
    walked: list[str] = []
    real = sm.list_media

    def counted(*args, **kwargs):
        walked.append(str(kwargs.get("subfolder", "")))
        return real(*args, **kwargs)

    monkeypatch.setattr(sm, "list_media", counted)
    first = sm.cached_media("inputs", "all", base_dir=media_tree)
    second = sm.cached_media("inputs", "all", base_dir=media_tree)
    assert len(walked) == 1, "the second answer must not touch the filesystem"
    assert first["cached"] is False and first["stale"] is False
    assert second["cached"] is True and second["stale"] is False
    # ...and a different request is its own entry, not a hit on someone else's answer.
    other = sm.cached_media("inputs", "audio", base_dir=media_tree)
    assert len(walked) == 2
    assert [item["name"] for item in other["items"]] == ["voice.wav"]


def test_a_stale_listing_is_served_while_it_refreshes(media_tree: Path, monkeypatch: pytest.MonkeyPatch):
    scheduled: list[tuple] = []
    monkeypatch.setattr(sm, "_schedule", lambda key, kwargs: scheduled.append(key))
    start = 1_000.0
    sm.cached_media("inputs", "all", base_dir=media_tree, now=start)
    assert scheduled == [], "a fresh listing needs no refresh"
    again = sm.cached_media("inputs", "all", base_dir=media_tree, now=start + sm.CACHE_TTL + 1)
    assert again["stale"] is True and again["cached"] is True
    assert again["items"], "and the stale answer is still a usable one"
    assert len(scheduled) == 1, "the refresh is on its way in the background"
    # A different folder is a different entry: it must not be answered from this one.
    sm.cached_media("inputs", "all", "h3_character_sheet", base_dir=media_tree, now=start)
    assert len(scheduled) == 1


def test_a_partial_answer_is_never_used_as_a_complete_one(media_tree: Path,
                                                          monkeypatch: pytest.MonkeyPatch):
    scheduled: list[tuple] = []
    monkeypatch.setattr(sm, "_schedule", lambda key, kwargs: scheduled.append(key))
    partial = sm.cached_media("inputs", "all", recursive=True, base_dir=media_tree, budget_ms=0)
    assert partial["partial"] is True
    assert len(scheduled) == 1, "the rest of the walk is handed to a thread"
    after = sm.cached_media("inputs", "all", recursive=True, base_dir=media_tree)
    assert after["stale"] is True, "a capped scan may not be reused as if it were finished"


def test_a_background_refresh_replaces_what_the_cap_returned(media_tree: Path):
    """The thread's own path, run inline: it must store a complete listing for that key."""
    key = sm._cache_key(media_tree, "all", "", "", True, sm.DEFAULT_LIMIT)
    kwargs = {"source": "inputs", "kind": "all", "subfolder": "", "query": "",
              "recursive": True, "limit": sm.DEFAULT_LIMIT, "base_dir": media_tree}
    sm.cached_media("inputs", "all", recursive=True, base_dir=media_tree, budget_ms=0)
    sm._refresh(key, kwargs)
    with sm._cache_lock:
        stamp, payload = sm._cache[key]
    assert payload["partial"] is False
    assert len(payload["items"]) == 6
    # ...and the next request is a fresh cache hit of the FULL listing.
    full = sm.cached_media("inputs", "all", recursive=True, base_dir=media_tree)
    assert full["partial"] is False and full["stale"] is False
    assert len(full["items"]) == 6
