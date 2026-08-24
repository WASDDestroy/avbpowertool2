"""Tests for SubprocessAvbTool runner."""

from __future__ import annotations

from pathlib import Path

from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool


class TestSubprocessAvbTool:
    def test_init_defaults(self, tmp_path: Path) -> None:
        script = tmp_path / "avbtool.py"
        script.write_text("# placeholder")
        tool = SubprocessAvbTool(script)
        assert tool._script == str(script)
        assert tool._timeout == 300.0

    def test_init_custom_timeout(self, tmp_path: Path) -> None:
        script = tmp_path / "avbtool.py"
        script.write_text("# placeholder")
        tool = SubprocessAvbTool(script, timeout=60.0)
        assert tool._timeout == 60.0

    def test_inspect_nonexistent_script(self, tmp_path: Path) -> None:
        tool = SubprocessAvbTool(tmp_path / "nonexistent.py")
        result = tool.inspect_image(Path("/fake/image.img"))
        # On Windows, Python returns 2 for missing script; on POSIX OSError -> -1
        assert result.returncode != 0
        assert result.stderr

    def test_command_summary_redacts_key(self, tmp_path: Path) -> None:
        """Verify that --key paths are redacted in command summaries."""
        script = tmp_path / "avbtool.py"
        script.write_text("# placeholder")
        tool = SubprocessAvbTool(script)

        # We can't actually run avbtool, but we can test the summary sanitization
        # by checking the _run method's behavior via a real subprocess that fails
        result = tool.add_hash_footer(
            Path("/img/boot.img"),
            Path("/staging/boot.img"),
            partition_name="boot",
            algorithm="SHA256_RSA4096",
            key_path=Path("/secret/keys/test.pem"),
            salt="abcdef",
            rollback_index=0,
        )
        # The command summary should NOT contain the key path
        assert "/secret/keys/test.pem" not in result.command_summary
        assert "<redacted>" in result.command_summary

    def test_avbtool_result_fields(self, tmp_path: Path) -> None:
        script = tmp_path / "avbtool.py"
        script.write_text("# placeholder")
        tool = SubprocessAvbTool(script)

        result = tool.erase_footer(Path("/fake/image.img"))
        assert hasattr(result, "returncode")
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "command_summary")
