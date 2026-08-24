"""Stable error hierarchy with machine-readable error codes.

All errors raised by application/domain/infrastructure layers
inherit from AvbError and carry an ``error_code`` suitable for
localization lookups and CLI exit-code mapping.
"""

from __future__ import annotations


class AvbError(Exception):
    """Base for all AVB Power Tool errors."""

    error_code: str = "error.unknown"

    def __init__(self, message: str = "", *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class ValidationError(AvbError):
    """Input does not satisfy domain rules."""

    error_code = "validation.invalid"


class ConfigError(AvbError):
    """Configuration is missing, malformed, or inconsistent."""

    error_code = "config.invalid"


class WorkspaceError(AvbError):
    """Workspace layout or path problem."""

    error_code = "workspace.invalid"


class ToolExecutionError(AvbError):
    """An external tool (avbtool, openssl, fec) returned non-zero exit code."""

    error_code = "tool.execution_failed"


class SigningError(AvbError):
    """An error occurred during the signing workflow."""

    error_code = "signing.failed"
