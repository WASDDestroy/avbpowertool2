"""Contract tests for the hexagonal dependency direction.

The documented direction is ``presentation -> application -> domain``
(see ``AGENTS.md``): ``infrastructure`` implements the ports defined in
``application``, and the inner layers never reach outwards.  A single
stray import is enough to invert that direction silently, so the rules
are checked mechanically here by parsing the sources with :mod:`ast`
(never with a regex: ``from x import y`` inside a string or a comment is
not an import, and a regex cannot tell the difference).

Scope:

* ``avbpowertool/domain/**`` may not import ``application``,
  ``infrastructure`` or ``presentation``.
* ``avbpowertool/application/**`` may not import ``presentation``.

``application -> infrastructure`` is deliberately *not* forbidden: the
service layer currently imports ``infrastructure.persistence`` and
``infrastructure.filesystem.workspace`` directly, which is existing
behaviour this test must not change.  ``infrastructure`` itself is out
of scope: it is allowed to import both inner layers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE_ROOT = REPO_ROOT / "avbpowertool"

#: Layer directories, relative to the package root.
LAYERS = ("domain", "application")

#: Forbidden top-level import targets per layer.
FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    "domain": ("application", "infrastructure", "presentation"),
    "application": ("presentation",),
}


def _layer_files(layer: str) -> list[Path]:
    """Every ``.py`` file of one layer, in a stable order."""
    return sorted((PACKAGE_ROOT / layer).rglob("*.py"))


def _imported_modules(node: ast.AST) -> list[str]:
    """The absolute ``avbpowertool.*`` module names an import statement pulls in.

    ``import a.b as c`` and ``from a.b import c`` both yield ``a.b``.
    Relative imports (``from ..domain import y``) and third-party modules
    are skipped: they cannot name a layer of this package, and treating
    their leading segment as a top-level name would produce false
    positives.
    """
    if isinstance(node, ast.Import):
        modules = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
        modules = [node.module] if node.module and node.level == 0 else []
    else:
        return []
    return [module for module in modules if module.split(".")[0] == "avbpowertool"]


def _display(path: Path) -> str:
    """Repo-relative POSIX path when possible, absolute otherwise."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _violations(path: Path, forbidden: tuple[str, ...]) -> list[str]:
    """Describe every forbidden import in ``path`` as ``file:line: module``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        for module in _imported_modules(node):
            # Compare on whole dotted segments so that a module such as
            # ``avbpowertool.presentation_helpers`` is not mistaken for
            # ``avbpowertool.presentation``.
            parts = module.split(".")
            for target in forbidden:
                if target in parts[1:]:
                    found.append(
                        f"{_display(path)}:{node.lineno}: imports {module!r} (forbidden {target!r})"
                    )
    return found


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_files_are_discovered(layer: str) -> None:
    """A silently empty glob would make every other assertion vacuous."""
    assert _layer_files(layer), f"no Python files found under avbpowertool/{layer}/"


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_respects_the_dependency_direction(layer: str) -> None:
    forbidden = FORBIDDEN_IMPORTS[layer]
    violations = [v for path in _layer_files(layer) for v in _violations(path, forbidden)]
    assert violations == [], (
        f"avbpowertool/{layer}/ must not import {', '.join(forbidden)}:\n  "
        + "\n  ".join(violations)
    )


def test_domain_does_not_import_application() -> None:
    """Spelled out separately: ``domain`` is the innermost layer."""
    violations = [
        v
        for path in _layer_files("domain")
        for v in _violations(path, ("application", "presentation", "infrastructure"))
    ]
    assert violations == [], "avbpowertool/domain/ must stay dependency-free:\n  " + "\n  ".join(
        violations
    )


def test_detector_catches_a_forbidden_import(tmp_path: Path) -> None:
    """The detector itself must fail loudly, including line numbers."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import avbpowertool.presentation.i18n\n"
        "from avbpowertool.presentation.i18n import get_current_language\n"
        "from ..domain import models\n"
        "import os\n",
        encoding="utf-8",
    )

    found = _violations(sample, ("presentation",))

    assert len(found) == 2
    assert ":1: " in found[0]
    assert "avbpowertool.presentation.i18n" in found[0]
    assert ":2: " in found[1]
    assert "os" not in " ".join(found)
    assert "domain" not in " ".join(found)
