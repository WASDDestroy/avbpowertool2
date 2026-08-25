"""Domain models for AVB Power Tool.

All models are immutable frozen dataclasses. They carry no presentation
or filesystem logic.

Python 3.11+ required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DescriptorType(Enum):
    """AVB descriptor type."""

    HASH = "hash"
    HASHTREE = "hashtree"
    VBMETA = "vbmeta"

    @classmethod
    def from_avbtool_label(cls, label: str) -> DescriptorType:
        """Map an avbtool descriptor header line to a DescriptorType."""
        lower = label.lower()
        if "hashtree" in lower:
            return cls.HASHTREE
        if "hash" in lower:
            return cls.HASH
        if "chain partition" in lower or "vbmeta" in lower:
            return cls.VBMETA
        raise ValueError(f"Unknown descriptor label: {label!r}")


class SigningAlgorithm(Enum):
    """Supported AVB signing algorithms."""

    NONE = "NONE"
    SHA256_RSA2048 = "SHA256_RSA2048"
    SHA256_RSA4096 = "SHA256_RSA4096"
    SHA256_RSA8192 = "SHA256_RSA8192"
    SHA512_RSA2048 = "SHA512_RSA2048"
    SHA512_RSA4096 = "SHA512_RSA4096"
    SHA512_RSA8192 = "SHA512_RSA8192"

    @classmethod
    def from_str(cls, value: str) -> SigningAlgorithm:
        """Parse algorithm string. Raises ValueError for unknown values."""
        for member in cls:
            if member.value == value.upper():
                return member
        raise ValueError(f"Unknown signing algorithm: {value!r}")


# ---------------------------------------------------------------------------
# Config models (v2 schema)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyRef:
    """Reference to a key within a profile's key store."""

    key_id: str
    private_key_filename: str
    public_key_filename: str | None = None
    public_key_sha1: str | None = None


@dataclass(frozen=True)
class PartitionConfig:
    """AVB signing configuration for a single partition (v3 schema).

    Field set mirrors the full avbtool argument surface for the
    ``add_hash_footer`` / ``add_hashtree_footer`` / ``make_vbmeta_image``
    commands (see ``infrastructure/avbtool/command_spec.py``).  ``key_id``
    may be empty for unsigned (``NONE``) partitions.
    """

    image: str
    descriptor: DescriptorType
    algorithm: SigningAlgorithm
    key_id: str
    partition_name: str
    # partition size (hash: required — either partition_size or
    # dynamic_partition_size must be non-zero/false, mirroring avbtool)
    partition_size: int = 0
    dynamic_partition_size: bool = False
    # rollback / digest
    rollback_index: int = 0
    rollback_index_location: int = 0
    salt: str = ""  # hex; empty -> avbtool generates a random salt
    hash_algorithm: str = "sha256"
    # descriptor properties
    props: tuple[tuple[str, str], ...] = ()
    prop_from_file: tuple[tuple[str, str], ...] = ()
    flags: int = 0
    set_hashtree_disabled_flag: bool = False
    set_verification_disabled_flag: bool = False
    # hashtree-specific
    block_size: int = 4096  # add_hashtree_footer --block_size
    do_not_generate_fec: bool = False
    fec_num_roots: int = 2
    no_hashtree: bool = False
    check_at_most_once: bool = False
    setup_as_rootfs_from_kernel: bool = False
    # vbmeta / footer common
    included_partitions: tuple[str, ...] = ()
    include_descriptors_from_image: tuple[str, ...] = ()
    chain_partitions: tuple[str, ...] = ()
    chain_partitions_do_not_use_ab: tuple[str, ...] = ()
    kernel_cmdlines: tuple[str, ...] = ()
    setup_rootfs_from_kernel: str = ""
    padding_size: int = 0  # make_vbmeta_image --padding_size
    output_vbmeta_image: str = ""
    # behavior switches
    calc_max_image_size: bool = False
    do_not_append_vbmeta_image: bool = False
    print_required_libavb_version: bool = False
    use_persistent_digest: bool = False
    do_not_use_ab: bool = False
    # signing helper
    signing_helper: str = ""
    signing_helper_with_files: str = ""
    public_key_metadata: str = ""
    append_to_release_string: str = ""


@dataclass(frozen=True)
class AvbProfile:
    """A complete AVB signing profile (v3 schema)."""

    id: str
    name: str
    schema_version: int = 3
    key_store_path: str = "keys"
    partitions: dict[str, PartitionConfig] = field(default_factory=lambda: {})


# ---------------------------------------------------------------------------
# Execution models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperationIssue:
    """A single issue (warning or error) from an operation."""

    error_code: str
    message: str


@dataclass(frozen=True)
class SigningStep:
    """A single step in a signing plan."""

    partition_name: str
    operation: str
    command: tuple[str, ...]
    input_path: str
    output_path: str
    order: int


@dataclass(frozen=True)
class SigningPlan:
    """Immutable, validated execution plan for batch signing."""

    profile_id: str
    steps: tuple[SigningStep, ...]
    vbmeta_order: tuple[str, ...]
    issues: tuple[OperationIssue, ...] = ()


# ---------------------------------------------------------------------------
# Inspection models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageInspection:
    """Parsed AVB metadata for a single image."""

    image_name: str
    image_path: str
    descriptor: DescriptorType | None = None
    algorithm: str | None = None
    partition_name: str | None = None
    public_key_sha1: str | None = None
    rollback_index: str | None = None
    rollback_index_location: str | None = None
    salt: str | None = None
    hash_algorithm: str | None = None
    digest: str | None = None
    flags: str | None = None
    props: tuple[tuple[str, str], ...] = ()
    raw_extensions: tuple[tuple[str, str], ...] = ()
