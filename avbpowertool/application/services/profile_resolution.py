"""Profile-ID resolution for use cases that operate on the key store.

``ProfileRepository.resolve_profile_id`` is strict: it only accepts a
literal ID whose ``profile.json`` already exists.  The key-store use
cases are also driven by the TUI create wizard, which prepares
``profiles/<id>/keys`` *before* ``profile.json`` is written, so they
resolve through :func:`resolve_key_store_profile_id`.

That helper adds the ``current``/empty -> active-profile mapping on top
of the previous literal-ID behaviour: a non-empty request that cannot be
resolved is used as-is (the use case then reports its own
``keys.directory_not_found`` / ``chain.key_not_found`` issue), while an
empty request with no active profile reports ``config.no_active_profile``.
"""

from __future__ import annotations

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.profile_repository import (
    ProfileRepository,
)


def resolve_key_store_profile_id(
    workspace: WorkspacePaths, requested: str
) -> tuple[str, OperationIssue | None]:
    """Resolve *requested* to the profile that owns the key store.

    Returns ``(profile_id, issue)``; ``issue`` is not ``None`` when the
    request cannot be resolved and the caller must report it instead of
    touching the filesystem.

    A literal profile ID always wins; ``current``/empty resolves to the
    active profile; anything else is used literally so that a key store
    prepared before its ``profile.json`` exists (create wizard) keeps
    working.
    """
    literal = (requested or "").strip()
    repo = ProfileRepository(workspace)

    try:
        return repo.resolve_profile_id(literal), None
    except ConfigError as exc:
        if literal:
            return literal, None
        return literal, OperationIssue(exc.error_code, str(exc))
