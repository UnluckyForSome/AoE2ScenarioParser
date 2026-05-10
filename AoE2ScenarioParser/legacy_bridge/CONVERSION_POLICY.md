# Legacy bridge conversion policy

Intentional **non-genie** values applied during `apply_legacy_scenario_to_de_scenario` live in
`conversion_policy.py`. Genie-sourced mappings stay in `bridge_mapping.py`.

## Pinned fields

| Area | Target | Constant / value | Rationale |
|------|--------|------------------|-----------|
| Triggers | `trigger_instruction_start` | `PINNED_TRIGGER_INSTRUCTION_START` (0) | Match DE editor–resaved workbench references. Only applied when legacy trigger payload is mapped. |
| Triggers | `legacy_exec_order` | `LEGACY_TRIGGERS_SECTION_EXEC_ORDER` (1) | AoK/AoC trigger evaluation order; `from_default()` uses 0. |
| OptionManager | `legacy_execution_order` | `True` (with row above) | Same semantics as `legacy_exec_order`, exposed on the manager. |
| OptionManager | `villager_force_drop` | `PINNED_VILLAGER_FORCE_DROP` (True) | Legacy SCX bits ≠ DE-resaved defaults; pin DE map norms. |
| OptionManager | `lock_coop_alliances` | `PINNED_LOCK_COOP_ALLIANCES` (False) | Same. |
| OptionManager | `secondary_game_modes` | `PINNED_SECONDARY_GAME_MODES` (0) | Same. |

## Not listed here

- **`Triggers.trigger_version`**: left at `AoE2DEScenario.from_default()` (modern DE layout).
- **Per-trigger / condition / effect fields**: built from genie `properties[]`, with dataset defaults for unknown slots.
- **Tribe/options fields**: copied from genie when present; otherwise DE defaults remain.

## Changing policy

1. Edit constants and/or functions in `conversion_policy.py`.
2. Update this table if behavior or rationale changes.
3. Run `tests/legacy_bridge/test_conversion_policy.py` after edits.
