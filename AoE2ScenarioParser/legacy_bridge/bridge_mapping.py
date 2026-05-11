from __future__ import annotations

import re

"""
Legacy scenario (`aoe2_mcgeniescx.Scenario`) → DE ``AoE2DEScenario`` mapping.

This file is intentionally a *mapping specification* first:
explicit field-by-field transformation, heavily documented, and easy to audit.

Data flow
---------

1. **Parse legacy**: `aoe2_mcgeniescx.Scenario` reads legacy ``.scn`` / ``.scx`` into Python objects.
2. **Wireup**: `legacy_bridge/bridge_wireup.py` constructs ``AoE2DEScenario.from_default()``.
3. **This module**: :func:`apply_legacy_scenario_to_de_scenario` copies fields onto the DE scenario.

4. **Pinned non-genie defaults** (triggers / option manager): :mod:`AoE2ScenarioParser.legacy_bridge.conversion_policy`
   and ``legacy_bridge/CONVERSION_POLICY.md``.

Conversion is **best-effort**: preserve clean mappings, keep DE defaults when unclear, ``warn()`` instead of crashing.

Mapping block format (guideline)
--------------------------------

As this refactor proceeds, sections are rewritten into explicit blocks like:

    # ============================================================
    # FIELD: trigger.display_timer
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: Effect.display_time
    # Processing:
    #   display_timer = display_time / 1000
    # Output:
    #   AoE2ScenarioParser.objects.data_objects.trigger.Trigger.display_timer
"""

import struct
from typing import Any, Dict, List

from AoE2ScenarioParser.helper.printers import warn
from AoE2ScenarioParser.legacy_bridge.conversion_policy import (
    pin_legacy_trigger_execution_order,
    pin_option_manager_de_map_norms,
    pin_trigger_instruction_start,
)
from AoE2ScenarioParser.objects.data_objects.effect import Effect
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario
from AoE2ScenarioParser.sections.aoe2_file_section import AoE2FileSection


class _BridgeMappedEffect(Effect):
    """Bridge-only ``Effect`` that matches DE resave for genie ``properties[5]`` object refs.

    Stock ``Effect`` copies a valid ``legacy_location_object_reference`` into ``location_object_reference`` and
    exposes legacy as ``-1`` for serialization. DE-resaved scenarios keep the id in the legacy slot with
    ``location_object_reference`` cleared.
    """

    def __init__(self, **kwargs):
        legacy_src = kwargs.get("legacy_location_object_reference")
        adjusted = dict(kwargs)
        adjusted["legacy_location_object_reference"] = -1
        super().__init__(**adjusted)
        leg = -1 if legacy_src is None else int(legacy_src)
        self._bridge_legacy_location_object_reference = leg

    @property  # type: ignore[misc]
    def legacy_location_object_reference(self) -> int:
        return getattr(self, "_bridge_legacy_location_object_reference", -1)

    @legacy_location_object_reference.setter
    def legacy_location_object_reference(self, value):
        self._bridge_legacy_location_object_reference = -1 if value is None else int(value)


# --- Helpers: embedded AI, floats, diplomacy --------------------------------


def _ai_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _files_ai_fallback_from_slots(names_in: List[Any], scripts_in: List[Any]) -> List[Dict[str, str]]:
    """
    When ``AIInfo.files`` is empty, still emit ``Files.ai_files`` rows for distinct RGEScen slot filenames
    that carry script text (mirrors how embedded AI lists campaign ``.per`` chunks).
    """
    out: List[Dict[str, str]] = []
    seen_fn: set[str] = set()
    for i in range(16):
        sc = scripts_in[i] if i < len(scripts_in) else None
        if not _ai_str(sc).strip():
            continue
        nm = names_in[i] if i < len(names_in) else None
        fn = _ai_str(nm).strip() or f"legacy_ai_{i}.per"
        if fn in seen_fn:
            continue
        seen_fn.add(fn)
        out.append({"filename": fn, "content": _ai_str(sc)})
    return out


def _apply_legacy_ai_embedded(scen: Any, scenario: AoE2DEScenario) -> None:
    """Map RGEScen per-player AI + AIInfo embedded files into DE ``PlayerDataTwo`` and ``Files``."""
    try:
        tribe = scen.format.tribe_scen
    except Exception:
        return

    try:
        names_in = list(tribe.legacy_ai_filenames())
        scripts_in = list(tribe.legacy_ai_script_contents())
        types_in = list(tribe.legacy_ai_rules_types())
    except Exception:
        names_in = []
        scripts_in = []
        types_in = []

    ai_info = None
    try:
        ai_info = scen.format.ai_info
    except Exception:
        ai_info = None

    embedded: List[Dict[str, str]] = []
    if ai_info is not None:
        embedded = [{"filename": f.filename, "content": f.content} for f in ai_info.files]

    files_payload = embedded if embedded else _files_ai_fallback_from_slots(names_in, scripts_in)

    try:
        pd2 = scenario.sections["PlayerDataTwo"]
        ai_names = list(pd2.ai_names)
        ai_type = list(pd2.ai_type)
        for i in range(16):
            nm = names_in[i] if i < len(names_in) else None
            ai_names[i] = _ai_str(nm)
            sc = scripts_in[i] if i < len(scripts_in) else None
            pd2.ai_files[i].ai_per_file_text = _ai_str(sc)
            ty = types_in[i] if i < len(types_in) else 1
            try:
                ai_type[i] = max(0, min(255, int(ty))) & 0xFF
            except (TypeError, ValueError):
                ai_type[i] = 1
        pd2.ai_names = ai_names
        pd2.ai_type = ai_type

        for pid in range(1, 9):
            pl = scenario.player_manager.players[pid]
            pl.personality = ai_names[pid - 1]
            pl.ai_script = pd2.ai_files[pid - 1].ai_per_file_text
            pl.ai_type = ai_type[pid - 1]
        gaia_pl = scenario.player_manager.players[0]
        gaia_pl.personality = ai_names[8]
        gaia_pl.ai_script = pd2.ai_files[8].ai_per_file_text
        gaia_pl.ai_type = ai_type[8]

        fs = scenario.sections["Files"]
        ai2_model = fs.find_struct_model_by_retriever(fs.retriever_map["ai_files"])
        entries: List[AoE2FileSection] = []
        for item in files_payload:
            if not isinstance(item, dict):
                continue
            sec = AoE2FileSection.from_model(ai2_model, scenario.uuid, set_defaults=True)
            sec.ai_file_name = _ai_str(item.get("filename"))
            sec.ai_file = _ai_str(item.get("content"))
            entries.append(sec)
        fs.ai_files = entries
        fs.number_of_ai_files = int(len(entries))
        fs.ai_files_present = 1 if entries else 0

        # Legacy AIInfo optional compiler diagnostic — maps to DE ``Files.ai_error`` (struct AIError).
        legacy_err = getattr(ai_info, "error", None) if ai_info is not None else None
        if legacy_err is not None:
            err_model = fs.find_struct_model_by_retriever(fs.retriever_map["ai_error"])
            err_sec = AoE2FileSection.from_model(err_model, scenario.uuid, set_defaults=True)
            err_sec.ai_file = _ai_str(getattr(legacy_err, "filename", ""))[:259]
            err_sec.line_number = int(getattr(legacy_err, "line_number", 0))
            err_sec.message = _ai_str(getattr(legacy_err, "description", ""))[:127]
            try:
                err_sec.error_code = int(getattr(legacy_err, "error_code", 0))
            except (TypeError, ValueError):
                err_sec.error_code = 0
            fs.ai_error_present = 1
            fs.ai_error = [err_sec]
        else:
            fs.ai_error_present = 0
            fs.ai_error = []
    except Exception as e:
        warn(f"Unable to map legacy AI scripts into Files / PlayerDataTwo: {e}")


def _f32_roundtrip(x: float) -> float:
    """Round through IEEE-754 binary32 like DE scenario I/O so floats match retail `.aoe2scenario`."""
    return float(struct.unpack("<f", struct.pack("<f", float(x)))[0])


def _pad_diplomacy(relations: List[int], *, pad_to: int = 16, fill: int = 3) -> List[int]:
    # Legacy relations are typically per-other-player stances.
    # AoE2ScenarioParser expects a 16-length array for `stance_with_each_player`.
    rel = [int(x) for x in relations]
    if len(rel) >= pad_to:
        return rel[:pad_to]
    return rel + [fill] * (pad_to - len(rel))


def _normalize_trigger_text(s: str) -> str:
    """
    Normalize legacy-exported trigger text to match how DE scenario strings are commonly encoded/decoded.

    AoE2ScenarioParser decodes scenario text using a single-byte codec; DE-resaved files sometimes contain
    Windows-1252 control-code ellipsis (0x85) rather than Unicode '…'. To reduce diff noise, map '…' -> '\\x85'.
    """
    if not s:
        return ""
    return s.replace("…", "\x85")


