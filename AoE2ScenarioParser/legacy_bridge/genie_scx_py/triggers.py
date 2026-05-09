from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, List, Optional, Sequence

from ._io import BinaryReader, BinaryWriter
from ._support.read import read_opt_u32
from ._support.strings import (
    read_u32_length_prefixed_str,
    write_i32_str,
    write_opt_i32_str,
)
from ._support.ids import StringKey, StringKeyNum, string_key_try_into_u32
from ._support.ids import UnitTypeID


@dataclass(slots=True)
class TriggerCondition:
    condition_type: int
    properties: List[int]

    @staticmethod
    def read_from(reader: BinaryIO, version: float) -> "TriggerCondition":
        r = BinaryReader(reader)
        condition_type = r.read_i32()
        num_properties = r.read_i32() if version > 1.0 else 13
        props = [r.read_i32() for _ in range(num_properties)]
        while len(props) < 18:
            props.append(-1)
        return TriggerCondition(condition_type=condition_type, properties=props)

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        w.write_i32(self.condition_type)
        if version > 1.0:
            w.write_i32(len(self.properties))
            for v in self.properties:
                w.write_i32(v)
        else:
            for i in range(13):
                w.write_i32(self.properties[i] if i < len(self.properties) else 0)

    # Accessors used by converters
    def unit_type(self) -> UnitTypeID:
        return UnitTypeID(int(self.properties[4]) & 0xFFFF)

    def set_unit_type(self, unit_type: UnitTypeID) -> None:
        self.properties[4] = int(unit_type)

    def object_type(self) -> UnitTypeID:
        return UnitTypeID(int(self.properties[14]) & 0xFFFF)

    def set_object_type(self, object_type: UnitTypeID) -> None:
        self.properties[14] = int(object_type)


