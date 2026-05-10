# SCX scenario binary layout (`genie-scx`)

This document describes the Age of Empires scenario (`.scn` / `.scx` / `.aoe2scenario`) layout as implemented by the Rust crate [`genie-scx`](genie_rs/crates/genie-scx) (`src/format.rs`, `header.rs`, `map.rs`, `player.rs`, `triggers.rs`, `victory.rs`, `bitmap.rs`, `ai.rs`, `types.rs`). All multi-byte integers are **little-endian**. Text is interpreted as **WINDOWS-1252** unless noted.

---

## File shell

| Field | Type | Description |
|-------|------|-------------|
| Version tag | `c4` | Four ASCII bytes, e.g. `1.21`. Parsed as `SCXVersion` (`types.rs`). Unsupported tags fail `to_player_version()`. |
| Header payload | see below | Uncompressed; length field prefixes inner bytes (`header.rs`). |
| Body | zlib/deflate | Compressed with `flate2` `DeflateEncoder` / `DeflateDecoder` (`format.rs`). Everything after the header is this stream. |

Known `SCXVersion` → internal **player/data `f32` version** mappings (`types.rs::SCXVersion::to_player_version`):

| Format tag | Data version `f32` |
|------------|-------------------|
| `1.07` | 1.07 |
| `1.09`–`1.11` | 1.11 |
| `1.12`–`1.16` | 1.12 |
| `1.18`–`1.19` | 1.13 |
| `1.20`, `1.21`, `1.32`, `1.36`, `1.37` | 1.14 |

---

## Primitive conventions

| Notation | Meaning |
|----------|---------|
| `u8`, `i8`, `u16`, `i16`, `u32`, `i32`, `f32`, `f64` | Fixed-width scalars. |
| `str16` | `u16` length (see below), then that many bytes (`read_u16_length_prefixed_str`). `0xFFFF` length ⇒ omitted optional string. |
| `str32` | `u32` length; `0xFFFFFFFF` ⇒ omitted optional (`read_u32_length_prefixed_str`). |
| `write_str` / `write_opt_str` (`genie-support`) | `str16`: length includes trailing NUL; encoded bytes + `0x00`. |
| `write_i32_str` | `str32` with NUL-terminated payload and length including NUL. |
| String key | `u32`; `0xFFFFFFFF` means “none” (`read_opt_u32` / `write_opt_string_key`). |
| Separator | `i32` value `-99` (`0xFFFFFF9D`) appears between major blocks in `RGEScen` / `TribeScen`. |

---

## Uncompressed header (`SCXHeader`, `header.rs`)

The file writes a **`u32` size** equal to the byte length of the following inner blob, then that blob:

| Field | Type | Condition | Description |
|-------|------|-----------|-------------|
| Inner version | `u32` | | Header schema version. ≥2 adds timestamp; ≥5 adds author + trigger placeholder. |
| Timestamp | `u32` | version ≥ 2 | Unix seconds. |
| Description | special | | If format tag is `3.13`: HD-style (`u16` signature `0x0A60`, `u16` len, bytes). Else: `str32`-style (`u32` length prefix + bytes + NUL). |
| Any SP victory | `u32` | | Non-zero = true. |
| Active player count | `u32` | | |
| DLC options | `DLCOptions` | version > 2 and format ≠ `3.13` | See below. |
| Author name | `str32` | version ≥ 5 | |
| Trigger count placeholder | `u32` | version ≥ 5 | Written as `0` (TODO in code). |

**`DLCOptions`:** `u32` structure version (writer uses `1000`), `i32` game data set (`0` base / `1` expansions), `u32` dependency count, then `i32` DLC id per entry (`types.rs` `DLCPackage`).

---

## Compressed stream overview (`SCXFormat::load_inner`, `format.rs`)

Order in the inflated buffer:

1. `i32` **next object ID**
2. **`TribeScen`** (engine scenario blob; starts with `RGEScen`)
3. **`Map`**
4. `u32` **player slot count** `P`
5. **`P − 1` × `WorldPlayerData`** (loop `1..P`)
6. **Either** (depends on format tag):
   - If format ≥ `1.36`: **`ScenarioPlayerData`** list, then **per-player object lists**
   - Else: **per-player object lists**, then **`ScenarioPlayerData`** list
