"""Regression guard for pinned legacy→DE conversion defaults."""

from AoE2ScenarioParser.legacy_bridge.conversion_policy import (
    LEGACY_TRIGGERS_SECTION_EXEC_ORDER,
    PINNED_LOCK_COOP_ALLIANCES,
    PINNED_SECONDARY_GAME_MODES,
    PINNED_TRIGGER_INSTRUCTION_START,
    PINNED_VILLAGER_FORCE_DROP,
    pin_legacy_trigger_execution_order,
    pin_option_manager_de_map_norms,
    pin_trigger_instruction_start,
)
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario


def test_pinned_values_match_policy_constants():
    scenario = AoE2DEScenario.from_default()

    pin_legacy_trigger_execution_order(scenario)
    assert scenario.sections["Triggers"].legacy_exec_order == LEGACY_TRIGGERS_SECTION_EXEC_ORDER
    assert scenario.option_manager.legacy_execution_order is True

    pin_option_manager_de_map_norms(scenario)
    assert scenario.option_manager.villager_force_drop == PINNED_VILLAGER_FORCE_DROP
    assert scenario.option_manager.lock_coop_alliances == PINNED_LOCK_COOP_ALLIANCES
    assert int(scenario.option_manager.secondary_game_modes) == PINNED_SECONDARY_GAME_MODES

    trig = scenario.sections["Triggers"]
    pin_trigger_instruction_start(trig)
    assert trig.trigger_instruction_start == PINNED_TRIGGER_INSTRUCTION_START
