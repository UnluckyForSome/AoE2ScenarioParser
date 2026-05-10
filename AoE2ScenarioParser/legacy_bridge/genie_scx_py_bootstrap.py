"""Put the ``genie-scx-py`` git submodule on ``sys.path`` so ``import genie_scx_py`` works."""

from __future__ import annotations

import sys
from pathlib import Path

_LEGACY_BRIDGE = Path(__file__).resolve().parent
_SUBMODULE_PKG = _LEGACY_BRIDGE / "genie-scx-py" / "genie_scx_py"


def ensure_genie_scx_py_on_path() -> None:
    """Repo checkout must include ``AoE2ScenarioParser/legacy_bridge/genie-scx-py`` (submodule)."""
    if not _SUBMODULE_PKG.is_dir():
        raise ImportError(
            "genie-scx-py submodule missing or not initialized. From the repository root run:\n"
            "  git submodule update --init -- AoE2ScenarioParser/legacy_bridge/genie-scx-py"
        )
    root = str(_LEGACY_BRIDGE / "genie-scx-py")
    if root not in sys.path:
        sys.path.insert(0, root)
