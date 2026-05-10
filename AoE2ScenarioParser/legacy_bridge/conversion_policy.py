"""
Pinned defaults and non-genie norms for legacy → DE conversion.

Genie-sourced fields stay in :mod:`AoE2ScenarioParser.legacy_bridge.bridge_mapping`.
Everything **intentionally** forced to a fixed value for rebuilt scenarios lives here so it is
grep-able and reviewable in one place.

See ``CONVERSION_POLICY.md`` in this directory for the audit table.
"""

from __future__ import annotations

from typing import Any

from AoE2ScenarioParser.helper.printers import warn
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario

# --- Triggers section ---------------------------------------------------------

# DE-resaved workbench references use 0; keeps rebuilt files aligned with editor-resaved refs.
PINNED_TRIGGER_INSTRUCTION_START: int = 0

# AoK/AoC evaluation order; DE exposes ``Triggers.legacy_exec_order`` (u8). Editor-resaved refs use 1;
# ``AoE2DEScenario.from_default()`` leaves 0.
LEGACY_TRIGGERS_SECTION_EXEC_ORDER: int = 1

# --- OptionManager ↔ Map (since 1.37 / 1.42) ---------------------------------

# Legacy SCX bits do not match DE-resaved defaults for these; pin DE norms so rebuilt files match
# opened-and-saved references (commits flow through ``OptionManager``).
PINNED_VILLAGER_FORCE_DROP: bool = True
PINNED_LOCK_COOP_ALLIANCES: bool = False
PINNED_SECONDARY_GAME_MODES: int = 0


def pin_trigger_instruction_start(triggers_section: Any) -> None:
    """
    Set ``Triggers.trigger_instruction_start`` to :data:`PINNED_TRIGGER_INSTRUCTION_START`.

    Called only when legacy triggers are being mapped (same as prior inline behavior).
    Failures are ignored so conversion can proceed (matches previous silent ``except``).
    """
    try:
        triggers_section.trigger_instruction_start = PINNED_TRIGGER_INSTRUCTION_START
    except Exception:
        pass


def pin_legacy_trigger_execution_order(scenario: AoE2DEScenario) -> None:
    """Enable AoK/AoC-style trigger evaluation for converted scenarios."""
    try:
        scenario.sections["Triggers"].legacy_exec_order = LEGACY_TRIGGERS_SECTION_EXEC_ORDER
        scenario.option_manager.legacy_execution_order = True
    except Exception as e:
        warn(f"Unable to set legacy trigger execution order (Triggers.legacy_exec_order): {e}")


def pin_option_manager_de_map_norms(scenario: AoE2DEScenario) -> None:
    """Pin villager force-drop, coop alliances lock, and secondary game modes to DE map norms."""
    try:
        om = scenario.option_manager
        om.villager_force_drop = PINNED_VILLAGER_FORCE_DROP
        om.lock_coop_alliances = PINNED_LOCK_COOP_ALLIANCES
        om.secondary_game_modes = PINNED_SECONDARY_GAME_MODES
    except Exception as e:
        warn(
            "Unable to set DE Map option defaults "
            "(villager_force_drop / lock_coop_alliances / secondary_game_modes): "
            f"{e}"
        )