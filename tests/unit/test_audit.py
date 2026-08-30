"""Tests for the audit logging helpers (presentation/audit.py)."""

from __future__ import annotations

import logging

import pytest

from avbpowertool.presentation import audit


@pytest.fixture
def audit_caplog(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture records from the audit logger at DEBUG level."""
    caplog.set_level(logging.DEBUG, logger=audit.AUDIT_LOGGER_NAME)
    return caplog


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


class TestAuditHelpers:
    def test_session_start_end(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        audit.log_session_start("tui", "root=/tmp/ws")
        audit.log_session_end("cli", "exit_code=0")
        messages = _messages(audit_caplog)
        assert messages[0] == "tui session.start: root=/tmp/ws"
        assert messages[-1] == "cli session.end: exit_code=0"
        # Session boundaries are INFO so they survive the default level.
        assert audit_caplog.records[0].levelno == logging.INFO

    def test_navigation_is_debug(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        audit.log_navigation("enter", "route:home (start)")
        assert _messages(audit_caplog) == ["tui nav.enter: route:home (start)"]
        assert audit_caplog.records[0].levelno == logging.DEBUG

    def test_selection_choose_and_cancel(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        items = ["boot.img", "vbmeta.img"]
        audit.log_selection("Select Images", items, [1])
        audit.log_selection("Select Images", items, [])
        messages = _messages(audit_caplog)
        assert messages[0] == "tui select.choose: Select Images -> [1] vbmeta.img"
        assert messages[1] == "tui select.cancel: Select Images"

    def test_selection_out_of_range_index_is_safe(
        self, audit_caplog: pytest.LogCaptureFixture
    ) -> None:
        audit.log_selection("T", ["a"], [5])
        assert "[5] <index 5>" in _messages(audit_caplog)[0]

    def test_input_submit_and_cancel(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        audit.log_input("Profile ID", "my_profile", cancelled=False)
        audit.log_input("Profile ID", "", cancelled=True)
        messages = _messages(audit_caplog)
        assert messages[0] == "tui input.submit: Profile ID -> 'my_profile'"
        assert messages[1] == "tui input.cancel: Profile ID"

    def test_confirmation_records_yes_no(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        audit.log_confirmation("Sign images?", True)
        audit.log_confirmation("Delete profile?", False)
        messages = _messages(audit_caplog)
        assert messages[0] == "tui confirm: Sign images? -> yes"
        assert messages[1] == "tui confirm: Delete profile? -> no"

    def test_message_screen(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        audit.log_message_screen("Signing Results")
        assert _messages(audit_caplog) == ["tui message: Signing Results"]

    def test_action_start_end(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        audit.log_action_start("cli", "config.activate", "p1")
        audit.log_action_end("cli", "config.activate", "exit_code=0")
        messages = _messages(audit_caplog)
        assert messages[0] == "cli action.start config.activate: p1"
        assert messages[1] == "cli action.end config.activate: exit_code=0"

    def test_cli_command_logging(self, audit_caplog: pytest.LogCaptureFixture) -> None:
        audit.log_cli_command(["config", "list", "--json"])
        assert _messages(audit_caplog) == ["cli session.start: argv config list --json"]


class TestSetupLogging:
    @staticmethod
    def _make_ws(root) -> object:
        from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths

        ws = WorkspacePaths(
            root=root,
            images=root / "Images",
            profiles=root / "profiles",
            logs=root / "Logs",
            staging=root / ".staging",
            avbtool_script=root / "avbtool.py",
        )
        ws.ensure_dirs()
        return ws

    def test_audit_level_follows_setting(self, tmp_path_factory: pytest.TempPathFactory) -> None:
        from avbpowertool.bootstrap import setup_logging

        ws = self._make_ws(tmp_path_factory.mktemp("ws"))

        setup_logging(ws, "DEBUG")
        assert audit.audit_logger().isEnabledFor(logging.DEBUG)

        setup_logging(ws, "INFO")
        assert not audit.audit_logger().isEnabledFor(logging.DEBUG)
        assert audit.audit_logger().isEnabledFor(logging.INFO)

        # WARNING/ERROR silence the audit trail entirely.
        setup_logging(ws, "WARNING")
        assert not audit.audit_logger().isEnabledFor(logging.INFO)

        # Unknown names fall back to INFO instead of raising.
        setup_logging(ws, "not-a-level")
        assert audit.audit_logger().level == logging.INFO

    def test_each_setup_creates_a_new_session_log(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Every setup_logging call opens a fresh timestamped log file."""
        from avbpowertool.bootstrap import setup_logging

        ws = self._make_ws(tmp_path_factory.mktemp("ws2"))

        path1 = setup_logging(ws, "INFO")
        path2 = setup_logging(ws, "INFO")

        assert path1.exists() and path2.exists()
        assert path1 != path2  # same second -> _2 suffix disambiguates
        assert path1.parent == ws.logs
        # Only the latest session's handler stays attached.
        root_handlers = logging.getLogger().handlers
        assert (
            sum(
                1
                for h in root_handlers
                if isinstance(h, logging.FileHandler) and h.baseFilename in (str(path1), str(path2))
            )
            == 1
        )

    def test_session_log_path_avoids_existing_files(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        from avbpowertool.bootstrap import session_log_path

        logs_dir = tmp_path_factory.mktemp("ws3") / "Logs"
        logs_dir.mkdir()

        first = session_log_path(logs_dir)
        first.write_text("", encoding="utf-8")  # occupy the name
        second = session_log_path(logs_dir)

        assert first != second
        assert second.stem.endswith("_2")
