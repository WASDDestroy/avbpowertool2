"""Plugin repository — read/install/uninstall plugin packages on disk.

A plugin is a directory under ``plugins/`` that holds a manifest named
``avbpowertool_plugin_config.xml``.  The repository only knows about that
directory (like :class:`ProfileRepository` only knows about ``profiles/``),
so it stays independent of the whole workspace.

There is no security check anywhere here — no signature, no permission
model.  What *is* enforced is correctness: an archive member can never
escape the target directory, an id is always a single plain directory
name, and an entry is always a bare file name inside the plugin.
"""

from __future__ import annotations

import logging
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import OperationIssue
from avbpowertool.domain.plugin import PluginManifest
from avbpowertool.domain.validation import validate_plugin_manifest

logger = logging.getLogger(__name__)

#: Manifest file name expected inside every plugin directory / archive.
PLUGIN_MANIFEST_NAME = "avbpowertool_plugin_config.xml"

#: Root element of a plugin manifest.
_PLUGIN_ROOT_TAG = "avbpowertool_plugin"

#: A member like ``C:evil`` (drive) or ``name:stream`` (NTFS ADS).
_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")

#: Directory names that are development noise, not plugin content.
_PACK_NOISE_DIRECTORIES = frozenset({"__pycache__", ".git"})

#: File suffixes that are development noise, not plugin content.
_PACK_NOISE_SUFFIXES = (".pyc",)


# ---------------------------------------------------------------------------
# Manifest parsing (pure)
# ---------------------------------------------------------------------------


