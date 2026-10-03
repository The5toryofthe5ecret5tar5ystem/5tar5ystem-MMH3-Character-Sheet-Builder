# ComfyUI-H3-Character-Sheet - verbose logging switch.
# Distributed under GNU GPL v3.0. See repository LICENSE.

"""Raise/lower this pack's own loggers for a run, from the node's widget.

Same contract as the Motion Director's switch: the widget (or the environment
variable) turns DEBUG on for ``H3-Character-Sheet*`` loggers only, the previous
levels are restored when it is turned off, and the environment always wins. Never
raises - a logging problem must not fail a render.
"""

from __future__ import annotations

import logging
import os

ENV_OVERRIDE = "H3_CHARACTER_SHEET_VERBOSE"
LOG_PREFIX = "H3-Character-Sheet"

_TOUCHED: dict[str, int] = {}
_ON = False

_TRUTHY = {"1", "true", "on", "yes"}
_FALSY = {"0", "false", "off", "no"}


def _env_override() -> bool | None:
    raw = os.environ.get(ENV_OVERRIDE)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    return None


def _pack_loggers() -> list[logging.Logger]:
    found = [
        logging.getLogger(name)
        for name in list(logging.root.manager.loggerDict)
        if name.startswith(LOG_PREFIX)
    ]
    root = logging.getLogger(LOG_PREFIX)
    if root not in found:
        found.append(root)
    return found


def apply_verbose(widget_value: object) -> bool:
    """Enable/disable DEBUG for this pack's loggers; returns the effective state."""
    global _ON
    override = _env_override()
    enabled = bool(widget_value) if override is None else override
    try:
        if enabled and not _ON:
            for logger in _pack_loggers():
                _TOUCHED[logger.name] = logger.level
                logger.setLevel(logging.DEBUG)
            _ON = True
        elif not enabled and _ON:
            for name, level in _TOUCHED.items():
                logging.getLogger(name).setLevel(level)
            _TOUCHED.clear()
            _ON = False
    except Exception:  # noqa: BLE001 - logging must never break a render
        return _ON
    return _ON


__all__ = ["ENV_OVERRIDE", "LOG_PREFIX", "apply_verbose"]
