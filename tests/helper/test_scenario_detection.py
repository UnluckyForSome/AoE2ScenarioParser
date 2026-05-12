from __future__ import annotations

import io
import struct
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from aoe2_mcgeniescx._io import deflate_raw
from aoe2_mcgeniescx.header import SCXHeader
from aoe2_mcgeniescx.types import SCXVersion

from AoE2ScenarioParser import verify_scenario
from AoE2ScenarioParser.scenario_detection import (
    ScenarioEdition,
    detect_scenario_edition,
    is_definitive_edition,
)
from AoE2ScenarioParser.scenario_parsing import parse_scenario


def _build_detection_fixture(format_token: bytes, data_version: float) -> bytes:
    out = io.BytesIO()
    out.write(format_token)
    header = SCXHeader(
        version=2,
        timestamp=0,
        description=None,
        author_name=None,
        any_sp_victory=True,
        active_player_count=8,
        dlc_options=None,
    )
    header.write_to(out, SCXVersion(format_token), 2)
    payload = struct.pack("<if", 0, float(data_version))
    out.write(deflate_raw(payload))
    return out.getvalue()


class TestScenarioDetection(TestCase):
    def test_detects_legacy_scenario(self):
        data = _build_detection_fixture(b"1.21", 1.14)

        result = detect_scenario_edition(data)

        self.assertEqual(ScenarioEdition.LEGACY, result.edition)
        self.assertEqual("1.21", result.container_format)
        self.assertAlmostEqual(1.14, result.data_version)
        self.assertFalse(is_definitive_edition(data))

    def test_detects_de_by_container_format(self):
        data = b"1.36"

        result = detect_scenario_edition(data)

        self.assertEqual(ScenarioEdition.DEFINITIVE, result.edition)
        self.assertEqual("1.36", result.container_format)
        self.assertIsNone(result.data_version)
        self.assertTrue(is_definitive_edition(data))

    def test_detects_de_by_payload_data_version(self):
        data = _build_detection_fixture(b"1.21", 1.30)

        result = detect_scenario_edition(data)

        self.assertEqual(ScenarioEdition.DEFINITIVE, result.edition)
        self.assertEqual("1.21", result.container_format)
        self.assertAlmostEqual(1.30, result.data_version)
        self.assertTrue(is_definitive_edition(data))

    def test_keeps_malformed_bytes_unknown(self):
        result = detect_scenario_edition(b"bad")

        self.assertEqual(ScenarioEdition.UNKNOWN, result.edition)
        self.assertFalse(is_definitive_edition(b"bad"))


class TestScenarioParsing(TestCase):
    def test_parse_scenario_dispatches_legacy_parser(self):
        data = _build_detection_fixture(b"1.21", 1.14)
        legacy_result = object()

        with patch(
            "AoE2ScenarioParser.scenario_parsing.LegacyScenario.read_from_bytes",
            return_value=legacy_result,
        ) as mock_legacy:
            parsed = parse_scenario(data)

        mock_legacy.assert_called_once_with(data)
        self.assertEqual(ScenarioEdition.LEGACY, parsed.edition)
        self.assertIs(legacy_result, parsed.scenario)

    def test_parse_scenario_dispatches_de_parser_from_path(self):
        data = _build_detection_fixture(b"1.21", 1.30)
        de_result = object()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".aoe2scenario") as tmp:
            tmp.write(data)
            tmp.flush()
            path = Path(tmp.name)

        try:
            with patch(
                "AoE2ScenarioParser.scenario_parsing.AoE2DEScenario.from_file",
                return_value=de_result,
            ) as mock_de:
                parsed = parse_scenario(path, suppress_output=True)

            mock_de.assert_called_once()
            self.assertEqual(str(path), mock_de.call_args[0][0])
            self.assertEqual(ScenarioEdition.DEFINITIVE, parsed.edition)
            self.assertIs(de_result, parsed.scenario)
        finally:
            path.unlink(missing_ok=True)

    def test_parse_scenario_dispatches_de_parser_from_bytes(self):
        data = _build_detection_fixture(b"1.21", 1.30)
        de_result = object()

        with patch(
            "AoE2ScenarioParser.scenario_parsing.AoE2DEScenario.from_file",
            return_value=de_result,
        ) as mock_de:
            parsed = parse_scenario(data, suppress_output=True)

        mock_de.assert_called_once()
        self.assertEqual(ScenarioEdition.DEFINITIVE, parsed.edition)
        self.assertIs(de_result, parsed.scenario)

    def test_verify_scenario_exposes_legacy_metadata(self):
        data = _build_detection_fixture(b"1.21", 1.14)
        legacy_result = object()

        with patch(
            "AoE2ScenarioParser.scenario_parsing.LegacyScenario.read_from_bytes",
            return_value=legacy_result,
        ):
            parsed = verify_scenario(data)

        self.assertEqual(ScenarioEdition.LEGACY, parsed.edition)
        self.assertEqual("aoe2_mcgeniescx.Scenario", parsed.parse_backend)
        self.assertEqual("legacy", parsed.game_version)
        self.assertEqual("1.14", parsed.scenario_version)

    def test_verify_scenario_exposes_de_metadata(self):
        data = _build_detection_fixture(b"1.21", 1.30)

        class _DeScenarioStub:
            game_version = "DE"
            scenario_version = "1.57"

        with patch(
            "AoE2ScenarioParser.scenario_parsing.AoE2DEScenario.from_file",
            return_value=_DeScenarioStub(),
        ):
            parsed = verify_scenario(data, suppress_output=True)

        self.assertEqual(ScenarioEdition.DEFINITIVE, parsed.edition)
        self.assertEqual("AoE2DEScenario", parsed.parse_backend)
        self.assertEqual("DE", parsed.game_version)
        self.assertEqual("1.57", parsed.scenario_version)
