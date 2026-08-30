"""Tests for the audit-logging pipeline (bootstrap + CLI dispatch)."""

from __future__ import annotations

import json
import logging
from io import StringIO
from pathlib import Path

import pytest

from avbpowertool.presentation import audit
from avbpowertool.presentation.cli.parser import main


@pytest.fixture(autouse=True)
def _restore_logging() -> None:
    """Snapshot and restore root logger state around each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_audit_level = audit.audit_logger().level
    yield
    for handler in root.handlers:
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(saved_level)
    audit.audit_logger().setLevel(saved_audit_level)


def _enter_workspace(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir(exist_ok=True)
    (tmp_path / "Logs").mkdir(exist_ok=True)
    (tmp_path / ".avbpowertool-staging").mkdir(exist_ok=True)
    (tmp_path / "Images").mkdir(exist_ok=True)
    (tmp_path / "avbtool.py").write_text("# placeholder", encoding="utf-8")


class TestBootstrapAppliesLogLevel:
    def test_settings_log_level_is_applied(self, tmp_path: Path) -> None:
        from avbpowertool.bootstrap import bootstrap

        _enter_workspace(tmp_path)
        (tmp_path / "settings.json").write_text(
            json.dumps({"language": "en", "log_level": "DEBUG"}), encoding="utf-8"
        )
        bootstrap(root=tmp_path)
        assert audit.audit_logger().level == logging.DEBUG

    def test_default_log_level_is_info(self, tmp_path: Path) -> None:
        from avbpowertool.bootstrap import bootstrap

        _enter_workspace(tmp_path)
        bootstrap(root=tmp_path)
        assert audit.audit_logger().level == logging.INFO


class TestCliAuditTrail:
    def test_command_is_audited_to_session_file(self, tmp_path: Path) -> None:
        _enter_workspace(tmp_path)
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp_path)
            out = StringIO()
            code = main(["config", "list", "--json"], out=out)
        finally:
            os.chdir(old_cwd)

        assert code == 0
        # Each CLI invocation opens its own timestamped session log.
        log_files = list((tmp_path / "Logs").glob("avbpowertool_*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text(encoding="utf-8")
        # Session boundary with the raw argv ...
        assert "cli session.start: argv config list --json" in content
        # ... the dispatched action ...
        assert "cli action.start config.list" in content
        assert "cli action.end config.list: exit_code=0" in content
        # ... and the exit record.
        assert "cli session.end: exit_code=0" in content

    def test_debug_trail_written_at_debug_level(self, tmp_path: Path) -> None:
        _enter_workspace(tmp_path)
        (tmp_path / "settings.json").write_text(
            json.dumps({"language": "en", "log_level": "DEBUG"}), encoding="utf-8"
        )
        old_cwd = Path.cwd()
        try:
            import os

            os.chdir(tmp_path)
            out = StringIO()
            main(["config", "list", "--json"], out=out)
        finally:
            os.chdir(old_cwd)

        log_files = list((tmp_path / "Logs").glob("avbpowertool_*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text(encoding="utf-8")
        # DEBUG records now reach the file (bootstrap emits one), while the
        # CLI audit records stay INFO — the DEBUG audit trail is the TUI's.
        assert "DEBUG avbpowertool.bootstrap" in content
        assert "INFO avbpowertool.audit: cli session.start" in content
