"""Tests for vbmeta dependency graph ordering."""

from __future__ import annotations

from avbpowertool.domain.dependency_graph import resolve_vbmeta_order
from avbpowertool.domain.models import DescriptorType, PartitionConfig, SigningAlgorithm


def _make_vbmeta(
    partition_name: str,
    included: tuple[str, ...] = (),
    chains: tuple[str, ...] = (),
) -> PartitionConfig:
    return PartitionConfig(
        image=f"{partition_name}.img",
        descriptor=DescriptorType.VBMETA,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="testkey",
        partition_name=partition_name,
        included_partitions=included,
        chain_partitions=chains,
    )


def _make_hash(partition_name: str) -> PartitionConfig:
    return PartitionConfig(
        image=f"{partition_name}.img",
        descriptor=DescriptorType.HASH,
        algorithm=SigningAlgorithm.SHA256_RSA4096,
        key_id="testkey",
        partition_name=partition_name,
    )


class TestResolveVbmetaOrder:
    def test_no_vbmeta(self) -> None:
        partitions = {
            "boot": _make_hash("boot"),
            "system": _make_hash("system"),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert order == ()
        assert len(issues) == 0

    def test_single_vbmeta(self) -> None:
        partitions = {
            "boot": _make_hash("boot"),
            "vbmeta": _make_vbmeta("vbmeta", included=("boot",)),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert order == ("vbmeta",)
        assert len(issues) == 0

    def test_two_independent_vbmeta(self) -> None:
        partitions = {
            "boot": _make_hash("boot"),
            "system": _make_hash("system"),
            "vbmeta": _make_vbmeta("vbmeta", included=("boot",)),
            "vbmeta_system": _make_vbmeta("vbmeta_system", included=("system",)),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert len(order) == 2
        assert set(order) == {"vbmeta", "vbmeta_system"}
        assert len(issues) == 0

    def test_chain_dependency_order(self) -> None:
        """vbmeta depends on vbmeta_system via chain -> vbmeta_system must come first."""
        partitions = {
            "system": _make_hash("system"),
            "vbmeta": _make_vbmeta(
                "vbmeta",
                chains=("vbmeta_system:1:system_key.pem",),
            ),
            "vbmeta_system": _make_vbmeta("vbmeta_system", included=("system",)),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert len(order) == 2
        # vbmeta depends on vbmeta_system, so vbmeta_system must be before vbmeta
        assert order.index("vbmeta_system") < order.index("vbmeta")
        assert len(issues) == 0

    def test_chain_via_included_partition(self) -> None:
        """vbmeta includes vbmeta_system as descriptor -> dependency."""
        partitions = {
            "boot": _make_hash("boot"),
            "system": _make_hash("system"),
            "vbmeta": _make_vbmeta("vbmeta", included=("boot", "vbmeta_system")),
            "vbmeta_system": _make_vbmeta("vbmeta_system", included=("system",)),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert len(order) == 2
        assert order.index("vbmeta_system") < order.index("vbmeta")
        assert len(issues) == 0

    def test_cycle_detected(self) -> None:
        partitions = {
            "vbmeta_a": _make_vbmeta(
                "vbmeta_a",
                chains=("vbmeta_b:1:key.pem",),
            ),
            "vbmeta_b": _make_vbmeta(
                "vbmeta_b",
                chains=("vbmeta_a:1:key.pem",),
            ),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert any(i.error_code == "config.cycle_detected" for i in issues)

    def test_missing_included_partition(self) -> None:
        partitions = {
            "vbmeta": _make_vbmeta("vbmeta", included=("nonexistent",)),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert any(i.error_code == "config.missing_included_partition" for i in issues)

    def test_missing_chain_partition(self) -> None:
        partitions = {
            "vbmeta": _make_vbmeta(
                "vbmeta",
                chains=("nonexistent:1:key.pem",),
            ),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert any(i.error_code == "config.missing_chain_partition" for i in issues)

    def test_three_level_chain(self) -> None:
        """vbmeta -> vbmeta_system -> (independent)."""
        partitions = {
            "system": _make_hash("system"),
            "vendor": _make_hash("vendor"),
            "vbmeta": _make_vbmeta(
                "vbmeta",
                chains=("vbmeta_system:1:sys.pem",),
            ),
            "vbmeta_system": _make_vbmeta("vbmeta_system", included=("system",)),
            "vbmeta_vendor": _make_vbmeta("vbmeta_vendor", included=("vendor",)),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert len(order) == 3
        # vbmeta must be after vbmeta_system
        assert order.index("vbmeta_system") < order.index("vbmeta")
        # vbmeta_vendor is independent, can be anywhere
        assert "vbmeta_vendor" in order

    def test_mixed_vbmeta_and_non_vbmeta(self) -> None:
        """Non-vbmeta partitions are excluded from vbmeta ordering."""
        partitions = {
            "boot": _make_hash("boot"),
            "system": _make_hash("system"),
            "vbmeta": _make_vbmeta("vbmeta", included=("boot", "system")),
        }
        order, issues = resolve_vbmeta_order(partitions)
        assert order == ("vbmeta",)
        assert "boot" not in order
        assert "system" not in order