7. **Triggers** — only if format tag ≥ `1.14`; otherwise absent
8. **`AIInfo`** — only if format tag **>** `1.17` **and** format tag **<** `2.00`

---

## `RGEScen` (embedded “engine” scenario, start of `TribeScen`)

`f32` **data version** is read first (`base.version`). Unless noted, “version” in this section means that float.

| Field | Type | Condition | Description |
|-------|------|-----------|-------------|
| Version | `f32` | | Stored as `base.version`. |
| Player names | `16 × str256` | version > 1.13 | Each **256 raw bytes** (`read_str(256)`), fixed slots. |
| Player string-table IDs | `16 × u32` | version > 1.16 | Optional keys (`read_opt_u32`). |
| Player base properties | `16 ×` struct | version > 1.13 | Per slot: `i32` active, `i32` player type, `i32` civilization, `i32` posture (`PlayerBaseProperties`). |
| Conquest victory flag | `u8` | version ≥ 1.07 | Non-zero = true; older defaults true. |
| Timeline stub | `i16`, `i16`, `f32` | | Reader asserts count `0`; asserts unused fields (debug). Writer emits `0`, `0`, `-1.0`. |
| Civ lock | `16 × u32` | version ≥ 1.28 | Reader reads; writer writes zeros. |
| Scenario filename | `str16` | | May be empty for embedded scenarios. |
| Message string IDs | `5 × string key` | version ≥ 1.16 | Description, hints, win, loss, history. |
| Scout string ID | `string key` | version ≥ 1.22 | |
| Messages (inline) | `str16` × N | | Description; if version ≥ 1.11 also hints, win, loss, history; if ≥ 1.22 scout. |
| Cinematics | `str16` × 3 | | Pregame, victory, loss. |
| Mission BMP filename | `str16` | version ≥ 1.09 | |
| Mission picture | `Bitmap` \| empty | version ≥ 1.10 | See **`bitmap.rs`**. If width/height positive: `BitmapInfo` + pixel bytes; else skip payload. |
| Build list filenames | `16 × str16` | | |
| City plan filenames | `16 × str16` | | |
| AI rules filenames | `16 × str16` | version ≥ 1.08 | |
| AI file payloads | `16 ×` struct | | Per slot: `i32` build-list byte length, `i32` city-plan length, `i32` ai-rules length if ≥ 1.08; then raw bytes for each non-empty section (`PlayerFiles`). |
| AI rules type | `16 × i8` | version ≥ 1.20 | |
| Separator | `i32` | version ≥ 1.02 | Must be `-99`. |

---

## `TribeScen` continuation (`format.rs` / `player.rs`)

After `RGEScen`, still **same compressed stream**, same `f32` version variable:

### Resources and reordering for old versions

If **version ≤ 1.13**, player names + base properties + **inline `PlayerStartResources`** per slot are read **here** (256-byte names, then per player: active, `PlayerStartResources`, type, civ, posture).

If **version > 1.13**, only **`16 × PlayerStartResources`** follows `RGEScen` (`PlayerStartResources::read_from`):

| Field | Type | Condition |
|-------|------|-----------|
| Gold, wood, food, stone | `i32` × 4 | |
| Ore, goods | `i32` × 2 | version ≥ 1.17 |
| Player color | `i32` | version ≥ 1.24 |

Then:

| Field | Type | Condition | Description |
|-------|------|-----------|-------------|
| Separator | `i32` | version ≥ 1.02 | `-99` |
| Global victory info | `VictoryInfo` | | See below. |
| Victory “all required” | `i32` | | Bool as `i32`. |
| MP victory type / score / time | `i32` × 3 | version ≥ 1.13 | Defaults used when older. |
| Diplomacy matrix | `16 × 16 × i32` | | Each value ∈ {0 ally, 1 neutral, 3 enemy} (`DiplomaticStance`). |
| Legacy per-player victories | `16 × 12 × LegacyVictoryInfo` | | AoE1-style entries (`victory.rs`). |
| Separator | `i32` | version ≥ 1.02 | `-99` |
| Allied victory flags | `16 × i32` | | |
| Team options | mixed | version ≥ 1.24 | `i8` teams locked, can change teams, random starts, `u8` max teams. Special case: exactly `1.23` uses `i32` for teams locked only. |
| Disabled techs/units/buildings | see below | | Layout depends on version band (fixed 20 slots, 30 slots, or variable-length per player for DE). |
| Combat mode | `i32` | version > 1.04 | |
| Naval mode, all techs | `i32`, `i32` | version ≥ 1.12 | Second is bool. |
| Starting ages | `16 × i32` | version > 1.05 | Interpreted as `StartingAge` (`types.rs`). |
| Separator | `i32` | version ≥ 1.02 | `-99` |
| Editor camera | `i32`, `i32` | version ≥ 1.19 | Y, X order in file. |
| Map type | `i32` | version ≥ 1.21 | `-1`/`-2` treated as none. |
| Base priorities | `16 × i8` | version ≥ 1.24 | |
| Duplicate trigger count | `u32` | data version ≥ **1.35** (read) | Discarded; writer emits count at ≥ **1.28** (see note below). |
| Water definition | `u16` + `str16` | data version ≥ 1.30 | Leading `u16` treated as signature; then water string. |
| Color mood | `u16` + `str16` | data version ≥ 1.32 | |
| Collide-and-correct | `u8` | data version ≥ 1.36 | |
| Villager force drop | `u8` | data version ≥ 1.37 | |

