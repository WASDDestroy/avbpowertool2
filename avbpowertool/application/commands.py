"""Request/result dataclasses for application use cases.

All request/result types are frozen dataclasses for immutability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from avbpowertool.domain.models import (
    ChainDescriptor,
    ImageInspection,
    OperationIssue,
    PartitionConfig,
    SigningPlan,
)

# ---------------------------------------------------------------------------
# Inspect Images
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InspectImagesRequest:
    """Request to inspect AVB metadata for one or more images."""

    image_names: tuple[str, ...]
    profile_id: str = "current"
    with_cert: bool = False  # pass avbtool --cert / --atx


@dataclass(frozen=True)
class InspectImagesResult:
    """Result of an inspect-images operation."""

    images: tuple[ImageInspection, ...]
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Resolve chain keys
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolveChainKeysRequest:
    """Request to resolve chain descriptors to key files in the key store."""

    profile_id: str = "current"
    chains: tuple[ChainDescriptor, ...] = ()


@dataclass(frozen=True)
class ChainKeyResolution:
    """Resolution of one chain descriptor to a key-store entry.

    ``entry`` is the ``PART:SLOT:KEY_FILE`` triple with the key file
    relative to the profile's key store; empty when no key matched.
    """

    entry: str = ""
    key_id: str | None = None


@dataclass(frozen=True)
class ResolveChainKeysResult:
    """Result of chain-to-key resolution."""

    resolutions: tuple[ChainKeyResolution, ...] = ()
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Sign Images
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignImagesRequest:
    """Request to sign images."""

    image_names: tuple[str, ...]
    profile_id: str = "current"
    remove_existing_footers: bool = False
    dry_run: bool = True  # default to safe
    include_vbmeta_props: bool = False  # emit config props into generated vbmeta


@dataclass(frozen=True)
class SignImagesResult:
    """Result of a sign-images operation."""

    plan: SigningPlan
    executed: bool = False  # True if actual signing was attempted
    success_count: int = 0
    fail_count: int = 0
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Config Show / Validate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigShowRequest:
    """Request to show the currently active configuration."""

    profile_id: str = "current"


@dataclass(frozen=True)
class ConfigShowResult:
    """Result of showing configuration."""

    config_name: str
    partitions: tuple[PartitionConfig, ...]
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class ConfigValidateRequest:
    """Request to validate configuration against workspace."""

    profile_id: str = "current"


@dataclass(frozen=True)
class ConfigValidateResult:
    """Result of config validation."""

    config_name: str
    partitions: tuple[PartitionConfig, ...]
    missing_images: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Config Check Chains
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckChainsRequest:
    """Request to check every chain-partition entry of a profile."""

    profile_id: str = "current"


@dataclass(frozen=True)
class ChainCheckEntry:
    """Outcome of one ``PART:SLOT:KEYFILE`` chain entry.

    ``partition_name`` is the partition that *declares* the entry (the
    vbmeta one), while ``entry`` is the raw ``chain_partitions`` string.
    ``ok`` is False as soon as any check failed for that entry; the
    matching failures are in ``CheckChainsResult.issues``.
    """

    partition_name: str
    entry: str
    ok: bool = True


@dataclass(frozen=True)
class CheckChainsResult:
    """Result of checking a profile's chain partitions.

    ``checked`` counts every chain entry that was looked at, including the
    failing ones.  ``issues`` holds every failure (the use case never
    stops at the first one).  ``entries`` is the per-entry status used by
    the text renderer; the JSON contract only exposes ``profile_id`` /
    ``checked`` / ``issues``.
    """

    profile_id: str
    checked: int = 0
    issues: tuple[OperationIssue, ...] = ()
    entries: tuple[ChainCheckEntry, ...] = ()


# ---------------------------------------------------------------------------
# Config Create
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigCreateRequest:
    """Request to create a new profile.

    ``allow_empty`` permits creating a profile with zero partitions, which
    the strict domain validator reports as ``config.no_partitions``.  Only
    that one issue is suppressed; every other validation issue still
    applies.  It defaults to ``False`` so the creation wizard keeps its
    current behaviour.

    ``overwrite`` reuses an existing ``profiles/<id>/`` directory: its
    ``keys/`` content is kept while the partition set is replaced.  It
    defaults to ``False`` so every existing caller still reports
    ``config.profile_exists``.
    """

    profile_id: str
    profile_name: str
    partitions: tuple[PartitionConfig, ...] = ()
    activate: bool = True
    allow_empty: bool = False
    overwrite: bool = False


@dataclass(frozen=True)
class ConfigCreateResult:
    """Result of profile creation."""

    profile_id: str
    created: bool = False  # True when the profile directory was written
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Config Create From Images
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigCreateFromImagesRequest:
    """Request to create a profile from the AVB metadata of image files.

    ``image_dir`` is scanned for ``*.img`` files and defaults to the
    workspace ``Images/`` directory when it is ``None``.  ``image_names``
    holds bare image stems (no ``.img``); when non-empty every one of them
    must exist as ``<image_dir>/<name>.img`` and only those images are
    used.

    ``allow_fallback`` is off by default here: the vbmeta
    ``included_partitions`` stay pruned to the descriptors the image really
    embeds, whereas the TUI wizard passes ``True`` for its historical
    behaviour.  ``skip_non_avb`` downgrades an image without any AVB
    structure from a fatal ``image.no_vbmeta_structure`` to a reported
    skip.  ``overwrite`` reuses an existing ``profiles/<id>/`` directory
    (keeping its ``keys/``) instead of reporting ``config.profile_exists``.
    """

    profile_id: str
    profile_name: str = ""  # empty -> the profile id
    image_dir: Path | None = None  # None -> the workspace Images/ directory
    image_names: tuple[str, ...] = ()  # empty -> every *.img in the directory
    key_id: str | None = None  # explicit override of the automatic choice
    resolve_chains: bool = True
    allow_fallback: bool = False
    skip_non_avb: bool = False
    overwrite: bool = False
    activate: bool = False


@dataclass(frozen=True)
class ConfigCreateFromImagesResult:
    """Result of creating a profile from images.

    ``missing_keys`` is informational only: it lists the key ids the new
    profile references but its key store does not hold yet, and never
    influences ``created`` or the exit code (keys may be dropped in
    later).  ``chain_count`` is the total number of ``chain_partitions``
    entries written across all vbmeta partitions.

    ``chain_issues`` (e.g. ``chain.key_not_found`` for a vbmeta signed by
    a vendor key that is not in the store) is informational in exactly the
    same way: the chains can be hardcoded afterwards, so a failed chain
    resolution is reported here instead of in ``issues`` and never
    influences ``created`` or the exit code.
    """

    profile_id: str
    created: bool = False
    partition_count: int = 0
    chain_count: int = 0
    scanned_images: tuple[str, ...] = ()
    skipped_images: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()
    issues: tuple[OperationIssue, ...] = ()
    chain_issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Config Auto Create (from images)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigAutoCreateRequest:
    """Request to build partition configs from the images in a directory.

    ``image_dir`` is scanned for ``*.img`` files (sorted by name); when
    ``image_names`` is non-empty only those stems are inspected.  The
    ``key_id`` override wins over the automatic key selection, which
    otherwise picks from ``available_keys`` (defaulting to
    ``default_key_id``) based on the image's signing algorithm.
    """

    image_dir: Path
    image_names: tuple[str, ...] = ()
    key_id: str | None = None  # explicit override of the automatic choice
    available_keys: tuple[str, ...] = ()  # candidates for select_key_for_algorithm
    default_key_id: str = "default"
    profile_id: str = "current"  # used for chain-key resolution
    resolve_chains: bool = True
    allow_fallback: bool = True


@dataclass(frozen=True)
class ConfigAutoCreateResult:
    """Result of generating partition configs from images.

    ``issues`` carries the inspection issues (e.g. ``image.not_found`` /
    ``image.no_vbmeta_structure``); chain-resolution problems are kept
    separate in ``chain_issues`` so callers can render them in their own
    section, exactly as the create wizard does.
    """

    partitions: tuple[PartitionConfig, ...] = ()
    scanned_images: tuple[str, ...] = ()  # scanned image stems (sorted)
    skipped_images: tuple[str, ...] = ()  # descriptor is None -> skipped
    chain_issues: tuple[OperationIssue, ...] = ()
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Config Migrate / Edit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigMigrateRequest:
    """Request to migrate a profile to the current schema version."""

    profile_id: str = "current"


@dataclass(frozen=True)
class ConfigMigrateResult:
    """Result of a config migration."""

    profile_id: str
    migrated: bool = False  # True if the on-disk file was upgraded
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class ConfigEditRequest:
    """Request to update a single partition's config fields.

    ``updates`` maps PartitionConfig field names to string values and
    replaces the whole field (``--set``); only whitelisted scalar/tuple
    fields are accepted (see ``ConfigEditUseCase``).  ``unset`` names
    fields to reset to their empty value, while ``appends`` / ``removes``
    carry ordered ``(field, item)`` pairs for tuple fields (``--append`` /
    ``--remove``).
    """

    profile_id: str = "current"
    partition_name: str = ""
    updates: dict[str, str] = field(default_factory=dict[str, str])
    unset: tuple[str, ...] = ()
    appends: tuple[tuple[str, str], ...] = ()
    removes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ConfigEditResult:
    """Result of a config field update."""

    profile_id: str
    partition_name: str
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Config Import / Export
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigImportRequest:
    """Request to import a config archive."""

    archive_path: str
    new_profile_id: str | None = None


@dataclass(frozen=True)
class ConfigImportResult:
    """Result of config import."""

    profile_id: str
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class ConfigExportRequest:
    """Request to export a config as archive."""

    profile_id: str
    output_path: str | None = None


@dataclass(frozen=True)
class ConfigExportResult:
    """Result of config export."""

    output_path: str
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class LegacyImportRequest:
    """Request to import a legacy (v1) config archive with auto-conversion."""

    archive_path: str
    new_profile_id: str | None = None
    activate: bool = True


@dataclass(frozen=True)
class LegacyImportResult:
    """Result of a legacy (v1) config import."""

    profile_id: str
    partition_count: int = 0
    key_count: int = 0
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Profile Management
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileListRequest:
    """Request to list all profiles."""


@dataclass(frozen=True)
class ProfileListItem:
    """A single profile in the list."""

    profile_id: str
    name: str
    is_active: bool
    partition_count: int


@dataclass(frozen=True)
class ProfileListResult:
    """Result of listing profiles."""

    profiles: tuple[ProfileListItem, ...]
    active_profile_id: str | None = None
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class ProfileActivateRequest:
    """Request to activate a profile."""

    profile_id: str


@dataclass(frozen=True)
class ProfileActivateResult:
    """Result of activating a profile."""

    profile_id: str
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class ProfileDeleteRequest:
    """Request to delete a profile.

    ``force`` allows deleting the *active* profile: the directory is removed
    and ``.active-profile`` is cleared when it pointed at the deleted id.
    Without it, deleting the active profile is refused with
    ``config.active_delete_forbidden``.
    """

    profile_id: str
    force: bool = False


@dataclass(frozen=True)
class ProfileDeleteResult:
    """Result of deleting a profile.

    ``deleted`` is True only when the directory was really removed;
    ``deleted_files`` / ``deleted_bytes`` describe the regular files that
    were counted just before the removal.
    """

    profile_id: str
    issues: tuple[OperationIssue, ...] = ()
    deleted: bool = False
    deleted_files: int = 0
    deleted_bytes: int = 0


@dataclass(frozen=True)
class ProfileRenameRequest:
    """Request to rename a profile directory and/or its display name.

    ``profile_id`` is the current profile id (its directory name).
    ``new_profile_id`` must survive the public ``sanitize_profile_id``
    unchanged: a value that would be rewritten is rejected with
    ``config.invalid_profile_id`` instead of silently creating a profile
    under another id.  ``new_name`` only touches the display name and may
    be ``None`` to keep the current one.
    """

    profile_id: str
    new_profile_id: str
    new_name: str | None = None


@dataclass(frozen=True)
class ProfileRenameResult:
    """Result of renaming a profile.

    ``profile_id`` is the new id.  ``renamed`` is True only when the
    profile directory really changed name; ``name_changed`` is True when
    a new display name was written.  An empty ``issues`` tuple means the
    rename succeeded (which includes the "nothing to do" case where the
    id did not change and no display name was given).
    """

    old_profile_id: str
    profile_id: str
    renamed: bool = False
    name_changed: bool = False
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Key Management
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyDiscoveryRequest:
    """Request to discover and update key manifest.

    ``merge`` (the default) keeps the manifest entries that are already
    on disk: a discovered ``.pem`` only overwrites its own key_id, and
    the cached ``public_key`` / ``public_key_sha1`` survive as long as
    the entry still points at the same private-key filename.
    ``merge=False`` restores the historical replace semantics, where the
    manifest is rebuilt from the discovered ``.pem`` files alone.
    """

    profile_id: str = "current"
    merge: bool = True


@dataclass(frozen=True)
class KeyDiscoveryResult:
    """Result of key discovery."""

    discovered_count: int
    manifest_entries: tuple[tuple[str, str], ...]  # (key_id, filename) pairs
    issues: tuple[OperationIssue, ...] = ()
    # Statistics for the merge semantics; both default to 0 so the
    # create wizard (which only reads discovered_count /
    # manifest_entries / issues) is unaffected.
    retained_count: int = 0
    merged: bool = True


@dataclass(frozen=True)
class KeyListRequest:
    """Request to list keys in a profile's key store."""

    profile_id: str = "current"


