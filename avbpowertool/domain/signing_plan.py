"""Build a deterministic SigningPlan from configuration.

All side-effects happen in the *execution* of the plan, not during
construction.  The builder is a pure planner that checks for missing
images/keys and reports issues without raising.
"""

from __future__ import annotations

from pathlib import Path

from .dependency_graph import resolve_vbmeta_order
from .models import (
    AvbProfile,
    DescriptorType,
    OperationIssue,
    PartitionConfig,
    SigningAlgorithm,
    SigningPlan,
    SigningStep,
)


class SigningPlanBuilder:
    """Build a signing plan from a profile.

    Catches missing-path, key, and config errors into
    OperationIssue instead of raising.
    """

    def __init__(
        self,
        profile: AvbProfile,
        image_dir: Path,
        key_dir: Path,
        staging_dir: Path,
    ) -> None:
        self._profile = profile
        self._image_dir = image_dir
        self._key_dir = key_dir
        self._staging_dir = staging_dir

    def build(self, partition_names: tuple[str, ...]) -> SigningPlan:
        """Build a signing plan for the given partition names.

        Non-vbmeta images are signed first (alphabetical), then vbmeta
        images in dependency order.
        """
        issues: list[OperationIssue] = []

        # Validate requested partitions exist in profile
        available = set(self._profile.partitions.keys())
        requested = set(partition_names)
        missing = requested - available
        for name in sorted(missing):
            issues.append(
                OperationIssue(
                    "config.partition_missing",
                    f"Partition not in profile: {name}",
                )
            )

        # Separate into non-vbmeta and vbmeta
        non_vbmeta_names: list[str] = []
        vbmeta_names: list[str] = []

        for name in sorted(partition_names):
            if name in missing:
                continue
            config = self._profile.partitions[name]
            if config.descriptor == DescriptorType.VBMETA:
                vbmeta_names.append(name)
            else:
                non_vbmeta_names.append(name)

        # Resolve vbmeta ordering
        vbmeta_order: tuple[str, ...] = ()
        if vbmeta_names:
            full_vbmeta_order, graph_issues = resolve_vbmeta_order(self._profile.partitions)
            issues.extend(graph_issues)
            # Filter to only requested vbmeta names, preserving order
            vbmeta_order = tuple(n for n in full_vbmeta_order if n in set(vbmeta_names))

        # Build steps
        steps: list[SigningStep] = []
        order_counter = 0

        # Pass 1: non-vbmeta images (alphabetical)
        for name in non_vbmeta_names:
            config = self._profile.partitions[name]
            step, step_issues = self._build_non_vbmeta_step(name, config, order_counter)
            issues.extend(step_issues)
            if step is not None:
                steps.append(step)
                order_counter += 1

        # Pass 2: vbmeta images (dependency order)
        for name in vbmeta_order:
            config = self._profile.partitions[name]
            step, step_issues = self._build_vbmeta_step(name, config, order_counter)
            issues.extend(step_issues)
            if step is not None:
                steps.append(step)
                order_counter += 1

        return SigningPlan(
            profile_id=self._profile.id,
            steps=tuple(steps),
            vbmeta_order=vbmeta_order,
            issues=tuple(issues),
        )

    # ------------------------------------------------------------------
    # Step builders
    # ------------------------------------------------------------------

    def _build_non_vbmeta_step(
        self,
        name: str,
        config: PartitionConfig,
        order: int,
    ) -> tuple[SigningStep | None, list[OperationIssue]]:
        """Build a signing step for a hash or hashtree partition."""
        issues: list[OperationIssue] = []

        # Resolve image path
        image_path = self._resolve_image_path(config.image)
        if image_path is None:
            issues.append(OperationIssue("image.not_found", f"Image not found: {config.image}"))
            return None, issues

        # Resolve key path (unsigned NONE partitions need no key)
        key_path: str | None
        if config.algorithm == SigningAlgorithm.NONE:
            key_path = None
        else:
            key_path, key_issues = self._resolve_key_path(config.key_id)
            issues.extend(key_issues)
            if key_path is None:
                return None, issues

        staging_output = str(self._staging_dir / config.image)

        if config.descriptor == DescriptorType.HASH:
            cmd = self._build_hash_command(str(image_path), staging_output, config, key_path)
            operation = "add_hash_footer"
        elif config.descriptor == DescriptorType.HASHTREE:
            cmd = self._build_hashtree_command(str(image_path), staging_output, config, key_path)
            operation = "add_hashtree_footer"
        else:
            issues.append(
                OperationIssue(
                    "config.unsupported_descriptor",
                    f"Unsupported descriptor for {name}: {config.descriptor.value}",
                )
            )
            return None, issues

        return (
            SigningStep(
                partition_name=name,
                operation=operation,
                command=tuple(cmd),
                input_path=str(image_path),
                output_path=staging_output,
                order=order,
            ),
            issues,
        )

    def _build_vbmeta_step(
        self,
        name: str,
        config: PartitionConfig,
        order: int,
    ) -> tuple[SigningStep | None, list[OperationIssue]]:
        """Build a signing step for a vbmeta partition."""
        issues: list[OperationIssue] = []

        # Resolve key path (unsigned NONE vbmeta needs no key)
        key_path: str | None
        if config.algorithm == SigningAlgorithm.NONE:
            key_path = None
        else:
            key_path, key_issues = self._resolve_key_path(config.key_id)
            issues.extend(key_issues)
            if key_path is None:
                return None, issues

        staging_output = str(self._staging_dir / config.image)

        cmd: list[str] = [
            "make_vbmeta_image",
            "--output",
            staging_output,
            "--rollback_index",
            str(config.rollback_index),
            "--rollback_index_location",
            str(config.rollback_index_location),
        ]
        if key_path is not None:
            cmd.extend(["--algorithm", config.algorithm.value, "--key", key_path])
        if config.flags:
            cmd.extend(["--flags", str(config.flags)])
        if config.set_hashtree_disabled_flag:
            cmd.append("--set_hashtree_disabled_flag")
        if config.set_verification_disabled_flag:
            cmd.append("--set_verification_disabled_flag")
        if config.kernel_cmdline:
            cmd.extend(["--kernel_cmdline", config.kernel_cmdline])

        # Include descriptors from other images (staging paths)
        for included_name in config.included_partitions:
            included_config = self._profile.partitions.get(included_name)
            if included_config is None:
                issues.append(
                    OperationIssue(
                        "config.missing_included_partition",
                        f"Included partition {included_name!r} not in profile",
                    )
                )
                continue
            desc_path = str(self._staging_dir / included_config.image)
            cmd.extend(["--include_descriptors_from_image", desc_path])

        # Chain partitions (resolve public-key files relative to the key store)
        for chain_entry in config.chain_partitions:
            cmd.extend(["--chain_partition", self._resolve_chain_key(chain_entry)])

        # Properties
        for k, v in config.props:
            cmd.extend(["--prop", f"{k}:{v}"])

        return (
            SigningStep(
                partition_name=name,
                operation="make_vbmeta_image",
                command=tuple(cmd),
                input_path="(generated)",
                output_path=staging_output,
                order=order,
            ),
            issues,
        )

    # ------------------------------------------------------------------
    # Command builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_hash_command(
        image_path: str,
        output_path: str,
        config: PartitionConfig,
        key_path: str | None,
    ) -> list[str]:
        cmd = [
            "add_hash_footer",
            "--image",
            image_path,
            "--output",
            output_path,
            "--partition_name",
            config.partition_name,
            "--salt",
            config.salt,
            "--rollback_index",
            str(config.rollback_index),
            "--rollback_index_location",
            str(config.rollback_index_location),
            "--hash_algorithm",
            config.hash_algorithm,
        ]
        if key_path is not None:
            cmd.extend(["--algorithm", config.algorithm.value, "--key", key_path])
        if config.flags:
            cmd.extend(["--flags", str(config.flags)])
        if config.set_hashtree_disabled_flag:
            cmd.append("--set_hashtree_disabled_flag")
        if config.set_verification_disabled_flag:
            cmd.append("--set_verification_disabled_flag")
        for k, v in config.props:
            cmd.extend(["--prop", f"{k}:{v}"])
        return cmd

    @staticmethod
    def _build_hashtree_command(
        image_path: str,
        output_path: str,
        config: PartitionConfig,
        key_path: str | None,
    ) -> list[str]:
        cmd = [
            "add_hashtree_footer",
            "--image",
            image_path,
            "--output",
            output_path,
            "--partition_name",
            config.partition_name,
            "--salt",
            config.salt,
            "--rollback_index",
            str(config.rollback_index),
            "--rollback_index_location",
            str(config.rollback_index_location),
            "--data_block_size",
            str(config.data_block_size),
            "--hash_block_size",
            str(config.hash_block_size),
        ]
        if key_path is not None:
            cmd.extend(["--algorithm", config.algorithm.value, "--key", key_path])
        if config.flags:
            cmd.extend(["--flags", str(config.flags)])
        if config.set_hashtree_disabled_flag:
            cmd.append("--set_hashtree_disabled_flag")
        if config.set_verification_disabled_flag:
            cmd.append("--set_verification_disabled_flag")
        for k, v in config.props:
            cmd.extend(["--prop", f"{k}:{v}"])
        return cmd

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_chain_key(self, chain_entry: str) -> str:
        """Resolve the public-key segment of a chain entry relative to the key store.

        Chain format: ``partition_name:rollback_index_location:public_key_file``.
        If the public-key file is not absolute, resolve it against ``self._key_dir``
        so v1-converted entries like ``boot:3:testkey_rsa4096_pub.bin`` work.
        """
        parts = chain_entry.split(":")
        if len(parts) < 3:
            return chain_entry
        name = parts[0]
        location = parts[1]
        key_file = ":".join(parts[2:])  # key file itself may contain ':' (Windows drive)
        key_path = Path(key_file)
        if not key_path.is_absolute():
            key_file = str(self._key_dir / key_file)
        return f"{name}:{location}:{key_file}"

    def _resolve_image_path(self, image_file: str) -> str | None:
        """Resolve image file path. Returns None if not found."""
        path = self._image_dir / image_file
        if path.exists():
            return str(path)
        # Try appending .img
        if not image_file.endswith(".img"):
            path_with_ext = self._image_dir / (image_file + ".img")
            if path_with_ext.exists():
                return str(path_with_ext)
        return None

    def _resolve_key_path(self, key_id: str) -> tuple[str | None, list[OperationIssue]]:
        """Resolve key file path from key_id via manifest.json."""
        issues: list[OperationIssue] = []
        manifest_path = self._key_dir / "manifest.json"

        if not manifest_path.exists():
            issues.append(
                OperationIssue(
                    "keys.manifest_not_found",
                    f"Key manifest not found: {manifest_path}",
                )
            )
            return None, issues

        try:
            import json

            with open(manifest_path, encoding="utf-8") as f:
                manifest: dict[str, dict[str, str]] = json.load(f)
        except (OSError, ValueError) as exc:
            issues.append(
                OperationIssue("keys.manifest_read_error", f"Failed to read manifest: {exc}")
            )
            return None, issues

        entry = manifest.get(key_id)
        if entry is None:
            issues.append(
                OperationIssue(
                    "config.key_missing",
                    f"Key {key_id!r} not found in manifest",
                )
            )
            return None, issues

        private_key = entry.get("private_key")
        if not private_key:
            issues.append(
                OperationIssue(
                    "config.key_missing",
                    f"Key {key_id!r}: no private_key in manifest entry",
                )
            )
            return None, issues

        key_path = self._key_dir / private_key
        if not key_path.exists():
            issues.append(
                OperationIssue(
                    "config.key_missing",
                    f"Key file not found: {key_path}",
                )
            )
            return None, issues

        return str(key_path), issues
