# ComfyUI-H3-Character-Sheet - output name placeholders.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""``%date:...%`` in the sheet name, expanded the way the other packs here do it.

Core ``SaveImage`` does **not** expand these placeholders: it writes the literal
text into the filename (verified against this build - ``character_sheet-%date:hhmmss%``
produced a file with that name). The token syntax comes from packs that implement it
themselves (DaSiWa's savers, CGlide's video node), so a name copied from one of those
workflows silently does nothing in a core saver.

This module implements the same vocabulary, byte for byte, so a name that works in a
DaSiWa workflow works here too:

* ``%date%`` - ``yyyyMMdd_HHmmss``
* ``%date:hhmmss%`` - any combination of ``yyyy yy MM dd DD HH hh mm ss``
* ``%seed%`` - the sheet's seed

A tokenised name also has to be *findable*: ``folder_pattern`` gives the glob the
store and the panel route use to pick the newest run, because the panel only ever
knows the literal name the user typed.

A plain name is stamped instead (``export_stem``): the export is then a new file
every run - same folder, dated name, never an overwrite - and the manifest records
which file the run wrote so the panel follows the newest one.
"""

from __future__ import annotations

import datetime as _datetime
import re

#: ``%date%`` / ``%date:<format>%`` - the format part stops at the next ``%``.
DATE_RE = re.compile(r"%date(?::([^%]+))?%")

#: Java-style tokens -> strftime, in this order: ``yyyy`` must be replaced before
#: ``yy``, and ``MM`` (month) before ``mm`` (minute).
DATE_TOKEN_MAP: tuple[tuple[str, str], ...] = (
    ("yyyy", "%Y"),
    ("yy", "%y"),
    ("MM", "%m"),
    ("dd", "%d"),
    ("DD", "%d"),
    ("HH", "%H"),
    ("hh", "%H"),
    ("mm", "%M"),
    ("ss", "%S"),
)

DEFAULT_DATE_FORMAT = "yyyyMMdd_HHmmss"

#: Stamp added to a name that carries no placeholder, so two runs never share a file.
AUTO_STAMP_FORMAT = "%Y%m%d-%H%M%S"


def has_tokens(text: object) -> bool:
    """Does this name contain anything that needs expanding?"""
    value = str(text or "")
    return bool(DATE_RE.search(value)) or "%seed%" in value


def expand_tokens(text: object, *, seed: int | None = None, now: _datetime.datetime | None = None) -> str:
    """Expand the placeholders; anything unrecognised is left exactly as typed."""
    value = str(text or "")
    clock = now or _datetime.datetime.now()

    def replace_date(match: re.Match[str]) -> str:
        fmt = match.group(1) or DEFAULT_DATE_FORMAT
        for token, directive in DATE_TOKEN_MAP:
            fmt = fmt.replace(token, directive)
        try:
            return clock.strftime(fmt)
        except ValueError:
            # A stray '%' in the format would make strftime raise; keep the literal.
            return match.group(0)

    value = DATE_RE.sub(replace_date, value)
    if seed is not None:
        value = value.replace("%seed%", str(int(seed)))
    return value


def export_stem(name: object, *, seed: int | None = None, now: _datetime.datetime | None = None) -> str:
    """File stem for a run: the expanded placeholders, or the name plus a stamp.

    ``character_sheet-%date:hhmmss%`` -> ``character_sheet-180705`` (the user asked
    for the date, so that IS the name) and plain ``character_sheet`` ->
    ``character_sheet-20261002-180705``. Either way the run writes a distinct file
    in the same folder instead of overwriting the previous sheet.
    """
    value = str(name or "").strip() or "character_sheet"
    if has_tokens(value):
        return expand_tokens(value, seed=seed, now=now)
    clock = now or _datetime.datetime.now()
    return f"{value}-{clock.strftime(AUTO_STAMP_FORMAT)}"


def folder_pattern(name: object) -> str | None:
    """Glob for the newest run of a tokenised name (None when the name is literal).

    ``character_sheet-%date:hhmmss%`` -> ``character_sheet-*``: the panel only knows
    the literal name, so that is how it finds the folder the run actually wrote.
    """
    value = str(name or "")
    if not has_tokens(value):
        return None
    positions = [index for index in (value.find("%date"), value.find("%seed%")) if index >= 0]
    head = value[: min(positions)] if positions else value
    return f"{head}*"


def is_expanded(name: object) -> bool:
    """A name that no longer contains placeholders (so a glob match is a real run)."""
    return not has_tokens(name) and "%" not in str(name or "")


__all__ = [
    "AUTO_STAMP_FORMAT",
    "DATE_RE",
    "DATE_TOKEN_MAP",
    "DEFAULT_DATE_FORMAT",
    "expand_tokens",
    "export_stem",
    "folder_pattern",
    "has_tokens",
    "is_expanded",
]
