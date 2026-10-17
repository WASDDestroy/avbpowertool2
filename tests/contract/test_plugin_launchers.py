"""Contract tests for plugin launcher scripts.

``cmd.exe`` reads ``.cmd`` / ``.bat`` files using the OEM code page (cp936 on a
Chinese Windows), not UTF-8.  A non-ASCII byte therefore shifts the byte stream
while parsing and can turn one line into several commands: a Chinese ``REM``
comment in ``make-testkey-config.cmd`` made the launcher exit with 9009
("'...' is not recognized as an internal or external command").

Batch launchers must stay ASCII-only; put translated text in the ``.ps1`` /
``.py`` entry (PowerShell 7 reads UTF-8) or in the plugin README.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PLUGINS_DIR = Path(__file__).parent.parent.parent / "plugins"


def _batch_files() -> list[Path]:
    if not PLUGINS_DIR.is_dir():
        return []
    return sorted([*PLUGINS_DIR.rglob("*.cmd"), *PLUGINS_DIR.rglob("*.bat")])


def _powershell_files() -> list[Path]:
    if not PLUGINS_DIR.is_dir():
        return []
    return sorted(PLUGINS_DIR.rglob("*.ps1"))


def test_plugins_directory_is_present() -> None:
    """Guard against the globs silently matching nothing."""
    assert PLUGINS_DIR.is_dir(), f"plugin directory not found: {PLUGINS_DIR}"


def test_at_least_one_batch_launcher_is_discovered() -> None:
    assert _batch_files(), "no plugin batch launcher found; the ASCII guard would be vacuous"


@pytest.mark.parametrize("path", _batch_files(), ids=lambda p: p.name)
def test_batch_launcher_is_ascii_only(path: Path) -> None:
    data = path.read_bytes()
    offenders = [index for index, byte in enumerate(data) if byte > 0x7F]
    assert not offenders, (
        f"{path.name}: non-ASCII bytes at offsets {offenders[:5]}"
        f"{' ...' if len(offenders) > 5 else ''}; cmd.exe decodes batch files with the OEM "
        "code page, so non-ASCII text can break line parsing (exit code 9009)"
    )


@pytest.mark.parametrize("path", _batch_files(), ids=lambda p: p.name)
def test_batch_launcher_has_no_utf8_bom(path: Path) -> None:
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), (
        f"{path.name}: batch files must not start with a UTF-8 BOM"
    )


@pytest.mark.parametrize("path", _powershell_files(), ids=lambda p: p.name)
def test_powershell_entry_is_valid_utf8(path: Path) -> None:
    """``pwsh`` reads scripts as UTF-8; invalid bytes would render as mojibake."""
    path.read_bytes().decode("utf-8")
