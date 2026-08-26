"""Build a deterministic SigningPlan from configuration.

All side-effects happen in the *execution* of the plan, not during
construction.  The builder is a pure planner that checks for missing
images/keys and reports issues without raising.
"""

from __future__ import annotations

from pathlib import Path

from .command_builder import (
    build_hash_footer_command,
    build_hashtree_footer_command,
    build_vbmeta_command,
)
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

    def build(
        self,
        partition_names: tuple[str, ...],
        include_vbmeta_props: bool = True,
    ) -> SigningPlan:
        """Build a signing plan for the given partition names.

        Non-vbmeta images are signed first (alphabetical), then vbmeta
        images in dependency order.  ``include_vbmeta_props`` controls
        whether the config's props are emitted into generated vbmeta
        images (default True keeps builder-level behavior stable; the
        use case passes the user's choice).
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
            step, step_issues = self._build_vbmeta_step(
                name, config, order_counter, include_vbmeta_props
            )
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

        # Footer commands modify the staged copy in place (no --output).
        key = Path(key_path) if key_path is not None else None
        if config.descriptor == DescriptorType.HASH:
            cmd = build_hash_footer_command(Path(staging_output), config, key)
            operation = "add_hash_footer"
        elif config.descriptor == DescriptorType.HASHTREE:
            cmd = build_hashtree_footer_command(Path(staging_output), config, key)
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
        include_vbmeta_props: bool = True,
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

        # Include descriptors from other images (staging paths) plus any
        # extra images named in include_descriptors_from_image.
        include_descriptors: list[Path] = []
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
            include_descriptors.append(Path(str(self._staging_dir / included_config.image)))
        for extra_image in config.include_descriptors_from_image:
            resolved = self._resolve_image_path(extra_image)
            if resolved is None:
                issues.append(
                    OperationIssue(
                        "image.not_found",
                        f"Include-descriptor image not found: {extra_image}",
                    )
                )
                continue
            include_descriptors.append(Path(resolved))

        # Chain partitions (resolve public-key files relative to the key store)
        chain_partitions = tuple(
            self._resolve_chain_key(entry) for entry in config.chain_partitions
        )

        key = Path(key_path) if key_path is not None else None
        cmd = build_vbmeta_command(
            Path(staging_output),
            config,
            key,
            include_descriptors=tuple(include_descriptors),
            chain_partitions=chain_partitions,
            include_props=include_vbmeta_props,
        )

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
        # Normalize legacy Windows absolute entries before constructing the
        # avbtool triple; drive-letter ':' is invalid inside the third field.
        marker = "\\profiles\\"
        if marker.lower() in key_file.lower():
            key_file = "profiles/" + key_file.lower().split(marker.lower(), 1)[1].replace("\\", "/")
            return f"{name}:{location}:{key_file}"
        if not key_path.is_absolute():
            # Keep the chain field colon-free and portable on Windows.
            try:
                root = self._key_dir.parents[2].resolve()
                key_file = (self._key_dir / key_file).resolve().relative_to(root).as_posix()
            except ValueError:
                key_file = key_path.name
        else:
            # avbtool parses chain entries by ':'; Windows drive letters would
            # introduce a fourth field. Use a workspace-relative path instead.
            root = self._key_dir.parents[2].resolve()
            full = key_path.resolve()
            try:
                key_file = full.relative_to(root).as_posix()
            except ValueError:
                # Keep the third field colon-free even for external keys.
                key_file = key_path.name
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
