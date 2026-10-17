"""Plugin management use cases: list, pack, install, uninstall, run."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from avbpowertool.application.commands import (
    PluginInstallRequest,
    PluginInstallResult,
    PluginListItem,
    PluginListRequest,
    PluginListResult,
    PluginPackRequest,
    PluginPackResult,
    PluginRunRequest,
    PluginRunResult,
    PluginUninstallRequest,
    PluginUninstallResult,
)
from avbpowertool.application.ports import PluginRunnerPort
from avbpowertool.domain.errors import ConfigError
from avbpowertool.domain.models import OperationIssue
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.infrastructure.persistence.plugin_repository import (
    PluginRepository,
)

logger = logging.getLogger(__name__)

#: Language used when the caller does not inject one.
DEFAULT_LANGUAGE = "en"

#: Environment contract handed to every plugin.  A plugin talks back to
#: the tool through the CLI (``$AVBPOWERTOOL_CLI``) rather than through an
#: import, so the variables are the whole interface.
ENV_ROOT = "AVBPOWERTOOL_ROOT"
ENV_PLUGIN_DIR = "AVBPOWERTOOL_PLUGIN_DIR"
ENV_PLUGIN_ID = "AVBPOWERTOOL_PLUGIN_ID"
ENV_LANG = "AVBPOWERTOOL_LANG"
ENV_CLI = "AVBPOWERTOOL_CLI"

#: How a plugin is expected to invoke this tool from inside the workspace.
PLUGIN_CLI_COMMAND = "uv run avbpowertool"


def _invalid_id_issue(plugin_id: str) -> OperationIssue:
    """The shared ``plugin.id_invalid`` issue (same rule as profile ids)."""
    return OperationIssue(
        "plugin.id_invalid",
        f"Invalid plugin id: {plugin_id!r} (must be a single directory name under plugins/)",
    )


class PluginListUseCase:
    """List every installed plugin, resolved for the injected language.

    The language is a constructor argument rather than a lookup: the
    application layer must not reach into the presentation layer, so the
    caller (CLI/TUI) owns the current language and passes it down.
    """

    def __init__(self, workspace: WorkspacePaths, language: str = DEFAULT_LANGUAGE) -> None:
        self._ws = workspace
        self._language = language

    def execute(self, _request: PluginListRequest) -> PluginListResult:
        repo = PluginRepository(self._ws.plugins)
        manifests, issues = repo.list_manifests()

        items = [
            PluginListItem(
                plugin_id=manifest.plugin_id,
                name=manifest.name_for(self._language),
                entry=manifest.entry,
                version=manifest.version,
                version_name=manifest.version_name,
                path=str(self._ws.resolve_plugin_dir(manifest.plugin_id)),
            )
            for manifest in manifests
        ]
        items.sort(key=lambda item: item.plugin_id)

        return PluginListResult(plugins=tuple(items), issues=tuple(issues))


class PluginInstallUseCase:
    """Install a plugin from a directory or a zip archive.

    The repository decides whether an existing installation may be
    replaced: a newer (or equal) ``version`` upgrades without ``force``, a
    lower one is refused with ``plugin.downgrade`` unless ``force`` is set,
    and an unreadable installed manifest falls back to ``plugin.exists``.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: PluginInstallRequest) -> PluginInstallResult:
        repo = PluginRepository(self._ws.plugins)
        try:
            manifest, file_count = repo.install(Path(request.source_path), request.force)
        except ConfigError as exc:
            # The id is unknown when the manifest itself is the problem;
            # the issue message carries the path (and the id when there is
            # one, as for plugin.exists / plugin.downgrade).
            logger.warning("Plugin install failed: %s", exc)
            return PluginInstallResult(issues=(OperationIssue(exc.error_code, str(exc)),))
        except OSError as exc:
            logger.error("Plugin install failed: %s", exc)
            return PluginInstallResult(
                issues=(
                    OperationIssue("plugin.install_failed", f"Failed to install plugin: {exc}"),
                )
            )

        return PluginInstallResult(
            plugin_id=manifest.plugin_id,
            installed=True,
            file_count=file_count,
            version=manifest.version,
            version_name=manifest.version_name,
        )


