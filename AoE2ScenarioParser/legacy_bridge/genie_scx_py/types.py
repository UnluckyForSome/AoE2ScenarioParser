from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

# Scenario "data" version: first `f32` inside the compressed payload (after `next_object_id`).
# Values >= this threshold match Definitive Edition scenario files; genie_scx_py rejects them at parse time.
DEFINITIVE_EDITION_MIN_DATA_VERSION = 1.28


class UnsupportedFormatVersionError(ValueError):
    """
    Raised when the four-byte container format token is not mapped by :meth:`SCXVersion.to_player_version`.

    Mirrors ``genie-scx`` ``Error::UnsupportedFormatVersionError``.
    """

    def __init__(self, format_version: "SCXVersion") -> None:
        self.format_version = format_version
        super().__init__(f"unsupported format version {format_version!r}")


class DefinitiveEditionScenarioError(ValueError):
    """Raised when the file is treated as AoE II: DE (container token and/or scenario data version)."""

    def __init__(
        self,
        *,
        data_version: Optional[float] = None,
        container_format: Optional[str] = None,
    ) -> None:
        bits: list[str] = []
        if container_format is not None:
            bits.append(f"container format {container_format}")
        if data_version is not None:
            bits.append(f"data version {float(data_version):g}")
        suffix = f" ({', '.join(bits)})" if bits else ""
        super().__init__(
            f"It looks like you're trying to parse a Definitive Edition scenario{suffix}. "
            "genie_scx_py only supports legacy Age of Empires II scenarios; try AoE2ScenarioParser instead."
        )
        self.data_version = data_version
        self.container_format = container_format


class TooManyDisabledTechsError(ValueError):
    """Mirrors ``genie-scx`` ``Error::TooManyDisabledTechsError``."""

    def __init__(self, count: int) -> None:
        self.count = int(count)
        super().__init__(
            f"too many disabled techs: got {self.count}, but requested version supports up to 20"
        )


class CannotDisableTechsError(ValueError):
    """Mirrors ``genie-scx`` ``Error::CannotDisableTechsError``."""

    def __init__(self) -> None:
        super().__init__("requested version does not support disabling techs")


class CannotDisableUnitsError(ValueError):
    """Mirrors ``genie-scx`` ``Error::CannotDisableUnitsError``."""

    def __init__(self) -> None:
        super().__init__("requested version does not support disabling units")


class TooManyDisabledBuildingsError(ValueError):
    """Mirrors ``genie-scx`` ``Error::TooManyDisabledBuildingsError``."""

    def __init__(self, count: int, max_allowed: int) -> None:
        self.count = int(count)
        self.max_allowed = int(max_allowed)
        super().__init__(
            "too many disabled buildings: got {}, but requested version supports up to {}".format(
                self.count, self.max_allowed
            )
        )


class CannotDisableBuildingsError(ValueError):
    """Mirrors ``genie-scx`` ``Error::CannotDisableBuildingsError``."""

    def __init__(self) -> None:
        super().__init__("requested version does not support disabling buildings")


def is_definitive_edition_scenario_data_version(data: float) -> bool:
    """True if ``data`` is the scenario payload version and indicates DE."""
    return float(data) >= DEFINITIVE_EDITION_MIN_DATA_VERSION


