"""Backward-compatible alias for the domain command builder.

The canonical implementation lives in ``avbpowertool/domain/command_builder.py``
(the signing plan is a domain concern, so command construction must not
depend on the infrastructure layer).  This module re-exports it for any
code that previously imported from the infrastructure path.
"""

from __future__ import annotations

from avbpowertool.domain.command_builder import (
    build_erase_footer_command,
    build_extract_public_key_command,
    build_hash_footer_command,
    build_hashtree_footer_command,
    build_inspect_command,
    build_vbmeta_command,
)

__all__ = [
    "build_erase_footer_command",
    "build_extract_public_key_command",
    "build_hash_footer_command",
    "build_hashtree_footer_command",
    "build_inspect_command",
    "build_vbmeta_command",
]
