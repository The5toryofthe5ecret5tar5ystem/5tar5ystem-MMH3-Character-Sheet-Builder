# ComfyUI-H3-Character-Sheet - custom node entry point.
# Distributed under GNU GPL v3.0. See LICENSE and NOTICE.
#
# ComfyUI loads a custom node directory as a package by executing this file with
# submodule_search_locations pointing at the pack root, so relative imports work and
# the implementation can live in the ``h3_character_sheet`` subpackage (which keeps
# pytest, the test aliases and the deployed copy identical).

from __future__ import annotations

import os
import sys

try:
    from .h3_character_sheet import (
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
        WEB_DIRECTORY,
    )
except ImportError:  # pragma: no cover - only when executed as a plain file
    # Pytest may import this file without a package (the checkout directory has
    # hyphens, so it is not a valid module name). Import the subpackage directly and
    # keep the same public names so every caller sees one shape.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from h3_character_sheet import (
        NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS,
        WEB_DIRECTORY,
    )

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