@dataclass(frozen=True, slots=True)
class SCXVersion:
    """
    Rust: `pub struct SCXVersion(pub(crate) [u8; 4]);`

    IMPORTANT: ordering is NOT string or float compare; it compares the 1st byte,
    then the 3rd, then the 4th (matching the Rust Ord impl).
    """

    raw: bytes = b"1.21"

    def __post_init__(self) -> None:
        if not isinstance(self.raw, (bytes, bytearray)) or len(self.raw) != 4:
            raise ValueError(f"SCXVersion must be 4 bytes, got: {self.raw!r}")
        object.__setattr__(self, "raw", bytes(self.raw))

    def as_bytes(self) -> bytes:
        return self.raw

    def __str__(self) -> str:
        return self.raw.decode("ascii", errors="replace")

    def __repr__(self) -> str:
        return repr(str(self))

    def __eq__(self, other) -> bool:  # type: ignore[override]
        if isinstance(other, SCXVersion):
            return self.raw == other.raw
        if isinstance(other, (bytes, bytearray)) and len(other) == 4:
            # Rust PartialEq<[u8;4]>: digits '.' digits digits semantics.
            return (
                other[0] == self.raw[0]
                and other[1] == ord(".")
                and other[2] == self.raw[2]
                and other[3] == self.raw[3]
            )
        return False

    def _cmp_tuple(self) -> tuple[int, int, int]:
        return (self.raw[0], self.raw[2], self.raw[3])

    def __lt__(self, other: "SCXVersion") -> bool:
        return self._cmp_tuple() < other._cmp_tuple()

    def __le__(self, other: "SCXVersion") -> bool:
        return self._cmp_tuple() <= other._cmp_tuple()

    def __gt__(self, other: "SCXVersion") -> bool:
        return self._cmp_tuple() > other._cmp_tuple()

    def __ge__(self, other: "SCXVersion") -> bool:
        return self._cmp_tuple() >= other._cmp_tuple()

    def to_player_version(self) -> Optional[float]:
        """
        Map this container token (first four bytes, ASCII ``d.dxx``) to genie-scx's **player-layout**
        reader version (which branch of ``WorldPlayerData`` / ``ScenarioPlayerData`` to use).

        This value is independent of ``VersionBundle.header``, ``.data``, ``.triggers``, and similar
        axes. Whether to reject a file as Definitive Edition is handled separately by
        :func:`is_definitive_edition_container_format` (container token vs. ``1.22``) and
        :func:`is_definitive_edition_scenario_data_version` (payload ``f32`` vs. ``1.28``).

        Mostly matches Rust ``SCXVersion::to_player_version``. This port additionally maps ``1.22``
        to ``1.14`` because genie-scx's ``VersionBundle::is_hd_edition`` allows container ``1.22``,
        but upstream ``to_player_version`` does not list it.
        """
        b = self.as_bytes()
        if b == b"1.07":
            return 1.07
        if b in (b"1.09", b"1.10", b"1.11"):
            return 1.11
        if b in (b"1.12", b"1.13", b"1.14", b"1.15", b"1.16"):
            return 1.12
        if b in (b"1.18", b"1.19"):
            return 1.13
        if b in (b"1.20", b"1.21", b"1.22"):
            return 1.14
        return None


# Non-DE ASCII container ceiling: genie-scx `hd_edition` uses `1.21`, but cheekily allows 1.22 - maybe this is for expansions or userpatch/wololo. Either way, have copied the logic from genie-scx.
LEGACY_MAX_CONTAINER_FORMAT_TOKEN = SCXVersion(b"1.22")


def is_definitive_edition_container_format(format_version: SCXVersion) -> bool:
    """
    True if the container token is strictly newer than ``1.22``.

    ``1.21`` / ``1.22`` stay on the legacy path (genie-scx HD signals); ``1.32``, ``1.57``, … are rejected here.
    """

    return format_version > LEGACY_MAX_CONTAINER_FORMAT_TOKEN


def is_ascii_scx_version_prefix(prefix: bytes) -> bool:
    """True if ``prefix`` looks like the fixed-width ASCII container token ``d.dxx`` (e.g. ``1.21``, ``1.57``)."""
    if len(prefix) != 4:
        return False
    if prefix[1] != ord("."):
        return False
    return all(48 <= b <= 57 for b in (prefix[0], prefix[2], prefix[3]))


def legacy_format_version_from_prefix(prefix: bytes) -> Optional[SCXVersion]:
    """
    Interpret ``prefix`` as the first four bytes of a genie-scx scenario container.

    These files start with a fixed-width ASCII format token ``d.dxx`` (for example ``1.21``).
    Returns ``SCXVersion`` only for tokens that have a :meth:`SCXVersion.to_player_version`
    mapping (legacy containers at most ``1.22``; newer tokens are rejected elsewhere).
    """
    if not is_ascii_scx_version_prefix(prefix):
        return None
    v = SCXVersion(prefix)
    return v if v.to_player_version() is not None else None


