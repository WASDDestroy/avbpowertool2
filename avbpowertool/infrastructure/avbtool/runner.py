"""Real AvbToolPort implementation via bundled avbtool.py subprocess."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from avbpowertool.application.ports import AvbToolResult

logger = logging.getLogger(__name__)


class SubprocessAvbTool:
    """Invoke the bundled avbtool.py as a subprocess.

    Implements the AvbToolPort protocol.
    """

    def __init__(
        self,
        avbtool_script: Path,
        python_exe: str | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._script = str(avbtool_script)
        self._python = python_exe or sys.executable
        self._timeout = timeout

    # ------------------------------------------------------------------
    # AvbToolPort
    # ------------------------------------------------------------------

    def inspect_image(self, image_path: Path, cert: bool = False) -> AvbToolResult:
        cmd = ["info_image", "--image", str(image_path)]
        if cert:
            cmd.append("--cert")
        return self._run(cmd)

    def erase_footer(self, image_path: Path) -> AvbToolResult:
        return self._run(["erase_footer", "--image", str(image_path)])

    def add_hash_footer(
        self,
        image_path: Path,
        *,
        partition_name: str,
        algorithm: str,
        key_path: Path | None = None,
        salt: str,
        rollback_index: int,
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        cmd = [
            "add_hash_footer",
            "--image",
            str(image_path),
            "--partition_name",
            partition_name,
            "--salt",
            salt,
            "--rollback_index",
            str(rollback_index),
        ]
        if key_path is not None:
            cmd.extend(["--algorithm", algorithm, "--key", str(key_path)])
        if flags:
            cmd.extend(["--flags", str(flags)])
        for k, v in props:
            cmd.extend(["--prop", f"{k}:{v}"])
        return self._run(cmd)

    def add_hashtree_footer(
        self,
        image_path: Path,
        *,
        partition_name: str,
        algorithm: str,
        key_path: Path | None = None,
        salt: str,
        rollback_index: int,
        block_size: int = 4096,
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        cmd = [
            "add_hashtree_footer",
            "--image",
            str(image_path),
            "--partition_name",
            partition_name,
            "--salt",
            salt,
            "--rollback_index",
            str(rollback_index),
            "--block_size",
            str(block_size),
        ]
        if key_path is not None:
            cmd.extend(["--algorithm", algorithm, "--key", str(key_path)])
        if flags:
            cmd.extend(["--flags", str(flags)])
        for k, v in props:
            cmd.extend(["--prop", f"{k}:{v}"])
        return self._run(cmd)

    def make_vbmeta_image(
        self,
        output_path: Path,
        *,
        algorithm: str,
        key_path: Path | None = None,
        rollback_index: int,
        include_descriptors: tuple[Path, ...] = (),
        chain_partitions: tuple[str, ...] = (),
        flags: int = 0,
        props: tuple[tuple[str, str], ...] = (),
    ) -> AvbToolResult:
        cmd = [
            "make_vbmeta_image",
            "--output",
            str(output_path),
            "--rollback_index",
            str(rollback_index),
        ]
        if key_path is not None:
            cmd.extend(["--algorithm", algorithm, "--key", str(key_path)])
        for desc in include_descriptors:
            cmd.extend(["--include_descriptors_from_image", str(desc)])
        for chain in chain_partitions:
            cmd.extend(["--chain_partition", chain])
        if flags:
            cmd.extend(["--flags", str(flags)])
        for k, v in props:
            cmd.extend(["--prop", f"{k}:{v}"])
        return self._run(cmd)

    def extract_public_key(self, key_path: Path, output_path: Path) -> AvbToolResult:
        return self._run(
            [
                "extract_public_key",
                "--key",
                str(key_path),
                "--output",
                str(output_path),
            ]
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _run(self, avb_args: list[str]) -> AvbToolResult:
        """Execute avbtool with the given arguments.

        Command summary is sanitized to not include key material paths.
        """
        cmd = [self._python, self._script] + avb_args
        # Build a sanitized summary (no key paths for logging)
        summary_parts = [avb_args[0]] if avb_args else []
        skip_next = False
        for _i, arg in enumerate(avb_args[1:], 1):
            if skip_next:
                skip_next = False
                continue
            if arg == "--key":
                summary_parts.append("--key <redacted>")
                skip_next = True
            else:
                summary_parts.append(arg)
        summary = " ".join(summary_parts)

        logger.debug("avbtool: %s", summary)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout,
            )
            return AvbToolResult(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                command_summary=summary,
            )
        except subprocess.TimeoutExpired:
            return AvbToolResult(
                returncode=-1,
                stdout="",
                stderr=f"avbtool timed out after {self._timeout}s",
                command_summary=summary,
            )
        except OSError as exc:
            return AvbToolResult(
                returncode=-1,
                stdout="",
                stderr=f"Failed to execute avbtool: {exc}",
                command_summary=summary,
            )
