"""Parse raw avbtool.py info_image --image <path> stdout.

Indentation-based boundary detection — no hard-coded line jumps.
Independent of the legacy Core package; callers provide the raw
text output and receive typed dictionaries.
"""

from __future__ import annotations

from typing import Any


def _detect_desc_type(stripped: str) -> str:
    """Map a descriptor header line to its canonical type name."""
    lower = stripped.lower()
    if "chain partition" in lower:
        return "Chain Partition"
    if "hashtree" in lower:
        return "Hashtree"
    if "hash" in lower:
        return "Hash"
    if "kernel cmdline" in lower:
        return "Kernel Cmdline"
    return stripped.rstrip(":")


def parse_info_image(text: str) -> dict[str, Any]:
    """Parse the stdout of avbtool.py info_image.

    Returns a dictionary with three keys:

    ``header``
        Flat dict of top-level (indent-0) key-value pairs.
    ``descriptors``
        List of ``{"type": str, "fields": dict}`` blocks.
    ``props``
        List of ``(key, value)`` tuples from ``Prop:`` lines.
    """
    header_fields: dict[str, str] = {}
    desc_blocks: list[dict[str, Any]] = []
    prop_entries: list[tuple[str, str]] = []

    current_desc_type: str | None = None
    current_desc_fields: dict[str, str] = {}
    in_descriptors = False

    for line in text.split("\n"):
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent == 0:
            if stripped.startswith("Descriptors:"):
                in_descriptors = True
                continue
            if not in_descriptors and ":" in stripped:
                k, v = stripped.split(":", 1)
                header_fields[k.strip()] = v.strip()

        elif indent == 4 and in_descriptors:
            if current_desc_type is not None:
                desc_blocks.append({"type": current_desc_type, "fields": dict(current_desc_fields)})
                current_desc_fields.clear()

            if stripped.startswith("Prop:"):
                content = stripped[5:].strip()
                if " -> " in content:
                    k, v = content.split(" -> ", 1)
                    prop_entries.append((k, v.strip("'")))
                current_desc_type = None
            elif stripped == "(none)":
                current_desc_type = None
            else:
                current_desc_type = _detect_desc_type(stripped)

        elif indent == 6 and current_desc_type is not None:
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                current_desc_fields[k.strip()] = v.strip()

    # close final descriptor
    if current_desc_type is not None:
        desc_blocks.append({"type": current_desc_type, "fields": dict(current_desc_fields)})

    return {
        "header": header_fields,
        "descriptors": desc_blocks,
        "props": prop_entries,
    }
