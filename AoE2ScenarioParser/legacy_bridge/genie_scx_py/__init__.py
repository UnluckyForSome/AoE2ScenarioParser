"""
Pure-Python port of the Rust crate `genie-scx`.

This package is intentionally self-contained under `AoE2ScenarioParser/legacy_bridge/` and is
wired into the legacy bridge as an in-process parser/writer for legacy scenario formats.
"""

from __future__ import annotations

from .scenario import Scenario
from .types import (
    DefinitiveEditionScenarioError,
    SCXVersion,
    VersionBundle,
    is_definitive_edition_scenario_format,
    legacy_format_version_from_prefix,
    legacy_format_version_peek_path,
    MIN_DEFINITIVE_EDITION_FORMAT,
)
from ._support.strings import DecodeStringError, EncodeStringError

__all__ = [
    "Scenario",
    "SCXVersion",
    "VersionBundle",
    "DefinitiveEditionScenarioError",
    "MIN_DEFINITIVE_EDITION_FORMAT",
    "is_definitive_edition_scenario_format",
    "legacy_format_version_from_prefix",
    "legacy_format_version_peek_path",
    "DecodeStringError",
    "EncodeStringError",
]