@dataclass(frozen=True)
class KeyListResult:
    """Result of listing keys."""

    manifest_entries: tuple[tuple[str, str], ...]  # (key_id, filename)
    pem_files_on_disk: tuple[str, ...]  # filenames not in manifest
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class KeyAddRequest:
    """Request to add a key entry to the manifest."""

    profile_id: str = "current"
    key_id: str = ""
    private_key_filename: str = ""


@dataclass(frozen=True)
class KeyAddResult:
    """Result of adding a key entry."""

    key_id: str
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class KeyRemoveRequest:
    """Request to remove a key entry from the manifest."""

    profile_id: str = "current"
    key_id: str = ""


@dataclass(frozen=True)
class KeyRemoveResult:
    """Result of removing a key entry."""

    key_id: str
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class KeyEnsurePublicRequest:
    """Request to extract missing public keys for a profile's key store."""

    profile_id: str = "current"


@dataclass(frozen=True)
class KeyEnsurePublicResult:
    """Result of ensuring public keys exist.

    ``extracted`` holds ``(key_id, public_key_filename)`` pairs for the
    public-key files that were produced (or newly registered in the
    manifest) by this call.  ``skipped`` lists the manifest entries whose
    private-key file is missing on disk.
    """

    extracted: tuple[tuple[str, str], ...] = ()
    skipped: tuple[str, ...] = ()
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Plugin Management
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PluginListItem:
    """A single installed plugin.

    ``name`` is already resolved for the language injected into the use
    case, so the presentation layer never needs to look at the manifest
    itself.  ``version`` / ``version_name`` are the manifest's declared
    version (``0`` / ``""`` for a plugin that declares none).
    """

    plugin_id: str = ""
    name: str = ""
    entry: str = ""
    version: int = 0
    version_name: str = ""
    path: str = ""


