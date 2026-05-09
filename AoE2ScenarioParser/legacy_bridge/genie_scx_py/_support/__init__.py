"""
Python port of the Rust crate `genie-support`.

This package is internal to the `genie_scx_py` port and intentionally mirrors the
API surface used by the Rust `genie-scx` crate.
"""

from __future__ import annotations

from .ids import SpriteID, StringKey, TechID, UnitTypeID
from .map_into import map_into
from .read import read_opt_u16, read_opt_u32, skip
from .strings import (
    DecodeStringError,
    EncodeStringError,
    ReadStringError,
    WriteStringError,
    read_hd_style_str,
    read_str,
    read_u16_length_prefixed_str,
    read_u32_length_prefixed_str,
    write_i32_str,
    write_opt_i32_str,
    write_opt_str,
    write_str,
)

__all__ = [
    "DecodeStringError",
    "EncodeStringError",
    "ReadStringError",
    "WriteStringError",
    "UnitTypeID",
    "TechID",
    "SpriteID",
    "StringKey",
    "read_opt_u16",
    "read_opt_u32",
    "skip",
    "map_into",
    "read_str",
    "read_u16_length_prefixed_str",
    "read_u32_length_prefixed_str",
    "read_hd_style_str",
    "write_str",
    "write_i32_str",
    "write_opt_str",
    "write_opt_i32_str",
]