def apply_legacy_scenario_to_de_scenario(scen: Any, scenario: AoE2DEScenario) -> None:
    """
    Apply legacy `aoe2_mcgeniescx.Scenario` data onto ``scenario`` (see module docstring for philosophy and unmapped
    fields).
    """

    # ============================================================
    # FIELD: FileHeader.creator_name
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.author_name
    #
    # Explanation:
    # DE uses this for metadata only. We prefer the legacy author when present, otherwise stamp conversion.
    #
    # Processing:
    #   creator_name = author_name or "AoE2ScenarioParser (legacy conversion)"
    #
    # Output:
    #   scenario.sections["FileHeader"].creator_name

    # ============================================================
    # FIELD: FileHeader.scenario_instructions (short header preview)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.description
    #
    # Explanation:
    # This is a fixed-width header field (str32). It is *not* the DE string-table backed instructions.
    # We store a short preview for debugging/traceability.
    #
    # Processing:
    #   scenario_instructions = description[:32]
    #
    # Output:
    #   scenario.sections["FileHeader"].scenario_instructions

    # ============================================================
    # FIELD: FileHeader.player_count
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.active_player_count
    #
    # Explanation:
    # Header player_count influences some editor UI assumptions. Keep it when exported.
    #
    # Output:
    #   scenario.sections["FileHeader"].player_count

    # ============================================================
    # FIELD: DataHeader.filename
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.filename
    #
    # Explanation:
    # Used as a file-internal name. Helpful during debugging; `write_to_file` may override anyway.
    #
    # Output:
    #   scenario.sections["DataHeader"].filename

    try:
        header = scen.format.header
        description = getattr(header, "description", "") or ""
        author_name = getattr(header, "author_name", None)
        active_player_count = getattr(header, "active_player_count", None)
    except Exception:
        description = ""
        author_name = None
        active_player_count = None

    try:
        filename = scen.filename()
    except Exception:
        filename = None

    try:
        tribe = scen.format.tribe_scen
    except Exception:
        tribe = None

    try:
        scenario.sections["FileHeader"].creator_name = author_name or "AoE2ScenarioParser (legacy conversion)"
        # Keep a short preview in the header field (str32 constraint). This is NOT string-table backed.
        scenario.sections["FileHeader"].scenario_instructions = description[:32]
        if active_player_count:
            scenario.sections["FileHeader"].player_count = int(active_player_count)
    except Exception as e:
        warn(f"Unable to map FileHeader metadata: {e}")

    try:
        # Used by AoE2Scenario.write_to_file() internal hook to set it anyway, but it helps debugging.
        if filename:
            scenario.sections["DataHeader"].filename = filename
    except Exception as e:
        warn(f"Unable to map DataHeader.filename: {e}")

    # ============================================================
    # FIELD: Messages.ascii_* + Cinematics.ascii_* (long-form scenario text)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.description
    #
    # Source (preferred when present):
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.raw.options.rge_messages
    #
    # Explanation:
    # DE stores long-form scenario text in the Messages/Cinematics sections. String-table IDs do not
    # round-trip cleanly across legacy↔DE. We therefore keep text in the `ascii_*` fields and force
    # string-table-backed IDs to the "unset" sentinel.
    #
    # Outputs:
    #   scenario.sections["Messages"].ascii_instructions / ascii_hints / ascii_victory / ...
    #   scenario.sections["Cinematics"].ascii_pregame / ascii_victory / ascii_loss

    # Legacy `description` maps closest to DE "instructions".
    # Prefer RGEScen's `description` when present; DE-resaved scenarios tend to use that.
    try:
        msg_section = scenario.sections["Messages"]
        msg_section.ascii_instructions = description
        # Disregard any legacy string-table IDs: DE string table IDs differ.
        # Keep text in ascii_* only.
        msg_section.instructions = 4294967294
        msg_section.hints = 4294967294
        msg_section.victory = 4294967294
        msg_section.loss = 4294967294
        msg_section.history = 4294967294
        msg_section.scouts = 4294967294
    except Exception as e:
        warn(f"Unable to map Messages.ascii_instructions: {e}")

    # Additional legacy message blocks (hints/victory/loss/history/scouts) and cinematics are exported
    # via `TribeScen.base` when present.
    try:
        if tribe is not None:
            msg = scenario.sections["Messages"]
            cin = scenario.sections["Cinematics"]
            base = tribe.base

            if getattr(base, "description", None):
                msg.ascii_instructions = str(base.description)
            if getattr(base, "hints", None):
                msg.ascii_hints = str(base.hints)
            if getattr(base, "win_message", None):
                msg.ascii_victory = str(base.win_message)
            if getattr(base, "loss_message", None):
                msg.ascii_loss = str(base.loss_message)
            if getattr(base, "history", None):
                msg.ascii_history = str(base.history)
            if getattr(base, "scout", None):
                msg.ascii_scouts = str(base.scout)

            if getattr(base, "pregame_cinematic", None):
                cin.ascii_pregame = str(base.pregame_cinematic)
            if getattr(base, "victory_cinematic", None):
                cin.ascii_victory = str(base.victory_cinematic)
            if getattr(base, "loss_cinematic", None):
                cin.ascii_loss = str(base.loss_cinematic)

            # Player names / civs / types from RGEScen (used by DE to populate player metadata).
            # Later ``scenario_players`` may fill ``tribe_name`` only when still empty (RGEScen wins).
            try:
                player_names = list(getattr(base, "player_names", []) or [])
                if len(player_names) >= 16:
                    for pid in range(1, 17):
                        name = str(player_names[pid - 1] or "")
                        if name:
                            scenario.player_manager.players[pid].tribe_name = name

                base_props = list(getattr(base, "player_base_properties", []) or [])
                if base_props:
                    from AoE2ScenarioParser.datasets.object_support import Civilization, CivilizationOld

                    by_pid = {int(i + 1): p for i, p in enumerate(base_props[:16])}
                    for pid in range(1, 17):
                        bp = by_pid.get(pid)
                        if bp is None:
                            continue
                        pd1 = scenario.sections["DataHeader"].player_data_1[pid - 1]

                        civ = getattr(bp, "civilization", None)
                        if civ is not None:
                            civ_id = int(civ)
                            try:
                                civ_name = CivilizationOld(civ_id).name
                                civ_key = Civilization[civ_name].value
                            except Exception:
                                civ_key = "RANDOM-CIV"
                            pd1.civilization = civ_key
                            pd1.architecture_set = civ_key

                        ptype = getattr(bp, "player_type", None)
                        if ptype is not None:
                            pd1.human = 1 if int(ptype) == 1 else 0
            except Exception as e:
                warn(f"Unable to map RGEScen player names/civs/types: {e}")
    except Exception as e:
        warn(f"Unable to map legacy hints/victory/loss/history/scouts/cinematics: {e}")

    # ============================================================
    # FIELD: DataHeader.string_table_player_names + Player.string_table_name_id
    # ============================================================
    # Source:
    # SOURCE TYPE: SYNTHETIC
    #
    # Explanation:
    # Legacy string-table IDs do not match DE references. Force the DE sentinel for “no string table name”.
    #
    # Output:
    #   scenario.sections["DataHeader"].string_table_player_names
    #   scenario.player_manager.players[pid].string_table_name_id

    try:
        # `string_table_player_names` is `s32` in DE structure; use -2 sentinel (not u32 4294967294).
        scenario.sections["DataHeader"].string_table_player_names = [-2] * 16
        players = scenario.player_manager.players
        max_pid = 16
        try:
            if hasattr(players, "__len__"):
                # Typical AoE2ScenarioParser: list-like with indices 0..16.
                max_pid = min(16, max(0, len(players) - 1))
        except Exception:
            max_pid = 16
        for pid in range(1, max_pid + 1):
            players[pid].string_table_name_id = -2
    except Exception as e:
        warn(f"Unable to clear string_table player name IDs: {e}")

    # ============================================================
    # FIELD: Triggers.trigger_data + trigger_display_order + variables
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.triggers (type IDs + properties arrays + ordering arrays)
    #
    # Explanation:
    # The DE trigger binary layout is versioned and sensitive. We keep DE's default trigger system version
    # (from `AoE2DEScenario.from_default()`), then populate Trigger/Condition/Effect objects from the
    # low-level legacy `properties[]` arrays.
    #
    # Key policies:
    # - **Version-gated fields**: only seed attributes supported by `scenario.scenario_version`.
    # - **String-table IDs**: prefer 0/-1 safe defaults; do not attempt to preserve legacy string IDs.
    #
    # Outputs:
    #   scenario.trigger_manager.triggers / variables / trigger_display_order

    trig_sys = None
    try:
        trig_sys = scen.triggers()
    except Exception:
        trig_sys = None

    if trig_sys is not None and getattr(trig_sys, "triggers", None):
        try:
            from AoE2ScenarioParser.objects.data_objects.condition import Condition
            from AoE2ScenarioParser.objects.data_objects.trigger import Trigger
            from AoE2ScenarioParser.objects.data_objects.variable import Variable
            from AoE2ScenarioParser.datasets import conditions as condition_dataset
            from AoE2ScenarioParser.datasets import effects as effect_dataset
            from AoE2ScenarioParser.objects.managers.trigger_manager import get_trigger_referencing_ce
            # NOTE: Trigger component fields can be version-gated with Support(since=...).
            # We filter seeded defaults using that metadata so conversion doesn't break
            # when datasets include fields newer than this repo's AoE2DEScenario.LATEST_VERSION.

            def _filter_supported_trigger_component_kwargs(obj_cls, *, scenario_version: str, kwargs: dict) -> dict:
                """
                Return a copy of kwargs with any version-unsupported fields removed.

                Uses the `Support(since=...)` metadata from RetrieverObjectLink definitions on the object.
                """
                try:
                    group = obj_cls._link_list[0]
                    links = getattr(group, "group", None) or []
                except Exception:
                    return kwargs

                supported: set[str] = set()
                for link in links:
                    name = getattr(link, "name", None)
                    if not name:
                        continue
                    support = getattr(link, "support", None)
                    if support is None or support.supports(scenario_version):
                        supported.add(name)

                # Only pass through names that are actually fields on this version.
                return {k: v for k, v in kwargs.items() if k in supported}

            trig_section = scenario.sections["Triggers"]

            # ============================================================
            # FIELD: Triggers.trigger_version
            # ============================================================
            # Source:
            # SOURCE TYPE: DE_DEFAULT
            #
            # Explanation:
            # Always write triggers using a modern DE trigger system version. Downgrading to a legacy version
            # can corrupt subsequent reads because the binary layout differs.
            #
            # Output:
            #   scenario.sections["Triggers"].trigger_version (kept as DE default)

            _ = getattr(trig_sys, "version", None)

            # FIELD: Triggers.trigger_instruction_start → :func:`conversion_policy.pin_trigger_instruction_start`
            pin_trigger_instruction_start(trig_section)

            tm = scenario.trigger_manager

            # Variables (names only): DE stores variable ID + name. Values are not currently mapped.
            variables: list[Variable] = []
            try:
                for var_id, nm in enumerate(getattr(trig_sys, "variable_names", []) or []):
                    if nm:
                        variables.append(Variable(variable_id=int(var_id), name=str(nm), uuid=tm._uuid))
            except Exception:
                variables = []
            tm.variables = variables

            new_triggers: list[Trigger] = []
            ordered_triggers = (
                [trig_sys.triggers[i] for i in trig_sys.trigger_order]
                if getattr(trig_sys, "trigger_order", None)
                else list(trig_sys.triggers)
            )
            for idx, t in enumerate(ordered_triggers):

                # ============================================================
                # FIELD: Trigger header fields (name/objective/enabled/looping/etc.)
                # ============================================================
                # Source:
                # SOURCE TYPE: GENIE_SCX_PY
                # genie-scx: payload.triggers.triggers[*]
                #
                # Explanation:
                # Trigger header attributes map fairly directly. We intentionally do **not** preserve
                # legacy string-table IDs and instead use safe defaults for DE.
                #
                # Output:
                #   AoE2ScenarioParser.objects.data_objects.trigger.Trigger

                name = getattr(t, "name", None) or f"Trigger {idx}"
                desc = getattr(t, "description", None) or ""
                short_desc = getattr(t, "short_description", None) or ""

                trig = Trigger(
                    name=str(name),
                    description=str(desc),
                    # Some DE builds appear to be sensitive to -1 string table IDs in triggers.
                    # Use 0 (no string-table entry) as a safer default for legacy conversions.
                    description_stid=0,
                    short_description=str(short_desc),
                    short_description_stid=0,
                    display_as_objective=int(bool(getattr(t, "is_objective", False))),
                    description_order=int(getattr(t, "objective_order", 0) or 0),
                    enabled=int(bool(getattr(t, "enabled", True))),
                    looping=int(bool(getattr(t, "looping", False))),
                    header=int(bool(getattr(t, "make_header", False))),
                    mute_objectives=int(bool(getattr(t, "mute_objective", False))),
                    conditions=[],
                    effects=[],
                    # Legacy exports carry a stable trigger index; DE resaves keep trigger IDs stable even if
                    # internal storage order changes. Use the legacy index when present so effect/condition
                    # cross-references (`trigger_id`) line up with DE-resaved references.
                    trigger_id=int(idx),
                    uuid=tm._uuid,
                )

                # ============================================================
                # FIELD: Trigger.conditions[*]
                # ============================================================
                # Source:
                # SOURCE TYPE: GENIE_SCX_PY
                # genie-scx: trigger.conditions[*].properties[]
                #
                # Explanation:
                # Legacy exports provide numeric `properties[]` arrays. We map known indices to DE Condition
                # fields, and seed DE-only fields with dataset “empty” defaults when absent in legacy.
                #
                # Output:
                #   Trigger.conditions (AoE2ScenarioParser.objects.data_objects.condition.Condition)

                conds_iter = (
                    [t.conditions[j] for j in t.condition_order]
                    if getattr(t, "condition_order", None)
                    else (getattr(t, "conditions", []) or [])
                )
                for c in conds_iter:
                    props = list(getattr(c, "properties", []) or [])
                    props = [int(x) for x in (props + [-1] * 32)][:32]
                    ctype = int(getattr(c, "condition_type", 0) or 0)
                    cond_defaults = {
                        **condition_dataset.default_attributes.get(0, {}),
                        **condition_dataset.default_attributes.get(ctype, {}),
                    }
                    # genie-scx exports legacy trigger condition "properties" in a stable order that matches
                    # the AoK/AoC-era trigger system, not necessarily the newest DE struct field order.
                    # Map only the known legacy slots, and keep the rest at DE-resaved empties (-1/"").
                    # ============================================================
                    # FIELD: Condition.condition_type
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.condition_type
                    #
                    # Output:
                    #   AoE2ScenarioParser.objects.data_objects.condition.Condition.condition_type
                    condition_type = ctype

                    # ============================================================
                    # FIELD: Condition.quantity
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[0]
                    quantity = props[0]

                    # ============================================================
                    # FIELD: Condition.attribute
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[1]
                    attribute = props[1]

                    # ============================================================
                    # FIELD: Condition.unit_object
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[2]
                    unit_object = props[2]

                    # ============================================================
                    # FIELD: Condition.next_object
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[3]
                    next_object = props[3]

                    # ============================================================
                    # FIELD: Condition.object_list
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[4]
                    object_list = props[4]

                    # ============================================================
                    # FIELD: Condition.source_player
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[5]
                    source_player = props[5]

                    # ============================================================
                    # FIELD: Condition.technology
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[6]
                    technology = props[6]

                    # ============================================================
                    # FIELD: Condition.timer
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[7]
                    timer = props[7]

                    # ============================================================
                    # FIELD: Condition.trigger_id
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[8]
                    #
                    # Explanation:
                    # This DE field exists since 1.54; legacy exports generally do not use it.
                    trigger_id = props[8]

                    # ============================================================
                    # FIELD: Condition.area_x1
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[9]
                    area_x1 = props[9]

                    # ============================================================
                    # FIELD: Condition.area_y1
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[10]
                    area_y1 = props[10]

                    # ============================================================
                    # FIELD: Condition.area_x2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[11]
                    area_x2 = props[11]

                    # ============================================================
                    # FIELD: Condition.area_y2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[12]
                    area_y2 = props[12]

                    # ============================================================
                    # FIELD: Condition.object_group
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[13]
                    object_group = props[13]

                    # ============================================================
                    # FIELD: Condition.object_type
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[14]
                    object_type = props[14]

                    # ============================================================
                    # FIELD: Condition.ai_signal
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[15]
                    ai_signal = props[15]

                    # ============================================================
                    # FIELD: Condition.inverted
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[16]
                    inverted = props[16]

                    # ============================================================
                    # FIELD: Condition.variable
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: condition.properties[17]
                    variable = props[17]

                    # ============================================================
                    # FIELD: Condition.comparison
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    # aoe2scenarioparser dataset: conditions.empty_attributes["comparison"]
                    comparison = condition_dataset.empty_attributes.get("comparison", -1)

                    # ============================================================
                    # FIELD: Condition.target_player
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    target_player = condition_dataset.empty_attributes.get("target_player", -1)

                    # ============================================================
                    # FIELD: Condition.unit_ai_action
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    unit_ai_action = condition_dataset.empty_attributes.get("unit_ai_action", -1)

                    # ============================================================
                    # FIELD: Condition.object_state
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    object_state = condition_dataset.empty_attributes.get("object_state", -1)

                    # ============================================================
                    # FIELD: Condition.timer_id
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    timer_id = condition_dataset.empty_attributes.get("timer_id", -1)

                    # ============================================================
                    # FIELD: Condition.victory_timer_type
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    victory_timer_type = condition_dataset.empty_attributes.get("victory_timer_type", -1)

                    # ============================================================
                    # FIELD: Condition.include_changeable_weapon_objects
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    include_changeable_weapon_objects = condition_dataset.empty_attributes.get(
                        "include_changeable_weapon_objects", -1
                    )

                    # ============================================================
                    # FIELD: Condition.decision_id
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    decision_id = condition_dataset.empty_attributes.get("decision_id", -1)

                    # ============================================================
                    # FIELD: Condition.decision_option
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    decision_option = condition_dataset.empty_attributes.get("decision_option", -1)

                    # ============================================================
                    # FIELD: Condition.variable2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: SYNTHETIC
                    #
                    # Explanation:
                    # Some dataset versions historically typed `variable2` oddly; keep a safe s32 sentinel.
                    variable2 = -1

                    # ============================================================
                    # FIELD: Condition.local_technology
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    local_technology = condition_dataset.empty_attributes.get("local_technology", -1)

                    # ============================================================
                    # FIELD: Condition.object_group2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    object_group2 = condition_dataset.empty_attributes.get("object_group2", -1)

                    # ============================================================
                    # FIELD: Condition.object_type2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    object_type2 = condition_dataset.empty_attributes.get("object_type2", -1)

                    # ============================================================
                    # FIELD: Condition.xs_function
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    xs_function = str(condition_dataset.empty_attributes.get("xs_function", ""))

                    cond_overrides = {
                        "condition_type": condition_type,
                        "quantity": quantity,
                        "attribute": attribute,
                        "unit_object": unit_object,
                        "next_object": next_object,
                        "object_list": object_list,
                        "source_player": source_player,
                        "technology": technology,
                        "timer": timer,
                        "trigger_id": trigger_id,
                        "area_x1": area_x1,
                        "area_y1": area_y1,
                        "area_x2": area_x2,
                        "area_y2": area_y2,
                        "object_group": object_group,
                        "object_type": object_type,
                        "ai_signal": ai_signal,
                        "inverted": inverted,
                        "variable": variable,
                        "comparison": comparison,
                        "target_player": target_player,
                        "unit_ai_action": unit_ai_action,
                        "object_state": object_state,
                        "timer_id": timer_id,
                        "victory_timer_type": victory_timer_type,
                        "include_changeable_weapon_objects": include_changeable_weapon_objects,
                        "decision_id": decision_id,
                        "decision_option": decision_option,
                        "variable2": variable2,
                        "local_technology": local_technology,
                        "object_group2": object_group2,
                        "object_type2": object_type2,
                        "xs_function": xs_function,
                    }
                    cond_kwargs = _filter_supported_trigger_component_kwargs(
                        Condition,
                        scenario_version=scenario.scenario_version,
                        kwargs={**cond_defaults, **cond_overrides},
                    )
                    trig.conditions.append(Condition(**cond_kwargs, uuid=tm._uuid))

                # ============================================================
                # FIELD: Trigger.effects[*]
                # ============================================================
                # Source:
                # SOURCE TYPE: GENIE_SCX_PY
                # genie-scx: trigger.effects[*].properties[]
                #
                # Explanation:
                # Same philosophy as conditions: explicit index→field mapping, plus seeding DE-only fields
                # to dataset “empty” values (version-gated).
                #
                # Output:
                #   Trigger.effects (AoE2ScenarioParser.objects.data_objects.effect.Effect)

                effs_iter = (
                    [t.effects[j] for j in t.effect_order]
                    if getattr(t, "effect_order", None)
                    else (getattr(t, "effects", []) or [])
                )
                for e in effs_iter:
                    props = list(getattr(e, "properties", []) or [])
                    props = [int(x) for x in (props + [-1] * 64)][:64]
                    selected = list(getattr(e, "objects", []) or [])
                    selected_ids = [int(x) for x in selected if isinstance(x, (int, float))]
                    etype = int(getattr(e, "effect_type", 0) or 0)
                    eff_defaults = {
                        **effect_dataset.default_attributes.get(0, {}),
                        **effect_dataset.default_attributes.get(etype, {}),
                    }
                    # Similar to conditions: map known legacy effect property slots only.
                    # ============================================================
                    # FIELD: Effect.effect_type
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.effect_type
                    effect_type = etype

                    # ============================================================
                    # FIELD: Effect.ai_script_goal
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.properties[0]
                    ai_script_goal = props[0]

                    # ============================================================
                    # FIELD: Effect._quantity_int (raw integer quantity slot)
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.properties[1]
                    _quantity_int = props[1]

                    # ============================================================
                    # FIELD: Effect.tribute_list
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.properties[2]
                    tribute_list = props[2]

                    # ============================================================
                    # FIELD: Effect.diplomacy
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.properties[3]
                    diplomacy = props[3]

                    # ============================================================
                    # FIELD: Effect.legacy_location_object_reference
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.properties[5]
                    legacy_location_object_reference = props[5]

                    # ============================================================
                    # FIELD: Effect.location_object_reference
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    #
                    # Explanation:
                    # For these legacy-derived effects, DE-resaved references often keep this unused.
                    location_object_reference = -1

                    # ============================================================
                    # FIELD: Effect.object_list_unit_id
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.properties[6]
                    object_list_unit_id = props[6]

                    # ============================================================
                    # FIELD: Effect.source_player
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    source_player = props[7]

                    # ============================================================
                    # FIELD: Effect.target_player
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    target_player = props[8]

                    # ============================================================
                    # FIELD: Effect.technology
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    technology = props[9]

                    # ============================================================
                    # FIELD: Effect.string_id
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: SYNTHETIC
                    #
                    # Explanation:
                    # Disregard legacy string-table IDs; keep `message` / `sound_name` text instead.
                    string_id = -1

                    # ============================================================
                    # FIELD: Effect.display_time
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    display_time = props[12]

                    # ============================================================
                    # FIELD: Effect.trigger_id
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    trigger_id = props[13]

                    # ============================================================
                    # FIELD: Effect.location_x / location_y
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    location_x = props[14]
                    location_y = props[15]

                    # ============================================================
                    # FIELD: Effect.area_x1/area_y1/area_x2/area_y2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    area_x1 = props[16]
                    area_y1 = props[17]
                    area_x2 = props[18]
                    area_y2 = props[19]

                    # ============================================================
                    # FIELD: Effect.object_group / object_type
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    object_group = props[20]
                    object_type = props[21]

                    # ============================================================
                    # FIELD: Effect.instruction_panel_position
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    instruction_panel_position = props[22]

                    # ============================================================
                    # FIELD: Effect.attack_stance
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    attack_stance = props[23]

                    # ============================================================
                    # FIELD: Effect.enabled
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    enabled = effect_dataset.empty_attributes.get("enabled", -1)

                    # ============================================================
                    # FIELD: Effect.food / wood / stone / gold
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    food = effect_dataset.empty_attributes.get("food", -1)
                    wood = effect_dataset.empty_attributes.get("wood", -1)
                    stone = effect_dataset.empty_attributes.get("stone", -1)
                    gold = effect_dataset.empty_attributes.get("gold", -1)

                    # ============================================================
                    # FIELD: Effect._item_id (raw serialized item_id)
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    _item_id = effect_dataset.empty_attributes.get("item_id", -1)

                    # ============================================================
                    # FIELD: Effect.flash_object
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    flash_object = effect_dataset.empty_attributes.get("flash_object", -1)

                    # ============================================================
                    # FIELD: Effect.force_research_technology
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    force_research_technology = effect_dataset.empty_attributes.get("force_research_technology", -1)

                    # ============================================================
                    # FIELD: Effect.visibility_state
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    visibility_state = effect_dataset.empty_attributes.get("visibility_state", -1)

                    # ============================================================
                    # FIELD: Effect.scroll
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    scroll = effect_dataset.empty_attributes.get("scroll", -1)

                    # ============================================================
                    # FIELD: Effect.operation
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    operation = effect_dataset.empty_attributes.get("operation", -1)

                    # ============================================================
                    # FIELD: Effect.object_list_unit_id_2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    object_list_unit_id_2 = effect_dataset.empty_attributes.get("object_list_unit_id_2", -1)

                    # ============================================================
                    # FIELD: Effect.button_location
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    button_location = effect_dataset.empty_attributes.get("button_location", -1)

                    # ============================================================
                    # FIELD: Effect.ai_signal_value
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    ai_signal_value = effect_dataset.empty_attributes.get("ai_signal_value", -1)

                    # ============================================================
                    # FIELD: Effect.object_attributes
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    object_attributes = effect_dataset.empty_attributes.get("object_attributes", -1)

                    # ============================================================
                    # FIELD: Effect._variable_ref (raw variable reference slot)
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    _variable_ref = effect_dataset.empty_attributes.get("variable", -1)

                    # ============================================================
                    # FIELD: Effect.timer
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    timer = effect_dataset.empty_attributes.get("timer", -1)

                    # ============================================================
                    # FIELD: Effect.facet / facet2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT / SYNTHETIC
                    facet = effect_dataset.empty_attributes.get("facet", -1)
                    facet2 = -3

                    # ============================================================
                    # FIELD: Effect.play_sound
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    play_sound = effect_dataset.empty_attributes.get("play_sound", -1)

                    # ============================================================
                    # FIELD: Effect.player_color
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    player_color = effect_dataset.empty_attributes.get("player_color", -1)

                    # ============================================================
                    # FIELD: Effect.color_mood
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    color_mood = effect_dataset.empty_attributes.get("color_mood", -1)

                    # ============================================================
                    # FIELD: Effect.reset_timer
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    reset_timer = effect_dataset.empty_attributes.get("reset_timer", -1)

                    # ============================================================
                    # FIELD: Effect.object_state
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    object_state = effect_dataset.empty_attributes.get("object_state", -1)

                    # ============================================================
                    # FIELD: Effect.action_type
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    action_type = effect_dataset.empty_attributes.get("action_type", -1)

                    # ============================================================
                    # FIELD: Effect.max_units_affected
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    max_units_affected = effect_dataset.empty_attributes.get("max_units_affected", -1)

                    # ============================================================
                    # FIELD: Effect.disable_garrison_unload_sound
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    disable_garrison_unload_sound = effect_dataset.empty_attributes.get(
                        "disable_garrison_unload_sound", -1
                    )

                    # ============================================================
                    # FIELD: Effect.disable_sound
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    disable_sound = effect_dataset.empty_attributes.get("disable_sound", -1)

                    # ============================================================
                    # FIELD: Effect.issue_group_command
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    issue_group_command = effect_dataset.empty_attributes.get("issue_group_command", -1)

                    # ============================================================
                    # FIELD: Effect.queue_action
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    queue_action = effect_dataset.empty_attributes.get("queue_action", -1)

                    # ============================================================
                    # FIELD: Effect.mutual_diplomacy
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    mutual_diplomacy = effect_dataset.empty_attributes.get("mutual_diplomacy", -1)

                    # ============================================================
                    # FIELD: Effect.building_list
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    building_list = effect_dataset.empty_attributes.get("building_list", -1)

                    # ============================================================
                    # FIELD: Effect.wall_x1/wall_y1/wall_x2/wall_y2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    wall_x1 = effect_dataset.empty_attributes.get("wall_x1", -1)
                    wall_y1 = effect_dataset.empty_attributes.get("wall_y1", -1)
                    wall_x2 = effect_dataset.empty_attributes.get("wall_x2", -1)
                    wall_y2 = effect_dataset.empty_attributes.get("wall_y2", -1)

                    # ============================================================
                    # FIELD: Effect.message_option1 / message_option2
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: DE_DEFAULT
                    message_option1 = str(effect_dataset.empty_attributes.get("message_option1", ""))
                    message_option2 = str(effect_dataset.empty_attributes.get("message_option2", ""))

                    # ============================================================
                    # FIELD: Effect.message
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.chat_text
                    message = _normalize_trigger_text(str(getattr(e, "chat_text", "") or ""))

                    # ============================================================
                    # FIELD: Effect.sound_name
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.audio_file
                    sound_name = str(getattr(e, "audio_file", "") or "")

                    # ============================================================
                    # FIELD: Effect.selected_object_ids
                    # ============================================================
                    # Source:
                    # SOURCE TYPE: GENIE_SCX_PY
                    # genie-scx: effect.objects[]
                    selected_object_ids = selected_ids

                    eff_overrides = {
                        "effect_type": effect_type,
                        "ai_script_goal": ai_script_goal,
                        "_quantity_int": _quantity_int,
                        "tribute_list": tribute_list,
                        "diplomacy": diplomacy,
                        "legacy_location_object_reference": legacy_location_object_reference,
                        "location_object_reference": location_object_reference,
                        "object_list_unit_id": object_list_unit_id,
                        "source_player": source_player,
                        "target_player": target_player,
                        "technology": technology,
                        "string_id": string_id,
                        "display_time": display_time,
                        "trigger_id": trigger_id,
                        "location_x": location_x,
                        "location_y": location_y,
                        "area_x1": area_x1,
                        "area_y1": area_y1,
                        "area_x2": area_x2,
                        "area_y2": area_y2,
                        "object_group": object_group,
                        "object_type": object_type,
                        "instruction_panel_position": instruction_panel_position,
                        "attack_stance": attack_stance,
                        "enabled": enabled,
                        "food": food,
                        "wood": wood,
                        "stone": stone,
                        "gold": gold,
                        "_item_id": _item_id,
                        "flash_object": flash_object,
                        "force_research_technology": force_research_technology,
                        "visibility_state": visibility_state,
                        "scroll": scroll,
                        "operation": operation,
                        "object_list_unit_id_2": object_list_unit_id_2,
                        "button_location": button_location,
                        "ai_signal_value": ai_signal_value,
                        "object_attributes": object_attributes,
                        "_variable_ref": _variable_ref,
                        "timer": timer,
                        "facet": facet,
                        "facet2": facet2,
                        "play_sound": play_sound,
                        "player_color": player_color,
                        "color_mood": color_mood,
                        "reset_timer": reset_timer,
                        "object_state": object_state,
                        "action_type": action_type,
                        "max_units_affected": max_units_affected,
                        "disable_garrison_unload_sound": disable_garrison_unload_sound,
                        "disable_sound": disable_sound,
                        "issue_group_command": issue_group_command,
                        "queue_action": queue_action,
                        "mutual_diplomacy": mutual_diplomacy,
                        "building_list": building_list,
                        "wall_x1": wall_x1,
                        "wall_y1": wall_y1,
                        "wall_x2": wall_x2,
                        "wall_y2": wall_y2,
                        "message_option1": message_option1,
                        "message_option2": message_option2,
                        "message": message,
                        "sound_name": sound_name,
                        "selected_object_ids": selected_object_ids,
                    }
                    eff_kwargs = _filter_supported_trigger_component_kwargs(
                        _BridgeMappedEffect,
                        scenario_version=scenario.scenario_version,
                        kwargs={**eff_defaults, **eff_overrides},
                    )
                    trig.effects.append(_BridgeMappedEffect(**eff_kwargs, uuid=tm._uuid))

                # Display orders: use exported order arrays if sane, else sequential.
                # NOTE: DE-resaved scenarios often keep a stable "display order array" but store the actual
                # `condition_data`/`effect_data` in a different internal slot order (like `trigger_data`).
                # The pair diffs in this repo compare list slots, so we rebuild internal storage order while
                # preserving the exported display order permutation.
                cond_order = list(getattr(t, "condition_order", []) or [])
                n_cond = len(trig.conditions)
                if (
                    isinstance(cond_order, list)
                    and len(cond_order) == n_cond
                    and sorted(int(x) for x in cond_order) == list(range(n_cond))
                ):
                    cond_order = [int(x) for x in cond_order]
                    inv = [0] * n_cond
                    for d in range(n_cond):
                        inv[cond_order[d]] = d
                    trig.conditions = [trig.conditions[inv[s]] for s in range(n_cond)]
                    trig.condition_order = cond_order
                else:
                    trig.condition_order = list(range(n_cond))

                eff_order = list(getattr(t, "effect_order", []) or [])
                n_eff = len(trig.effects)
                if (
                    isinstance(eff_order, list)
                    and len(eff_order) == n_eff
                    and sorted(int(x) for x in eff_order) == list(range(n_eff))
                ):
                    eff_order = [int(x) for x in eff_order]
                    inv = [0] * n_eff
                    for d in range(n_eff):
                        inv[eff_order[d]] = d
                    trig.effects = [trig.effects[inv[s]] for s in range(n_eff)]
                    trig.effect_order = eff_order
                else:
                    trig.effect_order = list(range(n_eff))

                new_triggers.append(trig)

            n = len(new_triggers)
            order_list = list(getattr(trig_sys, "trigger_order", []) or [])
            if (
                isinstance(order_list, list)
                and len(order_list) == n
                and sorted(int(x) for x in order_list) == list(range(n))
            ):
                order_list = [int(x) for x in order_list]
                # genie-scx exports `trigger_order` as a permutation that maps:
                #   legacy_trigger_index -> DE trigger_data storage slot
                #
                # DE-resaved scenarios store trigger_data in **storage slot order**, so we build:
                #   storage_slot -> legacy_trigger_index
                storage_to_legacy = [0] * n
                for legacy_idx, storage_slot in enumerate(order_list):
                    storage_to_legacy[storage_slot] = legacy_idx

                reordered = [new_triggers[storage_to_legacy[s]] for s in range(n)]
                for trigger in reordered:
                    for ce in get_trigger_referencing_ce(trigger):
                        tid = ce.trigger_id
                        if isinstance(tid, int) and 0 <= tid < n:
                            # genie-scx already exports trigger references (`trigger_id`) in the same
                            # numbering scheme that DE stores on disk for these legacy scenarios.
                            # Keep as-is; remapping based on trigger_order introduces incorrect refs.
                            pass
                for s, trigger in enumerate(reordered):
                    trigger.trigger_id = s
                tm.triggers = reordered
                tm.trigger_display_order = order_list
            else:
                if order_list is not None:
                    warn(
                        "Legacy triggers: missing or invalid trigger_order permutation; "
                        "using enumeration order for trigger_data and identity display order."
                    )
                tm.triggers = new_triggers
                tm.trigger_display_order = list(range(n))
        except Exception as e:
            warn(f"Unable to map legacy triggers: {e}")

    pin_legacy_trigger_execution_order(scenario)

    # ============================================================
    # FIELD: VictoryConditions (GlobalVictory / individual_victories)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.raw.options (encoded victory blobs)
    #
    # Explanation:
    # Legacy scenarios carry victory conditions in several encoded forms. Where available, we copy
    # the raw-encoded blocks into the DE structures to preserve semantics.
    #
    # Output:
    #   scenario.sections["GlobalVictory"] / scenario.sections["Options"].individual_victories
    if tribe is not None:
        try:
            gv = scenario.sections["GlobalVictory"]
            gv.conquest_required = int(bool(getattr(tribe.victory, "conquest", 0)))
            gv.ruins = int(getattr(tribe.victory, "ruins", 0))
            gv.artifacts_required = int(getattr(tribe.victory, "relics", 0))
            gv.discovery = int(getattr(tribe.victory, "discoveries", 0))
            gv.explored_percent_of_map_required = int(getattr(tribe.victory, "exploration", 0))
            gv.gold_required = int(getattr(tribe.victory, "gold", 0))
            gv.all_custom_conditions_required = int(bool(getattr(tribe, "victory_all_flag", 0)))
            gv.mode = int(getattr(tribe, "mp_victory_type", 0))
            gv.required_score_for_score_victory = int(getattr(tribe, "victory_score", 0))
            gv.time_for_timed_game_in_10ths_of_a_year = int(getattr(tribe, "victory_time", 0))
        except Exception as e:
            warn(f"Unable to map GlobalVictory from legacy victory export: {e}")

    # ---- Per-player VictoryConditions ----
    # We store these into the DE `Diplomacy.individual_victories` raw block (11520 bytes).
    if tribe is not None:
        try:
            import io

            indiv_buf = io.BytesIO()
            for row in getattr(tribe, "legacy_victory_info", []) or []:
                for entry in row:
                    entry.write_to(indiv_buf)
            data = indiv_buf.getvalue()
            if len(data) != 11520:
                warn(
                    f"individual_victories length mismatch: {len(data)} (expected 11520); trunc/pad will be applied"
                )
                data = (data + b"\x00" * 11520)[:11520]
            scenario.sections["Diplomacy"].retriever_map["individual_victories"].data = data
        except Exception as e:
            warn(f"Unable to map per-player VictoryConditions to Diplomacy.individual_victories: {e}")

    # ============================================================
    # FIELD: Options / Diplomacy / Map tail (TribeScen.options)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.raw.options
    #
    # Explanation:
    # This section is a grab-bag of legacy-derived knobs. Where fields are opaque or unstable between
    # pipelines, we either keep DE defaults or document ignore policy in the workbench.
    #
    # Outputs:
    #   scenario.sections["Options"], scenario.sections["Map"], diplomacy-related sections
    if tribe is not None:
        # Diplomacy team settings
        try:
            dip = scenario.sections["Diplomacy"]
            if getattr(tribe, "teams_locked", None) is not None:
                dip.lock_teams = int(bool(tribe.teams_locked))
            if getattr(tribe, "can_change_teams", None) is not None:
                dip.allow_players_choose_teams = int(bool(tribe.can_change_teams))
            if getattr(tribe, "random_start_locations", None) is not None:
                dip.random_start_points = 0
            if getattr(tribe, "max_teams", None) is not None:
                dip.max_number_of_teams = int(tribe.max_teams)
        except Exception as e:
            warn(f"Unable to map Diplomacy team options: {e}")

        # Allied victory (per player)
        try:
            av = list(getattr(tribe, "allied_victory", []) or [])
            if len(av) >= 8:
                scenario.sections["Diplomacy"].per_player_allied_victory = [int(x) for x in (av + [0] * 16)[:16]]
        except Exception as e:
            warn(f"Unable to map per_player_allied_victory: {e}")

        # Options section
        try:
            opt = scenario.sections["Options"]
            if getattr(tribe, "combat_mode", None) is not None:
                opt.combat_mode = int(tribe.combat_mode)
            if getattr(tribe, "naval_mode", None) is not None:
                opt.naval_mode = int(tribe.naval_mode)
            if getattr(tribe, "all_techs", None) is not None:
                opt.all_techs = int(bool(tribe.all_techs))

            # starting ages (per player)
            ages = list(getattr(tribe, "player_start_ages", []) or [])
            if len(ages) >= 16:

                def _legacy_age_to_de(v: int) -> int:
                    v = int(v)
                    if v <= 0:
                        return 2
                    if v == 1:
                        return 3
                    if v == 2:
                        return 4
                    if v == 3:
                        return 5
                    if v == 4:
                        return 6
                    return 2

                # `ages` entries may be enums (StartingAge) in genie_scx_py; normalize to legacy ints.
                def _age_raw(a: Any) -> int:
                    if hasattr(a, "to_i32"):
                        return int(a.to_i32(getattr(tribe.base, "version", 0.0)))
                    return int(a)

                opt.per_player_starting_age = [_legacy_age_to_de(_age_raw(x)) for x in ages[:16]]

            # map type -> ai_map_type (best-effort; DE stores this as signed)
            if getattr(tribe, "map_type", None) is not None:
                opt.ai_map_type = int(tribe.map_type)

            # base priorities
            bp = list(getattr(tribe, "base_priorities", []) or [])
            if len(bp) >= 8:
                opt.per_player_base_priority = [int(x) for x in bp[1:9]] if len(bp) >= 9 else [int(x) for x in bp[:8]]

            # disabled tech/unit/building IDs (match the old bridge_export filtering)
            def _filtered_disabled(kind: str) -> list[list[int]]:
                v = float(getattr(tribe.base, "version", 0.0))
                out: list[list[int]] = []
                for i in range(16):
                    arr = list(getattr(tribe, f"disabled_{kind}s")[i] or []) if hasattr(tribe, f"disabled_{kind}s") else []
                    if v >= 1.28:
                        out.append([int(x) for x in arr])
                    elif v >= 1.18:
                        counts = getattr(tribe, f"num_disabled_{kind}s", []) or []
                        n = max(0, int(counts[i])) if i < len(counts) else 0
                        out.append([int(x) for x in arr[: min(n, len(arr))] if int(x) > 0])
                    else:
                        out.append([])
                return out

            disabled_techs = _filtered_disabled("tech")
            disabled_units = _filtered_disabled("unit")
            disabled_buildings = _filtered_disabled("building")

            for pid in range(1, 9):
                try:
                    setattr(opt, f"disabled_tech_ids_player_{pid}", [int(x) for x in (disabled_techs[pid - 1] or []) if int(x) > 0])
                    setattr(opt, f"disabled_unit_ids_player_{pid}", [int(x) for x in (disabled_units[pid - 1] or []) if int(x) > 0])
                    setattr(opt, f"disabled_building_ids_player_{pid}", [int(x) for x in (disabled_buildings[pid - 1] or []) if int(x) > 0])
                except Exception as e:
                    warn(f"Unable to map disabled_*_ids_player_{pid}: {e}")
        except Exception as e:
            warn(f"Unable to map Options section from legacy options export: {e}")

    pin_option_manager_de_map_norms(scenario)

    # TribeScen.options.view is not applied as a blanket editor camera: DE-resaved scenarios derive
    # ``Units.player_data_3`` cameras from per-player ScenarioPlayerData (view + location), not from global view.

    # ============================================================
    # FIELD: Player metadata (resources, diplomacy, views, colors)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.world_players / payload.scenario_players / payload.raw.options.rge_messages
    #
    # Output:
    #   scenario.player_manager / scenario.sections["Units"] / scenario.sections["Map"] / etc.
    try:
        if active_player_count:
            scenario.player_manager.active_players = int(active_player_count)
    except Exception as e:
        warn(f"Unable to map PlayerManager.active_players: {e}")

    # World players -> starting resources (best-effort). Legacy ``ore`` is not written into
    # ``PlayerDataTwo.resources[*].ore_x_unused`` / ``Units.player_data_4`` duplicate ore slots;
    # mismatches vs DE-resaved refs are filtered by ``workbench/diff_validation.py`` (ore substring ignores).
    try:
        world_players = list(scen.world_players())
    except Exception:
        world_players = []

    for idx, wp in enumerate(world_players[:8], start=1):
        try:
            pid = idx
            p = scenario.player_manager.players[pid]
            food = int(float(getattr(wp, "food", p.food)))
            wood = int(float(getattr(wp, "wood", p.wood)))
            gold = int(float(getattr(wp, "gold", p.gold)))
            stone = int(float(getattr(wp, "stone", p.stone)))
            p.food = food
            p.wood = wood
            p.gold = gold
            p.stone = stone

            # Legacy `population` maps to DE population cap (best-effort).
            if getattr(wp, "population", None) is not None:
                pop = int(float(getattr(wp, "population")))
                p.population_cap = pop
                # NOTE: DE-resaved old/new pair files keep `Map.per_player_population_cap` at default 200s,
                # regardless of legacy world-player population. We'll set it explicitly below to match.

            goods = getattr(wp, "goods", None)
            if goods not in (None, 0, 0.0):
                warn(f"Legacy goods ignored for player {pid}: goods={goods}")
        except Exception as e:
            warn(f"Unable to map legacy world player resources: {e}")

    # RGEScen ``player_base_properties.active`` (needed before scenario_players so inactive slots do not
    # receive ``ScenarioPlayerData.name`` placeholders like ``Player 5``; DE-resaved refs keep those empty).
    active_by_pid: Dict[int, int] = {}
    try:
        if tribe is not None:
            base_props = list(getattr(tribe.base, "player_base_properties", []) or [])
            for pid, bp in enumerate(base_props[:16], start=1):
                active_by_pid[pid] = int(getattr(bp, "active", 0) or 0)
    except Exception:
        active_by_pid = {}

    # Scenario players -> names, diplomacy, initial views
    try:
        scenario_players = list(scen.scenario_players())
    except Exception:
        scenario_players = []

    for idx, sp in enumerate(scenario_players[:8], start=1):
        try:
            pid = idx
            p = scenario.player_manager.players[pid]

            if active_by_pid.get(pid, 1) != 0:
                name = getattr(sp, "name", None)
                if name and not (getattr(p, "tribe_name", None) or "").strip():
                    p.tribe_name = str(name)

            p.allied_victory = 1 if bool(getattr(sp, "allied_victory", False)) else 0

            relations = list(getattr(sp, "relations", []) or [])
            if relations:
                # Legacy ScenarioPlayerData.relations is a 9-length array:
                #   [Gaia, P1, P2, ..., P8]
                # and legacy stores "self" as 0. DE player diplomacy lists expect stances vs P1..P8
                # (8-length), with self encoded as 3.
                #
                # If we don't normalize this, `Units.player_data_3.diplomacy_for_*` (which is derived from
                # `player.diplomacy`) will differ from DE-resaved reference files.
                rel = [int(x) for x in relations]
                if len(rel) >= 9:
                    vs_players = rel[1:9]
                    vs_players[pid - 1] = 3
                    p.diplomacy = _pad_diplomacy(vs_players, pad_to=16, fill=3)
                else:
                    p.diplomacy = _pad_diplomacy(rel, pad_to=16, fill=3)

            view = list(getattr(sp, "view", []) or [])
            if view and len(view) >= 2:
                # stored as f32; DE expects ints
                ivx = int(float(view[0]))
                ivy = int(float(view[1]))
                p.initial_player_view_x = ivx
                p.initial_player_view_y = ivy

            # Player color:
            # The legacy `scenario_players.color` does not match DE's player-color assignment for many legacy files
            # (often appears as a permutation). We map to the canonical AoE2 player colors by player index:
            # P1..P8 => 0..7 (Blue, Red, Green, Yellow, Cyan, Purple, Gray, Orange).
            legacy_color = getattr(sp, "color", None)
            if legacy_color is not None and int(legacy_color) != (pid - 1):
                warn(f"Legacy color differs for player {pid}: legacy={legacy_color}; using canonical={pid - 1}")
            p.color = pid - 1
        except Exception as e:
            warn(f"Unable to map legacy scenario player data: {e}")

    for pid in range(1, 9):
        if active_by_pid.get(pid, 1) == 0:
            try:
                scenario.player_manager.players[pid].tribe_name = ""
            except Exception:
                pass

    # Match DE-resaved old/new pairs for map population caps, and for initial views when the legacy
    # file provides an editor "view" in the raw export.
    try:
        raw_view = list(getattr(tribe, "view", []) or []) if tribe is not None else None
        if isinstance(raw_view, list) and len(raw_view) >= 2:
            # DE-resaving often stamps this same view into all 16 initial view slots.
            ivx = int(raw_view[0])
            ivy = int(raw_view[1])
            for pv in scenario.sections["Map"].initial_player_views:
                pv.location_x = ivx
                pv.location_y = ivy
    except Exception as e:
        warn(f"Unable to set Map.initial_player_views from TribeScen.view: {e}")

    try:
        scenario.sections["Map"].per_player_population_cap = [200] * 16
    except Exception as e:
        warn(f"Unable to set Map.per_player_population_cap to 200s: {e}")

    # Ensure Options.per_player_starting_age is fully 16-length (including slots 9-16).
    try:
        ages = list(getattr(tribe, "player_start_ages", []) or []) if tribe is not None else None
        if isinstance(ages, list) and len(ages) >= 8:
            def _legacy_age_to_de(v: int) -> int:
                v = int(v)
                if v <= 0:
                    return 2
                if v == 1:
                    return 3
                if v == 2:
                    return 4
                if v == 3:
                    return 5
                if v == 4:
                    return 6
                return 2

            def _age_raw(a: Any) -> int:
                if tribe is not None and hasattr(a, "to_i32"):
                    return int(a.to_i32(getattr(tribe.base, "version", 0.0)))
                return int(a)

            # DE-resaved uses 0 for inactive slots.
            out_ages: list[int] = []
            for pid in range(1, 17):
                raw_age = _age_raw(ages[pid - 1]) if (pid - 1) < len(ages) else -1
                if active_by_pid.get(pid, 1) == 0:
                    # Inactive slots: DE-resaved references commonly keep `2` when legacy exports `0`,
                    # but keep `0` when legacy exports `-1`.
                    if raw_age > 0:
                        out_ages.append(_legacy_age_to_de(raw_age))
                    else:
                        out_ages.append(2 if raw_age == 0 else 0)
                else:
                    out_ages.append(_legacy_age_to_de(raw_age))
            scenario.sections["Options"].per_player_starting_age = out_ages
    except Exception as e:
        warn(f"Unable to ensure per_player_starting_age[0..15]: {e}")

    # Carry over per-player editor cameras (Units.player_data_3) from legacy ScenarioPlayerData (view + location).
    # DE-resaved matches: pd3[i] for i=1..7 uses legacy player (i+1); pd3[0] uses legacy player with max active pid 1..8.
    try:
        pd3 = scenario.sections["Units"].player_data_3
        sp_by_pid = {i + 1: sp for i, sp in enumerate(scenario_players[:16])}

        def _apply_sp_cameras(slot_idx: int, pid: int) -> None:
            sp = sp_by_pid.get(pid)
            if not sp or slot_idx < 0 or slot_idx >= len(pd3):
                return
            v = list(getattr(sp, "view", []) or [])
            loc = list(getattr(sp, "location", []) or [])
            if len(v) >= 2:
                pd3[slot_idx].editor_camera_x = float(v[0])
                pd3[slot_idx].editor_camera_y = float(v[1])
            if len(loc) >= 2:
                pd3[slot_idx].initial_camera_x = int(loc[0])
                pd3[slot_idx].initial_camera_y = int(loc[1])

        for idx in range(min(len(pd3), 8)):
            pid = idx + 1
            if idx == 0:
                continue
            _apply_sp_cameras(idx, pid)

        active_pids = [p for p in range(1, 9) if active_by_pid.get(p, 1) == 1]
        leader_pid = max(active_pids) if active_pids else None
        if leader_pid is not None:
            _apply_sp_cameras(0, leader_pid)
        elif len(pd3) >= 8:
            # Fallback: duplicate slot 7 if we cannot infer active players.
            pd3[0].editor_camera_x = pd3[7].editor_camera_x
            pd3[0].editor_camera_y = pd3[7].editor_camera_y
            pd3[0].initial_camera_x = pd3[7].initial_camera_x
            pd3[0].initial_camera_y = pd3[7].initial_camera_y
    except Exception as e:
        warn(f"Unable to map Units.player_data_3 editor/initial cameras from scenario_players: {e}")

    # ============================================================
    # FIELD: Embedded AI (PlayerDataTwo + Files.ai_files / Files.ai_error)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: TribeScen player AI slots + optional ``AIInfo`` (embedded ``AIFile`` list + optional ``AIErrorInfo``)
    #
    # Explanation:
    # ``Files.ai_files`` uses ``AIInfo.files`` when present; otherwise distinct RGEScen slot scripts
    # (filename + ``player_files`` ai_rules text). ``Files.ai_error`` is filled when ``AIInfo.error`` exists.
    #
    # Outputs:
    #   scenario.sections["PlayerDataTwo"], scenario.sections["Files"], scenario.player_manager.players[*]
    _apply_legacy_ai_embedded(scen, scenario)

    # If a full diplomacy matrix was exported from legacy TribeScen, prefer it over per-player relations.
    # DE stores 16 stance rows (Gaia + slots); mapping only P1–P8 left Gaia and empty slots at defaults.
    diplomacy_matrix = None
    if tribe is not None:
        try:
            diplomacy_matrix = [[stance.to_i32() for stance in row] for row in tribe.diplomacy]
        except Exception:
            diplomacy_matrix = None

    if isinstance(diplomacy_matrix, list) and len(diplomacy_matrix) == 16:
        try:
            dip = scenario.sections["Diplomacy"]
            for i in range(16):
                row = diplomacy_matrix[i]
                if not isinstance(row, list) or len(row) < 16:
                    continue
                stance = [int(x) for x in row[:16]]
                dip.per_player_diplomacy[i].stance_with_each_player = stance
                # IMPORTANT: do NOT overwrite `player_manager.players[*].diplomacy` from this matrix.
                # The DE-resaved reference pairs in this workbench often have `Units.player_data_3` (and
                # `PlayerManager.players[*].diplomacy`) matching legacy ScenarioPlayerData relations rather than
                # the raw TribeScen diplomacy matrix. We only use this matrix to populate the DE `Diplomacy`
                # section, which is the authoritative gameplay diplomacy table.
        except Exception as e:
            warn(f"Unable to map full diplomacy_matrix: {e}")

    # Units.player_data_3 stores duplicated diplomacy arrays used by the UI/AI.
    # DE-resaved scenarios have these consistent with the player's diplomacy stances, but legacy exports
    # encode relations as `[Gaia, P1..P8]` with self as 0. After normalizing `player.diplomacy` above,
    # rebuild these duplicates to avoid persistent diffs.
    try:
        original_map: Dict[int, str] = {0: "ally", 1: "neutral", 3: "enemy"}
        mappings: Dict[str, Dict[str, int]] = {
            "diplomacy_for_interaction": {"self": 0, "ally": 0, "neutral": 1, "enemy": 3, "gaia": 3},
            "diplomacy_for_ai_system": {"self": 1, "ally": 2, "neutral": 3, "enemy": 4, "gaia": 0},
        }
        pd3 = scenario.sections["Units"].player_data_3
        for idx in range(min(8, len(pd3))):
            pid = idx + 1
            stances = list(getattr(scenario.player_manager.players[pid], "diplomacy", []) or [])
            # By convention in this legacy bridge, `player.diplomacy[0..7]` represent stances vs P1..P8.
            # (Even if the list is padded to 16 for AoE2ScenarioParser internals.)
            vs_players = [int(x) for x in (stances + [3] * 8)[:8]]
            # Ensure self is encoded as 3 for mapping
            if 0 <= (pid - 1) < len(vs_players):
                vs_players[pid - 1] = 3

            for key, mapping in mappings.items():
                temp = [mapping["gaia"]]
                for n in vs_players:
                    label = original_map.get(int(n), "enemy")
                    temp.append(mapping[label])
                temp[pid] = mapping["self"]
                setattr(pd3[idx], key, temp)
    except Exception as e:
        warn(f"Unable to rebuild Units.player_data_3 diplomacy duplicates: {e}")

    # ============================================================
    # FIELD: Map terrain (tiles, elevation, layer)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.map.tiles (terrain_id/elevation/layer)
    #
    # Output:
    #   scenario.sections["Map"].tile_data
    try:
        map_obj = scen.map()
        width = int(getattr(map_obj, "width", 0) or 0)
        height = int(getattr(map_obj, "height", 0) or 0)
        tiles_src = list(getattr(map_obj, "tiles", []) or [])
    except Exception:
        width = 0
        height = 0
        tiles_src = []

    if width and height and width == height and tiles_src:
        try:
            scenario.map_manager.map_size = width
            if len(scenario.map_manager.terrain) != len(tiles_src):
                warn(
                    f"Legacy map tile count mismatch: legacy={len(tiles_src)} vs de={len(scenario.map_manager.terrain)}"
                )
            for i, t in enumerate(tiles_src[: len(scenario.map_manager.terrain)]):
                tile = scenario.map_manager.terrain[i]
                terrain_id = int(getattr(t, "terrain", 0) or 0)
                # Some legacy terrain IDs are no longer used in DE. DE-resaved scenarios represent them as
                # a base terrain (`terrain_id`) with an overlay (`layer`) equal to the overlay terrain ID.
                #
                # Verified with workbench pairs (Kyoto/Hastings):
                # - OBSOLETE_SNOW_GRASS (34) => GRASS_1 (0) + layer=SNOW (32)
                # - OBSOLETE_SNOW_DIRT  (33) => DIRT_1  (6) + layer=SNOW (32)
                #
                # genie-scx exports these as `terrain=<obsolete>` with `layered_terrain=None`, so we translate here.
                # Full obsolete-terrain translation (best-effort):
                # - Use a DE-equivalent base terrain ID and set `layer` to the overlay terrain ID when DE-resaved
                #   pairs indicate the obsolete tile is a base+overlay combination.
                # - For obsolete IDs that we haven't observed in workbench pairs yet, map to the closest modern
                #   single terrain (layer stays -1 unless `layered_terrain` is present).
                if terrain_id == 34:  # OBSOLETE_SNOW_GRASS
                    terrain_id = 0  # GRASS_1
                    tile.layer = 32  # SNOW overlay
                elif terrain_id == 33:  # OBSOLETE_SNOW_DIRT
                    terrain_id = 6  # DIRT_1
                    tile.layer = 32  # SNOW overlay
                elif terrain_id == 38:  # OBSOLETE_ROAD_SNOW
                    terrain_id = 25  # ROAD_BROKEN
                    tile.layer = 32  # SNOW overlay
                elif terrain_id == 39:  # OBSOLETE_ROAD_FUNGUS
                    terrain_id = 6  # DIRT_1
                    tile.layer = 75  # ROAD_FUNGUS overlay
                elif terrain_id == 43:  # OBSOLETE_ROAD_DESERT
                    # Observed in AllTerrain resave: DESERT_SAND (14) with layer=ROAD_BROKEN (25)
                    terrain_id = 14  # DESERT_SAND
                    tile.layer = 25  # ROAD_BROKEN
                elif terrain_id == 61:  # OBSOLETE_ROAD_JUNGLE
                    # Observed in AllTerrain resave: ROAD_FUNGUS (75) with layer=GRASS_JUNGLE (60)
                    terrain_id = 75  # ROAD_FUNGUS
                    tile.layer = 60  # GRASS_JUNGLE
                elif terrain_id == 62:  # OBSOLETE_UNDERBRUSH_JUNGLE
                    # Observed in AllTerrain resave: UNDERBRUSH_JUNGLE (77) with layer=GRASS_JUNGLE (60)
                    terrain_id = 77  # UNDERBRUSH_JUNGLE
                    tile.layer = 60  # GRASS_JUNGLE
                elif terrain_id == 44:  # OBSOLETE_DIRT_MUD
                    # Observed in AllTerrain resave: GRASS_1 (0) with layer=DIRT_MUD (76)
                    terrain_id = 0  # GRASS_1
                    tile.layer = 76  # DIRT_MUD
                
                # Special Cases
                elif terrain_id == 36:  # SNOW_FOUNDATION (layered in DE resaves)
                    # Observed in AllTerrain resave: DIRT_1 (6) with layer=SNOW (32)
                    terrain_id = 6  # DIRT_1
                    tile.layer = 32  # SNOW overlay
                elif terrain_id == 103:  # OBSOLETE_ROAD_GRAVEL
                    # Not seen in current workbench pairs; apply a simple direct conversion.
                    terrain_id = 78  # ROAD_GRAVEL

                tile.terrain_id = terrain_id
                tile.elevation = int(getattr(t, "elevation", 0) or 0)
                # genie-scx layered_terrain is optional u16; DE uses `layer` for something else.
                layered = getattr(t, "layered_terrain", None)
                if layered is not None:
                    tile.layer = int(layered)
                else:
                    # Preserve any layer we set via obsolete-terrain translation above.
                    tile.layer = int(getattr(tile, "layer", -1))
        except Exception as e:
            warn(f"Unable to map map terrain: {e}")
    else:
        warn(
            "Legacy map not mapped (missing width/height/tiles or non-square map). "
            "Output scenario will use default DE map."
        )

    # ============================================================
    # FIELD: Units (legacy objects → DE unit_manager)
    # ============================================================
    # Source:
    # SOURCE TYPE: GENIE_SCX_PY
    # genie-scx: payload.objects[*]
    #
    # Explanation:
    # Place each exported legacy object as a DE unit. Some attributes are inherently editor-dependent
    # (rotation/frames) and are intentionally treated as best-effort.
    #
    # Output:
    #   scenario.unit_manager (Units section)
    objects_src: list[tuple[int, Any]] = []
    try:
        for player_id, lst in enumerate(getattr(scen.format, "player_objects", []) or []):
            for obj in lst or []:
                objects_src.append((int(player_id), obj))
    except Exception:
        objects_src = []

    if not objects_src:
        warn("No legacy objects exported; Units will remain default/empty.")
        return

    placed = 0
    for player_id, obj in objects_src:
        try:
            pos = getattr(obj, "position", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
            x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
            unit_const = int(getattr(obj, "object_type", 0) or 0)
            reference_id = int(getattr(obj, "id", 0) or 0)
            # Legacy `.scx` angle is stored as f32 (often true radians for buildings/units). Gaia terrain pieces
            # frequently use 2*pi/5 steps in radians while DE-resaved scenarios may collapse facing to small floats
            # (0..7) in a placement-dependent way, so numeric compare vs an editor-resaved DE pair can still disagree
            # even when the map looks correct.
            rotation = _f32_roundtrip(float(getattr(obj, "angle", 0.0) or 0.0))
            raw_frame = getattr(obj, "frame", None)
            if raw_frame is None:
                animation_frame = 0
            else:
                animation_frame = max(0, min(int(raw_frame), 65535))
            status = int(getattr(obj, "state", 2) or 2)
            garrisoned_in = getattr(obj, "garrisoned_in", None)
            garrisoned_in_id = int(garrisoned_in) if garrisoned_in is not None else -1

            # DE-resaved campaign scenarios often omit some legacy "skeleton" decoration objects.
            # To match the DE-resaved references in our workbench, skip dead skeleton objects.
            if unit_const == 710 and status == 2:
                continue

            scenario.unit_manager.add_unit(
                player=player_id,
                unit_const=unit_const,
                x=x,
                y=y,
                z=z,
                rotation=rotation,
                garrisoned_in_id=garrisoned_in_id,
                animation_frame=animation_frame,
                status=status,
                reference_id=reference_id,
            )
            placed += 1
        except Exception as e:
            warn(f"Skipping legacy object due to mapping error: {e}")

    warn(
        f"Placed {placed}/{len(objects_src)} legacy objects as DE units (best-effort)."
    )

