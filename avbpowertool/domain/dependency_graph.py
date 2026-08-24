"""vbmeta dependency graph — topological ordering and cycle detection.

Determines the correct signing order when multiple vbmeta images have
chain partition relationships.
"""

from __future__ import annotations

from .models import DescriptorType, OperationIssue, PartitionConfig


def resolve_vbmeta_order(
    partitions: dict[str, PartitionConfig],
) -> tuple[tuple[str, ...], tuple[OperationIssue, ...]]:
    """Determine topological order for vbmeta image generation.

    Non-vbmeta images are signed first (order among them is alphabetical).
    vbmeta images are ordered so that a vbmeta that includes descriptors
    from another vbmeta (via chain partition) comes after the one it depends on.

    Returns:
        (ordered_vbmeta_names, issues)

    If a cycle or missing reference is detected, issues will contain the
    relevant error and the returned order may be partial.
    """
    issues: list[OperationIssue] = []

    # Separate vbmeta and non-vbmeta
    vbmeta_names: list[str] = []
    non_vbmeta_names: list[str] = []

    for name, config in partitions.items():
        if config.descriptor == DescriptorType.VBMETA:
            vbmeta_names.append(name)
        else:
            non_vbmeta_names.append(name)

    if not vbmeta_names:
        return ((), tuple(issues))

    # Build adjacency: vbmeta_name -> set of vbmeta names it depends on
    # A vbmeta depends on another vbmeta if that other vbmeta's partition name
    # appears in chain_partitions (format: "partition_name:rollback_loc:key_file")
    adjacency: dict[str, set[str]] = {name: set() for name in vbmeta_names}
    vbmeta_partition_to_name: dict[str, str] = {}

    for name in vbmeta_names:
        pname = partitions[name].partition_name
        vbmeta_partition_to_name[pname] = name

    for name in vbmeta_names:
        config = partitions[name]
        for chain_entry in config.chain_partitions:
            # chain format: "partition_name:rollback_index_location:key_filename"
            chain_partition = chain_entry.split(":")[0]
            if chain_partition in vbmeta_partition_to_name:
                dep_name = vbmeta_partition_to_name[chain_partition]
                if dep_name != name:
                    adjacency[name].add(dep_name)

        # Also check included_partitions for vbmeta-to-vbmeta deps
        for included in config.included_partitions:
            if included in vbmeta_partition_to_name:
                dep_name = vbmeta_partition_to_name[included]
                if dep_name != name:
                    adjacency[name].add(dep_name)

    # Validate references
    all_partition_names = set(partitions.keys())
    for name, config in partitions.items():
        for included in config.included_partitions:
            if included not in all_partition_names:
                issues.append(
                    OperationIssue(
                        "config.missing_included_partition",
                        f"Partition {name!r} includes {included!r}, which is not in the profile",
                    )
                )
        for chain_entry in config.chain_partitions:
            chain_partition = chain_entry.split(":")[0]
            if chain_partition not in all_partition_names:
                issues.append(
                    OperationIssue(
                        "config.missing_chain_partition",
                        f"Partition {name!r} chains to {chain_partition!r}, "
                        f"which is not in the profile",
                    )
                )

    # Topological sort (Kahn's algorithm)
    ordered = _topological_sort(adjacency, issues)
    return (tuple(ordered), tuple(issues))


def _topological_sort(
    adjacency: dict[str, set[str]],
    issues: list[OperationIssue],
) -> list[str]:
    """Kahn's algorithm with cycle detection."""
    # Compute in-degrees
    in_degree: dict[str, int] = {n: 0 for n in adjacency}
    for node, deps in adjacency.items():
        for _dep in deps:
            if _dep in in_degree:
                in_degree[node] = in_degree.get(node, 0)
    # Recount properly
    in_degree = {n: 0 for n in adjacency}
    for node in adjacency:
        for dep in adjacency[node]:
            if dep in in_degree:
                pass  # dep exists
    # Build reverse adjacency and in-degree
    in_degree = {n: 0 for n in adjacency}
    reverse: dict[str, list[str]] = {n: [] for n in adjacency}
    for node, deps in adjacency.items():
        for dep in deps:
            if dep in reverse:
                reverse[dep].append(node)
                in_degree[node] += 1

    # Start with nodes that have no dependencies
    queue: list[str] = sorted(n for n, d in in_degree.items() if d == 0)
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for dependent in sorted(reverse[node]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
        queue.sort()

    if len(result) != len(adjacency):
        remaining = sorted(set(adjacency) - set(result))
        issues.append(
            OperationIssue(
                "config.cycle_detected",
                f"Cycle detected among vbmeta partitions: {', '.join(remaining)}",
            )
        )

    return result
