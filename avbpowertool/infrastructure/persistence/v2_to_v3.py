"""v2 -> v3 profile migration (read-only derivation).

v3 changes vs v2:

* ``data_block_size`` / ``hash_block_size`` collapse into a single
  ``block_size`` (avbtool ``add_hashtree_footer`` only accepts one
  ``--block_size``); when the two v2 values differ the data block size
  wins and a warning issue is emitted.
* ``kernel_cmdline: str`` becomes ``kernel_cmdlines: list[str]``
  (avbtool accepts repeated ``--kernel_cmdline``).
* every other new v3 field is left at its default.

The migration never writes to disk — the caller decides when to persist
the migrated dict (e.g. ``config migrate``).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from avbpowertool.domain.models import OperationIssue

#: schema_version written by migration (== profile_codec.SCHEMA_VERSION)
V3_SCHEMA_VERSION = 3


def migrate_v2_to_v3(
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[OperationIssue]]:
    """Migrate a v2 profile dict to v3.

    Returns a ``(v3_data, issues)`` tuple.  ``data`` is not modified.
    """
    issues: list[OperationIssue] = []
    migrated = deepcopy(data)
    migrated["schema_version"] = V3_SCHEMA_VERSION

    partitions = migrated.get("partitions")
    if not isinstance(partitions, dict):
        return migrated, issues

    for name, entry in partitions.items():
        if not isinstance(entry, dict):
            continue

        # data_block_size / hash_block_size -> single block_size
        data_block = entry.get("data_block_size")
        hash_block = entry.get("hash_block_size")
        if data_block is not None or hash_block is not None:
            if (
                data_block is not None
                and hash_block is not None
                and int(data_block) != int(hash_block)
            ):
                issues.append(
                    OperationIssue(
                        "migrate.v2_to_v3.block_size_conflict",
                        f"Partition {name!r}: data_block_size={data_block} differs from "
                        f"hash_block_size={hash_block}; using {data_block} as block_size",
                    )
                )
            block_size = data_block if data_block is not None else hash_block
            entry["block_size"] = int(block_size)
            entry.pop("data_block_size", None)
            entry.pop("hash_block_size", None)

        # kernel_cmdline: str -> kernel_cmdlines: [str]
        cmdline = entry.get("kernel_cmdline")
        if isinstance(cmdline, str) and cmdline:
            entry["kernel_cmdlines"] = [cmdline]
        entry.pop("kernel_cmdline", None)

    return migrated, issues
