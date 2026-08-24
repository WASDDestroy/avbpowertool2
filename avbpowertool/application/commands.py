"""Request/result dataclasses for application use cases.

All request/result types are frozen dataclasses for immutability.
"""

from __future__ import annotations

from dataclasses import dataclass

from avbpowertool.domain.models import (
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


@dataclass(frozen=True)
class InspectImagesResult:
    """Result of an inspect-images operation."""

    images: tuple[ImageInspection, ...]
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
# Config Create
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigCreateRequest:
    """Request to create a new profile."""

    profile_id: str
    profile_name: str
    partitions: tuple[PartitionConfig, ...] = ()
    activate: bool = True


@dataclass(frozen=True)
class ConfigCreateResult:
    """Result of profile creation."""

    profile_id: str
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


# ---------------------------------------------------------------------------
# Key Management
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyDiscoveryRequest:
    """Request to discover and update key manifest."""

    profile_id: str = "current"


@dataclass(frozen=True)
class KeyDiscoveryResult:
    """Result of key discovery."""

    discovered_count: int
    manifest_entries: tuple[tuple[str, str], ...]  # (key_id, filename) pairs
    issues: tuple[OperationIssue, ...] = ()
