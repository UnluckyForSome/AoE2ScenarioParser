from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Optional, Union

from aoe2_mcgeniescx._io import inflate_raw
from aoe2_mcgeniescx.header import SCXHeader
from aoe2_mcgeniescx.types import (
    SCXVersion,
    is_ascii_scx_version_prefix,
    is_definitive_edition_container_format,
    is_definitive_edition_scenario_data_version,
    normalize_scenario_data_version,
)

ScenarioSource = Union[str, Path, bytes, bytearray, memoryview, BinaryIO]


class ScenarioEdition(str, Enum):
    LEGACY = "legacy"
    DEFINITIVE = "definitive"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ScenarioDetectionResult:
    edition: ScenarioEdition
    container_format: Optional[str] = None
    data_version: Optional[float] = None
    reason: Optional[str] = None

    @property
    def is_definitive_edition(self) -> bool:
        return self.edition == ScenarioEdition.DEFINITIVE


def _read_source_bytes(source: ScenarioSource) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    data = source.read()
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError("Scenario source must be a path, bytes-like object, or binary reader")


def detect_scenario_edition(source: ScenarioSource) -> ScenarioDetectionResult:
    data = _read_source_bytes(source)
    if len(data) < 4:
        return ScenarioDetectionResult(
            edition=ScenarioEdition.UNKNOWN,
            reason="missing format version",
        )

    prefix = data[:4]
    if not is_ascii_scx_version_prefix(prefix):
        return ScenarioDetectionResult(
            edition=ScenarioEdition.UNKNOWN,
            reason="missing ASCII container format prefix",
        )

    format_version = SCXVersion(prefix)
    container_format = str(format_version)

    if is_definitive_edition_container_format(format_version):
        return ScenarioDetectionResult(
            edition=ScenarioEdition.DEFINITIVE,
            container_format=container_format,
            reason="container format",
        )

    if format_version.to_player_version() is None:
        return ScenarioDetectionResult(
            edition=ScenarioEdition.UNKNOWN,
            container_format=container_format,
            reason="unsupported legacy container format",
        )

    try:
        reader = io.BytesIO(data)
        reader.read(4)
        SCXHeader.read_from(reader, format_version)
        compressed = reader.read()
        payload = inflate_raw(compressed)
        if len(payload) < 8:
            return ScenarioDetectionResult(
                edition=ScenarioEdition.UNKNOWN,
                container_format=container_format,
                reason="scenario payload too short",
            )
        data_version = normalize_scenario_data_version(
            struct.unpack_from("<f", payload, 4)[0]
        )
    except Exception as exc:  # noqa: BLE001 - keep corrupt/partial files distinct from valid legacy.
        return ScenarioDetectionResult(
            edition=ScenarioEdition.UNKNOWN,
            container_format=container_format,
            reason=f"unable to inspect scenario payload: {exc}",
        )

    if is_definitive_edition_scenario_data_version(data_version):
        return ScenarioDetectionResult(
            edition=ScenarioEdition.DEFINITIVE,
            container_format=container_format,
            data_version=data_version,
            reason="scenario data version",
        )

    return ScenarioDetectionResult(
        edition=ScenarioEdition.LEGACY,
        container_format=container_format,
        data_version=data_version,
        reason="legacy format and payload",
    )


def is_definitive_edition(source: ScenarioSource) -> bool:
    return detect_scenario_edition(source).is_definitive_edition


__all__ = [
    "ScenarioDetectionResult",
    "ScenarioEdition",
    "ScenarioSource",
    "detect_scenario_edition",
    "is_definitive_edition",
]
