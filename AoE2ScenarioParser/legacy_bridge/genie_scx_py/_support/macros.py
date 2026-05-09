from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Type, TypeVar

T = TypeVar("T")


def f32_eq(left: float, right: float) -> bool:
    # Rust: `f32::abs($left - $right) < std::f32::EPSILON`
    # We use the f32 epsilon constant value (not Python float epsilon).
    return abs(float(left) - float(right)) < 1.1920929e-07


def f32_neq(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) > 1.1920929e-07


def try_u16(value: int) -> int:
    if not (0 <= value <= 0xFFFF):
        raise ValueError("out of range for u16")
    return int(value)


def try_i16(value: int) -> int:
    if not (-0x8000 <= value <= 0x7FFF):
        raise ValueError("out of range for i16")
    return int(value)


def try_u32(value: int) -> int:
    if not (0 <= value <= 0xFFFF_FFFF):
        raise ValueError("out of range for u32")
    return int(value)


def try_i32(value: int) -> int:
    if not (-0x8000_0000 <= value <= 0x7FFF_FFFF):
        raise ValueError("out of range for i32")
    return int(value)