def parse_plugin_manifest(xml_bytes: bytes) -> tuple[PluginManifest, list[OperationIssue]]:
    """Parse plugin manifest XML into a manifest plus validation issues.

    Never raises: malformed XML is reported as a ``plugin.manifest_invalid``
    issue next to an empty manifest, and a well-formed manifest is handed to
    :func:`validate_plugin_manifest` whose issues are returned too.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        return _empty_manifest(), [
            OperationIssue("plugin.manifest_invalid", f"Malformed plugin manifest XML: {exc}")
        ]

    if root.tag != _PLUGIN_ROOT_TAG:
        return _empty_manifest(), [
            OperationIssue(
                "plugin.manifest_invalid",
                f"Unexpected plugin manifest root element: {root.tag!r}",
            )
        ]

    names_container = root.find("names")
    manifest = PluginManifest(
        plugin_id=(root.findtext("id") or "").strip(),
        entry=(root.findtext("entry") or "").strip(),
        version=_parse_version(root),
        version_name=(root.findtext("version_name") or "").strip(),
        names=_localized_pairs(names_container, "name"),
        descriptions=_localized_pairs(root, "description"),
        schema_version=_parse_schema_version(root),
    )
    return manifest, validate_plugin_manifest(manifest)


def _empty_manifest() -> PluginManifest:
    """A placeholder for XML that could not be understood at all."""
    return PluginManifest(plugin_id="", entry="")


def _parse_version(root: ET.Element) -> int:
    """Read ``<version>``; a missing element means version ``0``.

    A present but non-numeric value is returned as ``-1`` so that
    :func:`validate_plugin_manifest` reports it as
    ``plugin.manifest_invalid`` — exactly like an explicit negative value.
    """
    raw = root.findtext("version")
    if raw is None:
        return 0
    try:
        return int(raw.strip())
    except ValueError:
        return -1


def _parse_schema_version(root: ET.Element) -> int:
    """Read ``schema_version``; a missing attribute means the current schema."""
    raw = root.get("schema_version")
    if raw is None:
        return 1
    try:
        return int(raw.strip())
    except ValueError:
        # Not a number at all: report it through the schema_version check.
        return -1


def _localized_pairs(parent: ET.Element | None, item_tag: str) -> tuple[tuple[str, str], ...]:
    """Collect ``(lang, text)`` pairs from ``<parent><item lang=…>text``."""
    if parent is None:
        return ()
    return tuple(
        ((item.get("lang") or "").strip(), (item.text or "").strip())
        for item in parent.findall(item_tag)
    )


# ---------------------------------------------------------------------------
# Zip member safety
# ---------------------------------------------------------------------------


def _safe_member_parts(member_name: str) -> tuple[str, ...] | None:
    """Return the safe path components of a zip member, or ``None``.

    ``None`` means the member must be refused: it is absolute, carries a
    drive/stream separator, or contains a ``..`` component that would let
    it escape the extraction root.  Empty and ``.`` components are dropped
    so that ``a//b`` and ``a/./b`` cannot smuggle a leading separator past
    the checks below.
    """
    normalized = member_name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or _DRIVE_PATTERN.match(normalized):
        return None

    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == ".." or ":" in part:
            return None
        parts.append(part)
    return tuple(parts)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class PluginRepository:
    """Read, install, and remove plugin packages under ``plugins/``."""

    def __init__(self, plugins_dir: Path) -> None:
        self._plugins_dir = plugins_dir

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def list_manifests(self) -> tuple[tuple[PluginManifest, ...], list[OperationIssue]]:
        """Return every valid manifest plus the issues of the broken ones.

        A sub-directory without a manifest is simply not a plugin and is
        ignored; a sub-directory *with* a manifest that cannot be parsed
        is reported (never silently dropped) and left out of the result.
        """
        manifests: list[PluginManifest] = []
        issues: list[OperationIssue] = []

        if not self._plugins_dir.is_dir():
            return (), issues

        for child in sorted(self._plugins_dir.iterdir(), key=lambda entry: entry.name):
            if not child.is_dir():
                continue
            manifest_path = child / PLUGIN_MANIFEST_NAME
            if not manifest_path.is_file():
                continue

            try:
                xml_bytes = manifest_path.read_bytes()
            except OSError as exc:
                issues.append(
                    OperationIssue(
                        "plugin.manifest_invalid",
                        f"{manifest_path}: cannot be read: {exc}",
                    )
                )
                continue

            _manifest, manifest_issues = parse_plugin_manifest(xml_bytes)
            if manifest_issues:
                issues.extend(
                    OperationIssue(issue.error_code, f"{manifest_path}: {issue.message}")
                    for issue in manifest_issues
                )
                continue
            manifests.append(_manifest)

        return tuple(manifests), issues

    def load_manifest(self, plugin_id: str) -> PluginManifest:
        """Load the manifest of ``plugins/<plugin_id>/``.

        Raises:
            ConfigError: the plugin does not exist (``plugin.not_found``) or
                its manifest cannot be read/parsed (the manifest issue code).
        """
        manifest_path = self._plugins_dir / plugin_id / PLUGIN_MANIFEST_NAME
        if not manifest_path.is_file():
            raise ConfigError(
                f"Plugin not found: {plugin_id}",
                error_code="plugin.not_found",
            )
        return self._read_manifest(manifest_path)

    def read_manifest(self, plugin_dir: Path) -> PluginManifest:
        """Read the manifest of an arbitrary plugin directory.

        Unlike :meth:`load_manifest` this does not assume the directory sits
        under ``plugins/``, which is what ``plugin pack`` needs: a source is
        any plugin directory, installed or still in development.

        Raises:
            ConfigError: the manifest is missing (``plugin.manifest_missing``)
                or cannot be read/parsed/validated (its issue code).
        """
        return self._read_manifest(plugin_dir / PLUGIN_MANIFEST_NAME)

    # ------------------------------------------------------------------
    # Pack
    # ------------------------------------------------------------------

    def pack(self, plugin_dir: Path, output_path: Path) -> tuple[PluginManifest, int]:
        """Pack *plugin_dir* into an installable zip at *output_path*.

        The archive uses the "exactly one directory level" layout the
        installer understands (``<plugin_id>/<relative path>``), so the
        output of this method installs as-is.  Member names always use
        ``/`` separators; an absolute path or a ``..`` component can never
        be produced, and both are asserted before writing.

        Development noise is skipped at every level: ``__pycache__/``,
        ``.git/`` and ``*.pyc``.  Everything else is packed — including a
        plugin's own ``keys/`` directory, because a plugin may legitimately
        ship key material.  When *output_path* lives inside *plugin_dir*,
        the archive itself is left out so a repeated pack cannot swallow
        the previous one.

        Returns:
            ``(manifest, file_count)`` where *file_count* is the number of
            members written (the zip holds no explicit directory entries).

        Raises:
            ConfigError: ``plugin.not_found`` (no such directory), the
                manifest issue code, or ``plugin.pack_failed`` when the
                archive cannot be written.
        """
        if not plugin_dir.is_dir():
            raise ConfigError(
                f"Plugin directory not found: {plugin_dir}",
                error_code="plugin.not_found",
            )

        manifest = self.read_manifest(plugin_dir)
        members = _collect_pack_members(plugin_dir, manifest.plugin_id, output_path)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for source, arcname in members:
                    archive.write(source, arcname)
        except OSError as exc:
            # A half-written archive must not look like a usable package.
            _discard_partial_archive(output_path)
            raise ConfigError(
                f"Failed to pack plugin {manifest.plugin_id!r} into {output_path}: {exc}",
                error_code="plugin.pack_failed",
            ) from exc

        logger.info(
            "Packed plugin %r into %s (%d files)",
            manifest.plugin_id,
            output_path,
            len(members),
        )
        return manifest, len(members)

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def install(self, source: Path, force: bool) -> tuple[PluginManifest, int]:
        """Install the plugin package at *source*; returns manifest + file count.

        *source* is either a plugin directory or a zip holding the manifest
        at its root or under exactly one same-named directory (the layout
        ``Compress-Archive <dir>`` produces).

        An existing target is handled by version (see
        :meth:`_overwrite_allowed`): a newer or equal ``version`` overwrites
        without *force*, a lower one is refused, and an unreadable installed
        manifest falls back to the old "needs --force" rule.

        Raises:
            ConfigError: with ``plugin.manifest_missing``, a manifest issue
                code, ``plugin.downgrade``, ``plugin.exists``, or
                ``plugin.install_failed``.
        """
        if source.is_dir():
            manifest = self._read_manifest(source / PLUGIN_MANIFEST_NAME)
            return manifest, self._install_directory(source, manifest, force)

        if source.is_file() and _is_zipfile(source):
            manifest, prefix = self._read_zip_manifest(source)
            return manifest, self._install_zip(source, manifest, prefix, force)

        raise ConfigError(
            f"Not a plugin directory or zip archive: {source}",
            error_code="plugin.install_failed",
        )

    def _install_directory(self, source: Path, manifest: PluginManifest, force: bool) -> int:
        """Copy a plugin directory into ``plugins/<id>/``."""
        target = self._plugins_dir / manifest.plugin_id
        overwrite = self._overwrite_allowed(target, manifest, force)

        if _same_directory(source, target):
            # The plugin directory is its own install location: copying it
            # onto itself is a no-op, not an error.
            logger.info("Plugin %r is already installed in place", manifest.plugin_id)
            return _count_regular_files(target)[0]

        try:
            self._plugins_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, dirs_exist_ok=overwrite)
        except OSError as exc:
            raise ConfigError(
                f"Failed to install plugin {manifest.plugin_id!r}: {exc}",
                error_code="plugin.install_failed",
            ) from exc

        file_count = _count_regular_files(target)[0]
        logger.info(
            "Installed plugin %r from %s (%d files)", manifest.plugin_id, source, file_count
        )
        return file_count

    def _read_zip_manifest(self, source: Path) -> tuple[PluginManifest, tuple[str, ...]]:
        """Read the manifest inside a zip; returns it plus its directory prefix."""
        try:
            with zipfile.ZipFile(source) as archive:
                candidates: list[tuple[tuple[str, ...], zipfile.ZipInfo]] = []
                for info in archive.infolist():
                    parts = _safe_member_parts(info.filename)
                    if parts is None:
                        continue
                    if parts == (PLUGIN_MANIFEST_NAME,):
                        candidates.append(((), info))
                    elif len(parts) == 2 and parts[1] == PLUGIN_MANIFEST_NAME:
                        candidates.append(((parts[0],), info))

                if not candidates:
                    raise ConfigError(
                        f"Plugin archive holds no {PLUGIN_MANIFEST_NAME}: {source}",
                        error_code="plugin.manifest_missing",
                    )

                prefixes = {prefix for prefix, _info in candidates}
                if len(prefixes) > 1:
                    raise ConfigError(
                        f"Plugin archive holds more than one {PLUGIN_MANIFEST_NAME}: {source}",
                        error_code="plugin.manifest_invalid",
                    )

                prefix, info = candidates[0]
                xml_bytes = archive.read(info)
        except ConfigError:
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            raise ConfigError(
                f"Failed to read plugin archive {source}: {exc}",
                error_code="plugin.install_failed",
            ) from exc

        manifest, issues = parse_plugin_manifest(xml_bytes)
        if issues:
            raise ConfigError(f"{source}: {issues[0].message}", error_code=issues[0].error_code)
        return manifest, prefix

    def _install_zip(
        self,
        source: Path,
        manifest: PluginManifest,
        prefix: tuple[str, ...],
        force: bool,
    ) -> int:
        """Extract a zip into ``plugins/<id>/``, stripping the *prefix*."""
        target = self._plugins_dir / manifest.plugin_id
        self._overwrite_allowed(target, manifest, force)

        try:
            with zipfile.ZipFile(source) as archive:
                members = _select_zip_members(archive, prefix)
                self._plugins_dir.mkdir(parents=True, exist_ok=True)
                target.mkdir(parents=True, exist_ok=True)

                file_count = 0
                for info, relative in members:
                    destination = target.joinpath(*relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, open(destination, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    file_count += 1
        except (OSError, zipfile.BadZipFile) as exc:
            raise ConfigError(
                f"Failed to install plugin {manifest.plugin_id!r}: {exc}",
                error_code="plugin.install_failed",
            ) from exc

        logger.info(
            "Installed plugin %r from %s (%d files)", manifest.plugin_id, source, file_count
        )
        return file_count

    def _overwrite_allowed(self, target: Path, incoming: PluginManifest, force: bool) -> bool:
        """Decide what happens to an already existing *target* directory.

        Returns ``True`` when *target* exists and must be overwritten,
        ``False`` when there is nothing there yet (a plain install).

        The rule is driven by the manifest versions, because "already
        installed" is not an error any more — upgrading (and reinstalling
        the same version) is the normal path:

        ==============================  =====================================
        Situation                       Outcome
        ==============================  =====================================
        target missing                  install normally (``False``)
        ``force``                       overwrite, downgrade included
        incoming < installed            ``plugin.downgrade``, nothing written
        incoming >= installed           overwrite without ``force``
        installed manifest unreadable   ``plugin.exists`` without ``force``
        ==============================  =====================================

        ``plugin.exists`` is therefore only the fallback for a target whose
        version cannot be determined: a manifest that is missing, malformed,
        or belongs to a different id.
        """
        if not target.exists():
            return False
        if force:
            return True

        installed = self._read_installed_manifest(target, incoming.plugin_id)
        if installed is None:
            raise ConfigError(
                f"Plugin already installed: {incoming.plugin_id} "
                "(its manifest cannot be read, so the installed version is unknown; "
                "use --force to overwrite)",
                error_code="plugin.exists",
            )

        if incoming.version < installed.version:
            raise ConfigError(
                f"Refusing to downgrade plugin {incoming.plugin_id!r}: installed "
                f"{_describe_version(installed)} is newer than the incoming "
                f"{_describe_version(incoming)} (use --force to downgrade)",
                error_code="plugin.downgrade",
            )

        logger.info(
            "Upgrading plugin %r from %s to %s",
            incoming.plugin_id,
            _describe_version(installed),
            _describe_version(incoming),
        )
        return True

    def _read_installed_manifest(self, target: Path, plugin_id: str) -> PluginManifest | None:
        """Read the manifest already installed in *target*, or ``None``.

        ``None`` means "the installed version is unknown": the manifest is
        missing, cannot be read, does not parse/validate, or declares a
        different id than the directory it sits in.
        """
        manifest_path = target / PLUGIN_MANIFEST_NAME
        try:
            xml_bytes = manifest_path.read_bytes()
        except OSError:
            return None

        installed, issues = parse_plugin_manifest(xml_bytes)
        if issues or installed.plugin_id != plugin_id:
            return None
        return installed

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self, plugin_id: str) -> tuple[int, int]:
        """Remove ``plugins/<plugin_id>/``; returns ``(file_count, bytes)``.

        Raises:
            ConfigError: the id is not a plain directory name
                (``plugin.id_invalid``), the plugin does not exist
                (``plugin.not_found``), or the removal failed
                (``plugin.uninstall_failed``).
        """
        if not plugin_id or plugin_id in (".", "..") or "/" in plugin_id or "\\" in plugin_id:
            raise ConfigError(
                f"Invalid plugin id: {plugin_id!r} "
                "(must be a single directory name under plugins/)",
                error_code="plugin.id_invalid",
            )

        target = self._plugins_dir / plugin_id
        if target.resolve().parent != self._plugins_dir.resolve():
            raise ConfigError(
                f"Invalid plugin id: {plugin_id!r} "
                "(must be a single directory name under plugins/)",
                error_code="plugin.id_invalid",
            )

        if not target.is_dir():
            raise ConfigError(
                f"Plugin not found: {plugin_id}",
                error_code="plugin.not_found",
            )

        # Count before removing: rmtree destroys the evidence.
        file_count, total_bytes = _count_regular_files(target)
        try:
            shutil.rmtree(target)
        except OSError as exc:
            raise ConfigError(
                f"Failed to uninstall plugin {plugin_id!r}: {exc}",
                error_code="plugin.uninstall_failed",
            ) from exc

        logger.info(
            "Uninstalled plugin %r (%d files, %d bytes)", plugin_id, file_count, total_bytes
        )
        return file_count, total_bytes

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_manifest(self, manifest_path: Path) -> PluginManifest:
        """Read + parse + validate one manifest file."""
        if not manifest_path.is_file():
            raise ConfigError(
                f"Plugin manifest not found: {manifest_path}",
                error_code="plugin.manifest_missing",
            )
        try:
            xml_bytes = manifest_path.read_bytes()
        except OSError as exc:
            raise ConfigError(
                f"Cannot read plugin manifest {manifest_path}: {exc}",
                error_code="plugin.manifest_invalid",
            ) from exc

        manifest, issues = parse_plugin_manifest(xml_bytes)
        if issues:
            raise ConfigError(
                f"{manifest_path}: {issues[0].message}",
                error_code=issues[0].error_code,
            )
        return manifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _describe_version(manifest: PluginManifest) -> str:
    """Render a manifest version for messages: ``version 2 (2.0.0)``."""
    if manifest.version_name:
        return f"version {manifest.version} ({manifest.version_name})"
    return f"version {manifest.version}"


def _is_zipfile(path: Path) -> bool:
    """``zipfile.is_zipfile`` that answers False instead of raising."""
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def _same_directory(first: Path, second: Path) -> bool:
    """True when both paths name the same existing directory."""
    try:
        return first.samefile(second)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Pack helpers
# ---------------------------------------------------------------------------


def _collect_pack_members(
    plugin_dir: Path, plugin_id: str, output_path: Path
) -> list[tuple[Path, str]]:
    """Return ``(source, archive name)`` for every file to pack.

    Symlinks are skipped: they are not regular files and could point outside
    the plugin directory.  *output_path* is skipped too when it already
    exists inside *plugin_dir*, so packing over a previous archive never
    embeds that archive in the new one.
    """
    excluded = _resolved_path(output_path)
    members: list[tuple[Path, str]] = []

    for path in sorted(plugin_dir.rglob("*")):
        try:
            if path.is_symlink() or not path.is_file():
                continue
        except OSError:
            # A file that cannot be inspected is not worth failing the pack
            # over; it is simply not part of the package.
            continue

        relative = path.relative_to(plugin_dir)
        if _is_pack_noise(relative):
            continue
        if excluded is not None and _resolved_path(path) == excluded:
            continue

        members.append((path, _pack_member_name(plugin_id, relative)))

    return members


def _is_pack_noise(relative: Path) -> bool:
    """True for development noise: ``__pycache__/``, ``.git/``, ``*.pyc``."""
    parts = relative.parts
    if any(part in _PACK_NOISE_DIRECTORIES for part in parts):
        return True
    return relative.name.endswith(_PACK_NOISE_SUFFIXES)


def _pack_member_name(plugin_id: str, relative: Path) -> str:
    """Build ``<plugin_id>/<relative>`` with ``/`` separators.

    The relative path comes from ``rglob`` on the source directory, so it is
    already confined to it; the assertions below make that a checked
    invariant rather than an assumption.
    """
    parts = (plugin_id, *relative.parts)
    unsafe = any(
        part in ("", ".", "..") or "/" in part or "\\" in part or ":" in part for part in parts
    )
    if unsafe:
        raise ConfigError(
            f"Refused to pack unsafe archive member: {'/'.join(parts)!r}",
            error_code="plugin.pack_failed",
        )
    return PurePosixPath(*parts).as_posix()


def _resolved_path(path: Path) -> Path | None:
    """``Path.resolve()`` that answers ``None`` instead of raising."""
    try:
        return path.resolve()
    except OSError:
        return None


def _discard_partial_archive(output_path: Path) -> None:
    """Remove a partially written archive; the caller reports the failure."""
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Cannot remove partial plugin archive: %s", output_path)


def _select_zip_members(
    archive: zipfile.ZipFile, prefix: tuple[str, ...]
) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    """Validate every member and return the ones to extract, prefix stripped.

    Every member — including the ones that are skipped — must pass the
    path checks, so a hostile archive is refused before a single byte is
    written and a failed install leaves no half-extracted directory.
    """
    selected: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []

    for info in archive.infolist():
        parts = _safe_member_parts(info.filename)
        if parts is None:
            raise ConfigError(
                f"Refused to extract unsafe archive member: {info.filename!r}",
                error_code="plugin.install_failed",
            )
        if not parts or info.filename.endswith(("/", "\\")):
            continue  # explicit directory entry
        if prefix:
            if parts[: len(prefix)] != prefix:
                continue
            parts = parts[len(prefix) :]
        if not parts:
            continue
        selected.append((info, parts))

    return selected


def _count_regular_files(directory: Path) -> tuple[int, int]:
    """Return ``(file_count, total_bytes)`` of the regular files under *directory*."""
    files = 0
    total = 0
    for path in directory.rglob("*"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            total += path.stat().st_size
        except OSError:
            # A file that cannot be stat'ed simply does not contribute; the
            # removal decides whether the operation itself fails.
            continue
        files += 1
    return files, total