@dataclass(frozen=True)
class PluginListRequest:
    """Request to list the plugins installed under ``plugins/``."""


@dataclass(frozen=True)
class PluginListResult:
    """Result of listing plugins.

    ``issues`` reports the directories that hold a manifest which could
    not be parsed: they are *not* silently dropped from the report.
    """

    plugins: tuple[PluginListItem, ...] = ()
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class PluginInstallRequest:
    """Request to install a plugin from a directory or a zip archive."""

    source_path: str = ""
    force: bool = False


@dataclass(frozen=True)
class PluginInstallResult:
    """Result of installing a plugin.

    ``plugin_id`` is the id declared by the installed manifest;
    ``file_count`` counts the regular files that ended up in
    ``plugins/<plugin_id>/``.  ``version`` / ``version_name`` describe what
    was installed and keep their defaults when nothing was installed.
    """

    plugin_id: str = ""
    installed: bool = False
    file_count: int = 0
    version: int = 0
    version_name: str = ""
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class PluginPackRequest:
    """Request to pack a plugin directory into an installable zip.

    ``source`` is either a plugin directory path or the id of an installed
    plugin (resolved against ``plugins/``).  ``output_path`` is the zip to
    write; ``None`` means ``<workspace root>/<plugin_id>.zip``.
    """

    source: str = ""
    output_path: str | None = None


