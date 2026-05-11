from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aoe2_mcgeniescx import Scenario as LegacyScenario

from AoE2ScenarioParser import settings
from AoE2ScenarioParser.scenario_detection import (
    ScenarioDetectionResult,
    ScenarioEdition,
    ScenarioSource,
    detect_scenario_edition,
)
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario


@dataclass(frozen=True, slots=True)
class ParsedScenario:
    edition: ScenarioEdition
    detection: ScenarioDetectionResult
    scenario: Any

    @property
    def is_definitive_edition(self) -> bool:
        return self.edition == ScenarioEdition.DEFINITIVE


@contextmanager
def suppress_status_updates(enabled: bool):
    if not enabled:
        yield
        return

    old_print = settings.PRINT_STATUS_UPDATES
    settings.PRINT_STATUS_UPDATES = False
    try:
        yield
    finally:
        settings.PRINT_STATUS_UPDATES = old_print


def _read_source_bytes(source: ScenarioSource) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    data = source.read()
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError("Scenario source must be a path, bytes-like object, or binary reader")


def _parse_definitive_scenario(
    source: ScenarioSource,
    *,
    name: str = "",
    suppress_output: bool = False,
) -> AoE2DEScenario:
    if isinstance(source, (str, Path)):
        with suppress_status_updates(suppress_output):
            return AoE2DEScenario.from_file(str(source), name=name)

    data = _read_source_bytes(source)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".aoe2scenario") as tmp:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name
        with suppress_status_updates(suppress_output):
            return AoE2DEScenario.from_file(tmp_path, name=name)
    finally:
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def parse_legacy_scenario(source: ScenarioSource) -> LegacyScenario:
    return LegacyScenario.read_from_bytes(_read_source_bytes(source))


def parse_definitive_scenario(
    source: ScenarioSource,
    *,
    name: str = "",
    suppress_output: bool = False,
) -> AoE2DEScenario:
    return _parse_definitive_scenario(source, name=name, suppress_output=suppress_output)


def parse_scenario(
    source: ScenarioSource,
    *,
    name: str = "",
    suppress_output: bool = False,
) -> ParsedScenario:
    if isinstance(source, (str, Path)):
        detection_source = source
        parse_source = source
    else:
        parse_source = _read_source_bytes(source)
        detection_source = parse_source

    detection = detect_scenario_edition(detection_source)
    if detection.edition == ScenarioEdition.DEFINITIVE:
        return ParsedScenario(
            edition=ScenarioEdition.DEFINITIVE,
            detection=detection,
            scenario=_parse_definitive_scenario(parse_source, name=name, suppress_output=suppress_output),
        )
    if detection.edition == ScenarioEdition.LEGACY:
        return ParsedScenario(
            edition=ScenarioEdition.LEGACY,
            detection=detection,
            scenario=parse_legacy_scenario(parse_source),
        )
    raise ValueError(detection.reason or "Unable to detect scenario edition")


__all__ = [
    "ParsedScenario",
    "parse_definitive_scenario",
    "parse_legacy_scenario",
    "parse_scenario",
    "suppress_status_updates",
]