def legacy_format_version_peek_path(path: Path) -> Optional[SCXVersion]:
    """Read the first four bytes of ``path`` and return the format version when supported."""
    try:
        with path.open("rb") as f:
            prefix = f.read(4)
    except OSError:
        return None
    return legacy_format_version_from_prefix(prefix)


class ParseDiplomaticStanceError(ValueError):
    def __init__(self, found: int):
        super().__init__(f"invalid diplomatic stance {found} (must be 0/1/3)")
        self.found = found


class DiplomaticStance(Enum):
    Ally = 0
    Neutral = 1
    Enemy = 3

    @staticmethod
    def try_from(n: int) -> "DiplomaticStance":
        if n == 0:
            return DiplomaticStance.Ally
        if n == 1:
            return DiplomaticStance.Neutral
        if n == 3:
            return DiplomaticStance.Enemy
        raise ParseDiplomaticStanceError(int(n))

    def to_i32(self) -> int:
        return int(self.value)


class ParseDataSetError(ValueError):
    def __init__(self, found: int):
        super().__init__(f"invalid data set {found} (must be 0/1)")
        self.found = found


class DataSet(Enum):
    BaseGame = 0
    Expansions = 1

    @staticmethod
    def try_from(n: int) -> "DataSet":
        if n == 0:
            return DataSet.BaseGame
        if n == 1:
            return DataSet.Expansions
        raise ParseDataSetError(int(n))

    def to_i32(self) -> int:
        return int(self.value)


class ParseDLCPackageError(ValueError):
    def __init__(self, found: int):
        super().__init__(f"unknown dlc package {found}")
        self.found = found


class DLCPackage(Enum):
    # Some HD scenarios saved before the .aoe2scenario format use 0 or 1 here.
    LegacyDependencyCode0 = 0
    LegacyDependencyCode1 = 1
    AgeOfKings = 2
    AgeOfConquerors = 3
    TheForgotten = 4
    AfricanKingdoms = 5
    RiseOfTheRajas = 6
    LastKhans = 7

    @staticmethod
    def try_from(n: int) -> "DLCPackage":
        for v in DLCPackage:
            if v.value == n:
                return v
        raise ParseDLCPackageError(int(n))

    def to_i32(self) -> int:
        return int(self.value)


class ParseStartingAgeError(ValueError):
    def __init__(self, version: float, found: int):
        expected = "-1-4" if version < 1.25 else "-1-6"
        super().__init__(f"invalid starting age {found} (must be {expected})")
        self.version = float(version)
        self.found = int(found)


class StartingAge(Enum):
    Default = -1
    Nomad = -2
    DarkAge = 0
    FeudalAge = 1
    CastleAge = 2
    ImperialAge = 3
    PostImperialAge = 4

    @staticmethod
    def try_from(n: int, version: float) -> "StartingAge":
        n = int(n)
        if version < 1.25:
            if n == -1:
                return StartingAge.Default
            if n == 0:
                return StartingAge.DarkAge
            if n == 1:
                return StartingAge.FeudalAge
            if n == 2:
                return StartingAge.CastleAge
            if n == 3:
                return StartingAge.ImperialAge
            if n == 4:
                return StartingAge.PostImperialAge
            raise ParseStartingAgeError(version, n)
        else:
            if n in (-1, 0):
                return StartingAge.Default
            if n == 1:
                return StartingAge.Nomad
            if n == 2:
                return StartingAge.DarkAge
            if n == 3:
                return StartingAge.FeudalAge
            if n == 4:
                return StartingAge.CastleAge
            if n == 5:
                return StartingAge.ImperialAge
            if n == 6:
                return StartingAge.PostImperialAge
            raise ParseStartingAgeError(version, n)

    def to_i32(self, version: float) -> int:
        if version < 1.25:
            if self is StartingAge.Default:
                return -1
            if self in (StartingAge.Nomad, StartingAge.DarkAge):
                return 0
            if self is StartingAge.FeudalAge:
                return 1
            if self is StartingAge.CastleAge:
                return 2
            if self is StartingAge.ImperialAge:
                return 3
            if self is StartingAge.PostImperialAge:
                return 4
            raise AssertionError("unreachable")
        else:
            if self is StartingAge.Default:
                return 0
            if self is StartingAge.Nomad:
                return 1
            if self is StartingAge.DarkAge:
                return 2
            if self is StartingAge.FeudalAge:
                return 3
            if self is StartingAge.CastleAge:
                return 4
            if self is StartingAge.ImperialAge:
                return 5
            if self is StartingAge.PostImperialAge:
                return 6
            raise AssertionError("unreachable")


