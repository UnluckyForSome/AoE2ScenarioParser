from __future__ import annotations

from typing import Callable, Optional, TypeVar

S = TypeVar("S")
T = TypeVar("T")


def map_into(value, into: Callable[[S], T]):
    """
    Rust: MapInto for Option<T> and Result<T, E>.

    In Python we keep this helper extremely small and explicit: it maps `value`
    using `into` if the value is not None.
    """

    if value is None:
        return None
    return into(value)