class PluginPackUseCase:
    """Pack a plugin directory into an installable zip.

    ``SOURCE`` is resolved in this order:

    1. an existing directory path (a plugin still under development, or any
       directory holding a manifest);
    2. ``<workspace>/plugins/<SOURCE>/`` (an installed plugin, addressed by
       its id);
    3. neither → ``plugin.not_found``.

    The archive uses the "exactly one directory level" layout
    (``<plugin_id>/…``) that ``plugin install`` understands, and defaults to
    ``<workspace root>/<plugin_id>.zip`` — the same style as
    ``config export``.  A source that carries key material (a ``keys/``
    directory or any ``.pem`` file) is reported, because those files are
    packed like any other content.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: PluginPackRequest) -> PluginPackResult:
        plugin_dir = self._resolve_source(request.source)
        if plugin_dir is None:
            logger.warning(
                "Cannot pack plugin %r: no such directory and not installed", request.source
            )
            return PluginPackResult(
                issues=(
                    OperationIssue(
                        "plugin.not_found",
                        f"Plugin not found: {request.source!r} (pass a plugin directory "
                        "path, or the id of a plugin installed under plugins/)",
                    ),
                )
            )

        repo = PluginRepository(self._ws.plugins)
        try:
            manifest = repo.read_manifest(plugin_dir)
        except ConfigError as exc:
            logger.warning("Cannot pack plugin from %s: %s", plugin_dir, exc)
            return PluginPackResult(issues=(OperationIssue(exc.error_code, str(exc)),))

        # The default output name comes from the manifest id, not from the
        # directory name: the archive's top level is the manifest id, so a
        # source directory that was renamed still packs consistently.
        output_path = (
            Path(request.output_path)
            if request.output_path
            else self._ws.root / f"{manifest.plugin_id}.zip"
        )

        try:
            manifest, file_count = repo.pack(plugin_dir, output_path)
        except ConfigError as exc:
            logger.warning("Cannot pack plugin %r: %s", manifest.plugin_id, exc)
            return PluginPackResult(
                plugin_id=manifest.plugin_id,
                output_path=str(output_path),
                version=manifest.version,
                version_name=manifest.version_name,
                issues=(OperationIssue(exc.error_code, str(exc)),),
            )
        except OSError as exc:
            logger.error("Failed to pack plugin %r: %s", manifest.plugin_id, exc)
            return PluginPackResult(
                plugin_id=manifest.plugin_id,
                output_path=str(output_path),
                version=manifest.version,
                version_name=manifest.version_name,
                issues=(OperationIssue("plugin.pack_failed", f"Failed to pack plugin: {exc}"),),
            )

        return PluginPackResult(
            plugin_id=manifest.plugin_id,
            output_path=str(output_path),
            file_count=file_count,
            version=manifest.version,
            version_name=manifest.version_name,
            includes_key_material=_includes_key_material(plugin_dir),
        )

    def _resolve_source(self, source: str) -> Path | None:
        """Resolve ``SOURCE`` to a plugin directory, or ``None`` (see above)."""
        if not source.strip():
            return None
        candidate = Path(source)
        if candidate.is_dir():
            return candidate
        installed = self._ws.plugins / source
        if installed.is_dir():
            return installed
        return None


def _includes_key_material(plugin_dir: Path) -> bool:
    """True when *plugin_dir* holds a ``keys/`` directory or any ``.pem``."""
    for path in plugin_dir.rglob("*"):
        try:
            if path.name.lower() == "keys" and path.is_dir():
                return True
            if path.suffix.lower() == ".pem" and path.is_file():
                return True
        except OSError:
            continue
    return False


class PluginUninstallUseCase:
    """Remove an installed plugin directory.

    Order of operations — every failure returns before anything is removed:

    1. the id must be a plain directory name: empty, ``.``, ``..`` or
       anything containing ``/`` / ``\\`` is rejected with
       ``plugin.id_invalid``, and so is a value whose resolved directory is
       not a *direct* child of ``plugins/``;
    2. the directory must exist, otherwise ``plugin.not_found``;
    3. the files under it are counted *before* the removal, so
       ``removed_files`` / ``removed_bytes`` describe what was there;
    4. the directory is removed; an ``OSError`` (a locked file on Windows,
       for instance) reports ``plugin.uninstall_failed``.
    """

    def __init__(self, workspace: WorkspacePaths) -> None:
        self._ws = workspace

    def execute(self, request: PluginUninstallRequest) -> PluginUninstallResult:
        plugin_id = request.plugin_id

        # 1. Never let an id address anything but one directory under plugins/.
        if not plugin_id or plugin_id in (".", "..") or "/" in plugin_id or "\\" in plugin_id:
            logger.warning("Refused to uninstall invalid plugin id %r", plugin_id)
            return PluginUninstallResult(plugin_id, issues=(_invalid_id_issue(plugin_id),))

        plugin_dir = self._ws.resolve_plugin_dir(plugin_id)
        if plugin_dir.resolve().parent != self._ws.plugins.resolve():
            logger.warning("Refused to uninstall plugin id outside plugins/: %r", plugin_id)
            return PluginUninstallResult(plugin_id, issues=(_invalid_id_issue(plugin_id),))

        repo = PluginRepository(self._ws.plugins)
        try:
            removed_files, removed_bytes = repo.uninstall(plugin_id)
        except ConfigError as exc:
            logger.warning("Cannot uninstall plugin %r: %s", plugin_id, exc)
            return PluginUninstallResult(
                plugin_id, issues=(OperationIssue(exc.error_code, str(exc)),)
            )
        except OSError as exc:
            logger.error("Failed to uninstall plugin %r: %s", plugin_id, exc)
            return PluginUninstallResult(
                plugin_id,
                issues=(
                    OperationIssue("plugin.uninstall_failed", f"Failed to uninstall plugin: {exc}"),
                ),
            )

        return PluginUninstallResult(
            plugin_id,
            removed=True,
            removed_files=removed_files,
            removed_bytes=removed_bytes,
        )


class PluginRunUseCase:
    """Run an installed plugin's entry script with the plugin environment.

    The plugin runs with ``cwd`` set to the workspace root and with its
    own directory exported through ``AVBPOWERTOOL_PLUGIN_DIR``, so it can
    reach both the workspace and its own files without being told where
    either is on the command line.  The language exported through
    ``AVBPOWERTOOL_LANG`` is injected by the caller, exactly as for
    :class:`PluginListUseCase`.
    """

    def __init__(
        self,
        workspace: WorkspacePaths,
        runner: PluginRunnerPort,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._ws = workspace
        self._runner = runner
        self._language = language

    def execute(self, request: PluginRunRequest) -> PluginRunResult:
        plugin_id = request.plugin_id

        # 1. Same id safety rule as uninstall: one plain directory name.
        if not plugin_id or plugin_id in (".", "..") or "/" in plugin_id or "\\" in plugin_id:
            logger.warning("Refused to run invalid plugin id %r", plugin_id)
            return PluginRunResult(plugin_id, exit_code=-1, issues=(_invalid_id_issue(plugin_id),))

        plugin_dir = self._ws.resolve_plugin_dir(plugin_id)
        if plugin_dir.resolve().parent != self._ws.plugins.resolve():
            logger.warning("Refused to run plugin id outside plugins/: %r", plugin_id)
            return PluginRunResult(plugin_id, exit_code=-1, issues=(_invalid_id_issue(plugin_id),))

        # 2. The manifest is validated on load, so ``entry`` is guaranteed
        # to be a bare file name inside the plugin directory.
        repo = PluginRepository(self._ws.plugins)
        try:
            manifest = repo.load_manifest(plugin_id)
        except ConfigError as exc:
            logger.warning("Cannot run plugin %r: %s", plugin_id, exc)
            return PluginRunResult(
                plugin_id, exit_code=-1, issues=(OperationIssue(exc.error_code, str(exc)),)
            )

        entry = plugin_dir / manifest.entry
        if not entry.is_file():
            logger.warning("Plugin %r entry not found: %s", plugin_id, entry)
            return PluginRunResult(
                plugin_id,
                exit_code=-1,
                issues=(
                    OperationIssue(
                        "plugin.entry_not_found",
                        f"Plugin entry not found: {entry}",
                    ),
                ),
            )

        # 3. Inherit the parent environment and layer the plugin contract
        # on top: the plugin may need PATH, HOME, ...
        env = dict(os.environ)
        env[ENV_ROOT] = str(self._ws.root)
        env[ENV_PLUGIN_DIR] = str(plugin_dir)
        env[ENV_PLUGIN_ID] = plugin_id
        env[ENV_LANG] = self._language
        env[ENV_CLI] = PLUGIN_CLI_COMMAND

        # 4. The workspace root is the plugin's working directory: every
        # relative path it builds (Images/, Logs/, profiles/) then means
        # the same thing it means to the tool itself.
        outcome = self._runner.run(entry, cwd=self._ws.root, env=env, args=request.args)

        # 5. A non-zero exit code is the plugin's own verdict and is passed
        # through untouched; only a plugin that never started is an error.
        if outcome.error:
            logger.error("Plugin %r failed to start: %s", plugin_id, outcome.error)
            return PluginRunResult(
                plugin_id,
                exit_code=-1,
                issues=(OperationIssue("plugin.run_failed", outcome.error),),
            )

        return PluginRunResult(plugin_id=plugin_id, exit_code=outcome.exit_code)