@dataclass(slots=True)
class TriggerEffect:
    effect_type: int
    properties: List[int]
    chat_text: Optional[str]
    audio_file: Optional[str]
    objects: List[int]

    @staticmethod
    def read_from(reader: BinaryIO, version: float) -> "TriggerEffect":
        r = BinaryReader(reader)
        effect_type = r.read_i32()
        num_properties = r.read_i32() if version > 1.0 else 16
        props = [r.read_i32() for _ in range(num_properties)]
        while len(props) < 24:
            props.append(-1)
        chat_text = read_u32_length_prefixed_str(reader)
        audio_file = read_u32_length_prefixed_str(reader)
        objects: List[int] = []
        if version > 1.1:
            for _ in range(props[4]):
                objects.append(r.read_i32())
        else:
            objects.append(props[4])
            props[4] = 1
        return TriggerEffect(
            effect_type=effect_type,
            properties=props,
            chat_text=chat_text,
            audio_file=audio_file,
            objects=objects,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        w.write_i32(self.effect_type)
        w.write_i32(len(self.properties))
        for v in self.properties:
            w.write_i32(v)
        write_opt_i32_str(writer, self.chat_text)
        write_opt_i32_str(writer, self.audio_file)
        if version > 1.1:
            num_objects = self.properties[4] if len(self.properties) > 4 else 0
            for i in range(num_objects):
                w.write_i32(self.objects[i] if i < len(self.objects) else -1)

    def unit_type(self) -> UnitTypeID:
        return UnitTypeID(int(self.properties[6]) & 0xFFFF)

    def set_unit_type(self, unit_type: UnitTypeID) -> None:
        self.properties[6] = int(unit_type)

    def object_type(self) -> UnitTypeID:
        return UnitTypeID(int(self.properties[21]) & 0xFFFF)

    def set_object_type(self, object_type: UnitTypeID) -> None:
        self.properties[21] = int(object_type)


def _read_opt_string_key(reader: BinaryIO) -> Optional[StringKey]:
    v = read_opt_u32(reader)
    if v is None:
        return None
    return StringKeyNum(int(v))


def _write_opt_string_key(writer: BinaryIO, key: Optional[StringKey]) -> None:
    w = BinaryWriter(writer)
    if key is None:
        w.write_u32(0xFFFF_FFFF)
    else:
        w.write_u32(string_key_try_into_u32(key))


@dataclass(slots=True)
class Trigger:
    enabled: bool
    looping: bool
    name_id: int
    is_objective: bool
    objective_order: int
    start_time: int
    description: Optional[str]
    short_description_id: Optional[StringKey]
    short_description: Optional[str]
    display_short_description: bool
    short_description_state: int
    mute_objective: bool
    name: Optional[str]
    effects: List[TriggerEffect]
    effect_order: List[int]
    conditions: List[TriggerCondition]
    condition_order: List[int]
    make_header: bool

    @staticmethod
    def read_from(reader: BinaryIO, version: float) -> "Trigger":
        r = BinaryReader(reader)
        enabled = r.read_i32() != 0
        looping = r.read_i8() != 0
        name_id = r.read_i32()
        is_objective = r.read_i8() != 0
        objective_order = r.read_i32()

        make_header = False
        short_description_id: Optional[StringKey] = None
        short_description_state = 0
        display_short_description = False
        mute_objective = False

        if version >= 1.8:
            make_header = r.read_u8() != 0
            short_description_id = _read_opt_string_key(reader)
            display_short_description = r.read_u8() != 0
            short_description_state = r.read_u8()
            start_time = r.read_u32()
            mute_objective = r.read_u8() != 0
        else:
            start_time = r.read_u32()

        description = read_u32_length_prefixed_str(reader)
        name = read_u32_length_prefixed_str(reader)
        short_description = read_u32_length_prefixed_str(reader) if version >= 1.8 else None

        num_effects = r.read_i32()
        effects: List[TriggerEffect] = []
        effect_order: List[int] = []
        for _ in range(num_effects):
            effects.append(TriggerEffect.read_from(reader, version))
        for _ in range(num_effects):
            effect_order.append(r.read_i32())

        num_conditions = r.read_i32()
        conditions: List[TriggerCondition] = []
        condition_order: List[int] = []
        for _ in range(num_conditions):
            conditions.append(TriggerCondition.read_from(reader, version))
        for _ in range(num_conditions):
            condition_order.append(r.read_i32())

        return Trigger(
            enabled=enabled,
            looping=looping,
            name_id=name_id,
            is_objective=is_objective,
            objective_order=objective_order,
            start_time=start_time,
            description=description,
            short_description_id=short_description_id,
            short_description=short_description,
            display_short_description=display_short_description,
            short_description_state=short_description_state,
            mute_objective=mute_objective,
            name=name,
            effects=effects,
            effect_order=effect_order,
            conditions=conditions,
            condition_order=condition_order,
            make_header=make_header,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        w.write_i32(1 if self.enabled else 0)
        w.write_i8(1 if self.looping else 0)
        w.write_i32(self.name_id)
        w.write_i8(1 if self.is_objective else 0)
        w.write_i32(self.objective_order)
        if version >= 1.8:
            w.write_u8(1 if self.make_header else 0)
            _write_opt_string_key(writer, self.short_description_id)
            w.write_u8(1 if self.display_short_description else 0)
            w.write_u8(self.short_description_state)
            w.write_u32(self.start_time)
            w.write_u8(1 if self.mute_objective else 0)
        else:
            w.write_u32(self.start_time)

        write_opt_i32_str(writer, self.description)
        write_opt_i32_str(writer, self.name)
        if version >= 1.8:
            write_opt_i32_str(writer, self.short_description)

        w.write_u32(len(self.effects))
        for e in self.effects:
            e.write_to(writer, version)
        for o in self.effect_order:
            w.write_i32(o)

        w.write_u32(len(self.conditions))
        for c in self.conditions:
            c.write_to(writer, version)
        for o in self.condition_order:
            w.write_i32(o)

    def conditions_unordered_mut(self):
        return iter(self.conditions)

    def effects_unordered_mut(self):
        return iter(self.effects)


@dataclass(slots=True)
class TriggerSystem:
    version: float
    objectives_state: int
    triggers: List[Trigger]
    trigger_order: List[int]
    enabled_techs: List[int]
    variable_values: List[int]
    variable_names: List[str]

    @staticmethod
    def default() -> "TriggerSystem":
        return TriggerSystem(
            version=1.6,
            objectives_state=0,
            triggers=[],
            trigger_order=[],
            enabled_techs=[],
            variable_values=[0] * 256,
            variable_names=[""] * 256,
        )

    @staticmethod
    def read_from(reader: BinaryIO) -> "TriggerSystem":
        r = BinaryReader(reader)
        version = r.read_f64()
        objectives_state = r.read_i8() if version >= 1.5 else 0
        num_triggers = r.read_i32()
        triggers = [Trigger.read_from(reader, version) for _ in range(num_triggers)]
        if version >= 1.4:
            trigger_order = [r.read_i32() for _ in range(num_triggers)]
        else:
            trigger_order = list(range(num_triggers))

        variable_values: List[int] = []
        enabled_techs: List[int] = []
        variable_names: List[str] = []
        if version >= 2.2:
            variable_values = [r.read_u32() for _ in range(256)]
            num_enabled = r.read_u32()
            enabled_techs = [r.read_u32() for _ in range(num_enabled)]
            num_var_names = r.read_u32()
            variable_names = [""] * 256
            for _ in range(num_var_names):
                idx = r.read_u32()
                if idx >= 256:
                    raise ValueError("Unexpected variable number, this is probably a genie-scx bug")
                variable_names[idx] = read_u32_length_prefixed_str(reader) or ""

        return TriggerSystem(
            version=version,
            objectives_state=objectives_state,
            triggers=triggers,
            trigger_order=trigger_order,
            enabled_techs=enabled_techs,
            variable_values=variable_values,
            variable_names=variable_names,
        )

    def write_to(self, writer: BinaryIO, version: float) -> None:
        w = BinaryWriter(writer)
        w.write_f64(version)
        if version >= 1.5:
            w.write_i8(self.objectives_state)
        w.write_u32(len(self.triggers))
        for t in self.triggers:
            t.write_to(writer, version)
        if version >= 1.4:
            for o in self.trigger_order:
                w.write_i32(o)
        if version >= 2.2:
            padded_values = (self.variable_values + [0] * 256)[:256]
            for v in padded_values:
                w.write_u32(v)
            w.write_u32(len(self.enabled_techs))
            for tech in self.enabled_techs:
                w.write_u32(tech)
            custom = [(i, n) for i, n in enumerate(self.variable_names) if n]
            w.write_u32(len(custom))
            for idx, name in custom:
                w.write_u32(idx)
                write_i32_str(writer, name)

    def num_triggers(self) -> int:
        return len(self.triggers)