class VictoryCondition(Enum):
    Capture = 0
    Create = 1
    Destroy = 2
    DestroyMultiple = 3
    BringToArea = 4
    BringToObject = 5
    Attribute = 6
    Explore = 7
    CreateInArea = 8
    DestroyAll = 9
    DestroyPlayer = 10
    Points = 11
    Other = 255  # placeholder; real value stored separately


@dataclass(frozen=True, slots=True)
class VictoryConditionValue:
    kind: VictoryCondition
    other_raw: Optional[int] = None

    @staticmethod
    def from_u8(n: int) -> "VictoryConditionValue":
        n = int(n) & 0xFF
        mapping = {
            0: VictoryCondition.Capture,
            1: VictoryCondition.Create,
            2: VictoryCondition.Destroy,
            3: VictoryCondition.DestroyMultiple,
            4: VictoryCondition.BringToArea,
            5: VictoryCondition.BringToObject,
            6: VictoryCondition.Attribute,
            7: VictoryCondition.Explore,
            8: VictoryCondition.CreateInArea,
            9: VictoryCondition.DestroyAll,
            10: VictoryCondition.DestroyPlayer,
            11: VictoryCondition.Points,
        }
        if n in mapping:
            return VictoryConditionValue(mapping[n], None)
        return VictoryConditionValue(VictoryCondition.Other, n)

    def to_u8(self) -> int:
        if self.kind is VictoryCondition.Other:
            assert self.other_raw is not None
            return int(self.other_raw) & 0xFF
        return int(self.kind.value) & 0xFF


@dataclass(slots=True)
class VersionBundle:
    format: SCXVersion
    header: int
    dlc_options: Optional[int]
    data: float
    picture: int
    victory: float
    triggers: Optional[float]  # rust uses Option<f64>, but we hold as float
    map: int

    @staticmethod
    def ror() -> "VersionBundle":
        return VersionBundle(
            format=SCXVersion(b"1.11"),
            header=2,
            dlc_options=None,
            data=1.15,
            picture=1,
            victory=2.0,
            triggers=None,
            map=0,
        )

    @staticmethod
    def aok() -> "VersionBundle":
        return VersionBundle(
            format=SCXVersion(b"1.18"),
            header=2,
            dlc_options=None,
            data=1.2,
            picture=1,
            victory=2.0,
            triggers=1.6,
            map=0,
        )

    @staticmethod
    def aoc() -> "VersionBundle":
        return VersionBundle(
            format=SCXVersion(b"1.21"),
            header=2,
            dlc_options=None,
            data=1.22,
            picture=1,
            victory=2.0,
            triggers=1.6,
            map=0,
        )

    @staticmethod
    def userpatch_14() -> "VersionBundle":
        return VersionBundle.aoc()

    @staticmethod
    def userpatch_15() -> "VersionBundle":
        return VersionBundle.userpatch_14()

    @staticmethod
    def hd_edition() -> "VersionBundle":
        return VersionBundle(
            format=SCXVersion(b"1.21"),
            header=3,
            dlc_options=1000,
            data=1.26,
            picture=3,
            victory=2.0,
            triggers=1.6,
            map=0,
        )

    def is_aok(self) -> bool:
        return self.format.as_bytes() in (b"1.18", b"1.19", b"1.20")

    def is_aoc(self) -> bool:
        return self.format == b"1.21" and self.data <= 1.22

    def is_hd_edition(self) -> bool:
        # Rust precedence: (format == 1.21) || ((format == 1.22) && data > 1.22)
        return (self.format == b"1.21") or (self.format == b"1.22" and self.data > 1.22)