**Disabled tech/unit/building bands** (`format.rs`):

- **> 1.03 and < 1.18:** only techs: `16 × 20 × i32`; counts inferred by scanning for non-positive sentinel.
- **≥ 1.18 and < 1.28:** counts `16 × i32` each, then fixed arrays per player (30 techs, 30 units, 20 or 30 buildings depending on version).
- **≥ 1.28:** counts then exactly **N × `i32`** per category per player.

---

### `VictoryInfo` (global rules)

| Field | Type |
|-------|------|
| Conquest required | `i32` (bool) |
| Ruins count | `i32` |
| Relics count | `i32` |
| Discoveries count | `i32` |
| Exploration percent | `i32` |
| Gold amount | `i32` |

### `LegacyVictoryInfo` (12 per player)

`i32` fields, `f32` rectangle, more `i32`, plus two `u32` zero placeholders (`victory.rs`).

---

## `Map` (`map.rs`)

| Field | Type | Description |
|-------|------|-------------|
| Leader | `u32` | If `0xDEADF00D`, extended header follows; else this value is **width** (legacy). |
| Map version | `u32` | Present when leader was `0xDEADF00D`. |
| Render waves | `u8` | If map version ≥ 2: stored inverted (“do not render” flag). |
| Width, height | `u32`, `u32` | |
| Tiles | `width × height` × `Tile` | Row-major; inner loops **y** then **x** in reader (`height` outer, `width` inner). |

**`Tile`:**

| Field | Type | Condition |
|-------|------|-----------|
| Terrain id | `u8` | |
| Elevation | `i8` | |
| Zone | `i8` | |
| Mask type | `u16` | map version ≥ 1; optional (`0xFFFF`) |
| Layered terrain | `u16` | map version ≥ 1; optional |

---

## `WorldPlayerData` (`player.rs`)

Per slot after first player row (`f32` **player version**):

| Field | Condition |
|-------|-----------|
| Food, wood, gold, stone | `f32` × 4 if version > 1.06 |
| Ore, goods | `f32` × 2 if version > 1.12 |
| Population cap | `f32` if version ≥ 1.14 |

---

## Placed objects (`ScenarioObject`, `format.rs`)

Per player: `u32` count, then count ×:

| Field | Type | Condition |
|-------|------|-----------|
| Position X,Y,Z | `f32` × 3 | |
| ID | `i32` | |
| Unit type | `u16` | |
| State | `u8` | |
| Angle | `f32` | |
| Animation frame | `i16` | format tag > `1.14` |
| Garrison host ID | `i32` | format tag > `1.12`; `-1` / `0` ⇒ none depending on version |

---

## `ScenarioPlayerData` (`player.rs` + `victory.rs`)

List length `N` is stored as **`u32` = inner count + 1**; reader loops **`1..N`**.

| Field | Type | Condition |
|-------|------|-----------|
| Name | `str16` | |
| View X,Y | `f32` × 2 | |
| Location | `i16` × 2 | |
| Allied victory | `u8` | player version > 1.0 |
| Diplomacy row length | `i16` | Then that many `i8` stance bytes. |
| Unit diplomacy | `9 × i32` | player version ≥ 1.08 |
| Color | `i32` | player version ≥ 1.13 |
| Victory conditions | `VictoryConditions` | Optional inner `f32` version if player version ≥ 1.09 |