@dataclass(frozen=True)
class PluginPackResult:
    """Result of packing a plugin.

    ``plugin_id`` is the id declared by the manifest and is also the single
    top-level directory inside the archive, so the produced zip installs
    as-is.  ``file_count`` counts the members written (noise files such as
    ``__pycache__/``, ``.git/`` and ``*.pyc`` are not packed and not
    counted).  ``includes_key_material`` is ``True`` when the source holds a
    ``keys/`` directory or any ``.pem`` file — the zip carries those too,
    which a script may want to warn about.
    """

    plugin_id: str = ""
    output_path: str = ""
    file_count: int = 0
    version: int = 0
    version_name: str = ""
    includes_key_material: bool = False
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class PluginUninstallRequest:
    """Request to remove an installed plugin."""

    plugin_id: str = ""


@dataclass(frozen=True)
class PluginUninstallResult:
    """Result of removing a plugin.

    ``removed_files`` / ``removed_bytes`` describe the regular files that
    were counted just before the directory was removed.
    """

    plugin_id: str = ""
    removed: bool = False
    removed_files: int = 0
    removed_bytes: int = 0
    issues: tuple[OperationIssue, ...] = ()


@dataclass(frozen=True)
class PluginRunRequest:
    """Request to run an installed plugin's entry script."""

    plugin_id: str = ""
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginRunResult:
    """Result of running a plugin.

    A non-zero ``exit_code`` is *not* an error: the plugin ran and chose
    that status, and the CLI returns it to its caller as-is.  ``exit_code``
    is ``-1`` only when the plugin never started, which always comes with
    a ``plugin.run_failed`` (or ``plugin.not_found`` /
    ``plugin.entry_not_found``) issue in ``issues``.
    """

    plugin_id: str = ""
    exit_code: int = 0
    issues: tuple[OperationIssue, ...] = ()
