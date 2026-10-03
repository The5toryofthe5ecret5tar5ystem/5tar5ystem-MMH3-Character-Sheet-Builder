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