**`VictoryConditions`:** optional leading `f32` version; `i32` entry count; `u8` state; repeated `VictoryEntry`; if version ≥ 1.0, total points, point-entry count, optional starting fields if version ≥ 2.0, then `VictoryPointEntry` list (`victory.rs`).

---

## `TriggerSystem` (`triggers.rs`)

Only present when format tag ≥ `1.14`. Starts with **`f64` trigger-system version**, then:

| Field | Type | Condition |
|-------|------|-----------|
| Objectives state | `i8` | version ≥ 1.5 |
| Trigger count | `i32` | |
| Triggers | variable | Each `Trigger`. |
| Display order | `count × i32` | system version ≥ 1.4 |
| Variable values | `256 × u32` | system version ≥ 2.2 |
| Enabled tech list | `u32` count + ids | ≥ 2.2 |
| Custom variable names | `u32` count + (id, `str32`) pairs | ≥ 2.2 |

### `Trigger`

| Field | Type | Condition |
|-------|------|-----------|
| Enabled | `i32` (bool) | |
| Looping | `i8` | |
| Name string-table ID | `i32` | |
| Objective flag | `i8` | |
| Objective order | `i32` | |
| DE objective header fields | `u8`, string key, `u8` ×2, `u32`, `u8` | system version ≥ 1.8 |
| Start time | `u32` | if &lt; 1.8, read earlier without DE fields |
| Description, name, short description | `str32` | Short description only if ≥ 1.8 |
| Effect count | `u32` | Then effects, then `count × i32` effect order |
| Condition count | `u32` | Then conditions, then `count × i32` condition order |

### `TriggerEffect`

| Field | Type | Condition |
|-------|------|-----------|
| Type | `i32` | |
| Property count | `i32` | version > 1.0; else **16** fixed `i32` values |
| Properties | `count × i32` | Padded internally to 24 slots |
| Chat text, sound file | `str32` × 2 | |
| Selected object IDs | `N × i32` | version > 1.1: **N** = properties[4]; older stores single id in properties |

### `TriggerCondition`

| Field | Type | Condition |
|-------|------|-----------|
| Type | `i32` | |
| Property count | `i32` | version > 1.0; else **13** fixed |
| Properties | `count × i32` | Padded to 18 slots |

---

## `Bitmap` / `BitmapInfo` (`bitmap.rs`)

When embedded: `u32` own-memory flag, `u32` width/height, `u16` orientation. If width and height **both positive**: full **BITMAPINFOHEADER-style** header (`BitmapInfo`: header fields + **256 × RGBA** palette entries), then raw pixel bytes sized by `height * ((width + 3) & !3)` (reader).

---

## `AIInfo` (`ai.rs`)

When present (see shell overview):

| Field | Type | Description |
|-------|------|-------------|
| Has embedded files | `u32` | Non-zero ⇒ AI files section expected |
| Has PER error | `u32` | Non-zero ⇒ error blob follows |

If **both** flags zero at read start, parser returns **no `AIInfo`** and reads nothing else.

Otherwise:

| Field | Type | Condition |
|-------|------|-----------|
| Error record | `AIErrorInfo` | if error flag |
| AI file count | `u32` | |
| Files | count × `AIFile` | Each: `str32` filename, `str32` content |

**`AIErrorInfo`:** `257` bytes filename data, `i32` line number, `128` bytes description, `u32` error code (`AIErrorCode` enum).

---

## Implementation notes

- **Separator:** `-99` (`i32`) matches historical community docs (`0xFFFFFF9D`).
- **Trigger count duplication:** `TribeScen::write_to` writes `u32` trigger count when data version ≥ **1.28**; `read_from` only skips an extra **`u32`** when data version ≥ **1.35**. The crate comment notes DE duplicates this field relative to `TriggerSystem`.
- **DE tail fields:** Read order for water/color/collide flags follows `TribeScen::read_from`; `write_to` bundles some fields differently—round-trip fidelity should be validated against target game builds when modifying writers.

---

## References in-tree

- Crate root: `genie_rs/crates/genie-scx/`
- Primary loader: `src/format.rs` (`SCXFormat::load_scenario`, `load_inner`, `RGEScen`, `TribeScen`)
- Strings: `genie_rs/crates/genie-support/src/strings.rs`
