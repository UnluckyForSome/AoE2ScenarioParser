use base64::Engine;
use byteorder::{ReadBytesExt, LE};
use flate2::read::DeflateDecoder;
use genie_support::ReadStringsExt;
use serde::Serialize;
use std::io::{Read, Write};
use std::path::Path;

const BRIDGE_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Serialize)]
pub struct LegacyScenarioExportV1 {
    pub bridge_schema_version: u32,

    pub source_path: String,
    pub source_format: String,

    pub legacy_versions: serde_json::Value,

    pub filename: Option<String>,
    pub description: Option<String>,
    pub author_name: Option<String>,
    pub timestamp: Option<u32>,
    pub active_player_count: Option<u32>,

    pub map: serde_json::Value,
    pub objects: Vec<serde_json::Value>,
    pub world_players: Vec<serde_json::Value>,
    pub scenario_players: Vec<serde_json::Value>,
    pub triggers: Option<serde_json::Value>,

    pub raw: serde_json::Value,
}

pub fn export_legacy_scenario(
    source_path: &str,
    bytes: &[u8],
    include_raw: bool,
) -> anyhow::Result<LegacyScenarioExportV1> {
    // We parse in two layers:
    // - Use `Scenario::read_from` for high-level accessors (map/header/version bundle).
    // - Re-parse the compressed payload here to recover per-player object ownership, which is
    //   not exposed by the public `Scenario::objects()` iterator.
    let scen = match genie_scx::Scenario::read_from(bytes) {
        Ok(s) => s,
        Err(e) => {
            // Improve debuggability for rare parse failures (often string decode/misalignment).
            let header4 = bytes.get(0..4).unwrap_or_default();
            let header4_str = std::str::from_utf8(header4).unwrap_or("<non-utf8>");
            return Err(anyhow::anyhow!(
                "genie-scx Scenario::read_from failed (file_header={header4_str:?}): {e}\n\nDebug: {e:?}"
            ));
        }
    };
    let parsed_players_objects = parse_players_and_objects(bytes)?;

    let source_format = Path::new(source_path)
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();

    let version = scen.version();
    let legacy_versions = serde_json::json!({
        "format_version": version.format.to_string(),
        "header_version": version.header,
        "data_version": version.data,
    });

    let header = scen.header();

    let map = scen.map();
    let tiles: Vec<_> = map
        .tiles()
        .map(|t| {
            serde_json::json!({
                "terrain": t.terrain,
                "layered_terrain": t.layered_terrain,
                "elevation": t.elevation,
                "zone": t.zone,
            })
        })
        .collect();
    let map_json = serde_json::json!({
        "version": map.version(),
        "width": map.width(),
        "height": map.height(),
        "render_waves": null, // not exposed publicly by genie-scx; keep as null for now
        "tiles": tiles,
    });

    let mut objects: Vec<serde_json::Value> = vec![];
    for (player_id, list) in parsed_players_objects.player_objects.iter().enumerate() {
        for obj in list {
            let object_type: u16 = obj.object_type.into();
            objects.push(serde_json::json!({
                "player_id": player_id as u32,
                "position": [obj.position.0, obj.position.1, obj.position.2],
                "id": obj.id,
                "object_type": object_type,
                "state": obj.state,
                "angle": obj.angle,
                "frame": obj.frame,
                "garrisoned_in": obj.garrisoned_in,
            }));
        }
    }

    let world_players = parsed_players_objects.world_players;
    let scenario_players = parsed_players_objects.scenario_players;
    let victory = parsed_players_objects.victory;
    let diplomacy_matrix = parsed_players_objects.diplomacy_matrix;
    let individual_victories_bytes = parsed_players_objects.individual_victories_bytes;
    let options = parsed_players_objects.options;

    // Export trigger internals (best-effort structural export).
    let triggers = scen.triggers().map(|sys| {
        let trigger_list: Vec<serde_json::Value> = sys
            .triggers()
            .enumerate()
            .map(|(i, t)| {
                let conditions: Vec<serde_json::Value> = t
                    .conditions()
                    .map(|c| {
                        serde_json::json!({
                            "condition_type": c.condition_type_id(),
                            "properties": c.properties(),
                        })
                    })
                    .collect();

                let effects: Vec<serde_json::Value> = t
                    .effects()
                    .map(|e| {
                        serde_json::json!({
                            "effect_type": e.effect_type_id(),
                            "properties": e.properties(),
                            "chat_text": e.chat_text(),
                            "audio_file": e.audio_file(),
                            "objects": e.objects(),
                        })
                    })
                    .collect();

                serde_json::json!({
                    "trigger_index": i as u32,
                    "enabled": t.enabled(),
                    "looping": t.looping(),
                    "name_id": t.name_id(),
                    "is_objective": t.is_objective(),
                    "objective_order": t.objective_order(),
                    "start_time": t.start_time(),
                    "make_header": t.make_header(),
                    "mute_objective": t.mute_objective(),
                    "display_short_description": t.display_short_description(),
                    "short_description_state": t.short_description_state(),
                    "name": t.name(),
                    "description": t.description(),
                    "short_description": t.short_description(),
                    "condition_order": t.condition_order(),
                    "effect_order": t.effect_order(),
                    "conditions": conditions,
                    "effects": effects,
                })
            })
            .collect();

        // Variables: genie-scx only stores variable names/values for trigger versions >= 2.2.
        // DE uses a separate `VariableStruct` list for names; values are not currently mapped.
        let variable_names: Vec<serde_json::Value> = sys
            .variable_names()
            .iter()
            .enumerate()
            .filter(|(_i, name)| !name.is_empty())
            .map(|(i, name)| serde_json::json!({"variable_id": i as u32, "variable_name": name}))
            .collect();

        serde_json::json!({
            "trigger_version": sys.version(),
            "objectives_state": sys.objectives_state(),
            "num_triggers": sys.num_triggers(),
            "trigger_order": sys.trigger_order(),
            "triggers": trigger_list,
            "variables": {
                "names": variable_names,
                "values": sys.variable_values(),
                "enabled_techs": sys.enabled_techs(),
            },
        })
    });

    let raw = if include_raw {
        let b64 = base64::engine::general_purpose::STANDARD.encode(bytes);
        serde_json::json!({
            "full_file_base64": b64,
        })
    } else {
        serde_json::json!({})
    };

    Ok(LegacyScenarioExportV1 {
        bridge_schema_version: BRIDGE_SCHEMA_VERSION,
        source_path: source_path.to_string(),
        source_format,
        legacy_versions,
        filename: Some(scen.filename().to_string()),
        description: header.description.clone().map(|s| s.to_string()),
        author_name: header.author_name.clone().map(|s| s.to_string()),
        timestamp: Some(header.timestamp),
        active_player_count: Some(header.active_player_count),
        map: map_json,
        objects,
        world_players,
        scenario_players,
        triggers,
        raw: {
            let mut r = raw;
            if let Some(v) = victory {
                if let Some(obj) = r.as_object_mut() {
                    obj.insert("victory".to_string(), v);
                }
            }
            if let Some(m) = diplomacy_matrix {
                if let Some(obj) = r.as_object_mut() {
                    obj.insert("diplomacy_matrix".to_string(), serde_json::json!(m));
                }
            }
            if let Some(b) = individual_victories_bytes {
                if let Some(obj) = r.as_object_mut() {
                    obj.insert(
                        "individual_victories_base64".to_string(),
                        serde_json::json!(base64::engine::general_purpose::STANDARD.encode(b)),
                    );
                }
            }
            if let Some(o) = options {
                if let Some(obj) = r.as_object_mut() {
                    obj.insert("options".to_string(), o);
                }
            }
            if let Some(obj) = r.as_object_mut() {
                obj.insert(
                    "legacy_ai".to_string(),
                    parsed_players_objects.legacy_ai.clone(),
                );
            }
            r
        },
    })
}

#[derive(Debug)]
struct ParsedPlayersObjects {
    world_players: Vec<serde_json::Value>,
    scenario_players: Vec<serde_json::Value>,
    player_objects: Vec<Vec<genie_scx::ScenarioObject>>,
    victory: Option<serde_json::Value>,
    diplomacy_matrix: Option<Vec<Vec<i32>>>,
    individual_victories_bytes: Option<Vec<u8>>,
    options: Option<serde_json::Value>,
    legacy_ai: serde_json::Value,
}

fn legacy_ai_export_json(tribe: &genie_scx::TribeScen, embedded: &[genie_scx::AIFile]) -> serde_json::Value {
    let filenames: Vec<Option<&str>> = tribe
        .legacy_ai_filenames()
        .iter()
        .take(16)
        .map(|o| o.as_deref())
        .collect();
    let scripts = tribe.legacy_ai_script_contents();
    let types: Vec<i32> = tribe
        .legacy_ai_rules_types()
        .iter()
        .take(16)
        .copied()
        .map(|x| i32::from(x))
        .collect();
    let embedded_files: Vec<serde_json::Value> = embedded
        .iter()
        .map(|f| {
            serde_json::json!({
                "filename": f.filename(),
                "content": f.content(),
            })
        })
        .collect();
    serde_json::json!({
        "player_filenames": filenames,
        "player_scripts": scripts,
        "player_ai_types": types,
        "embedded_files": embedded_files,
    })
}

fn parse_players_and_objects(bytes: &[u8]) -> anyhow::Result<ParsedPlayersObjects> {
    // This intentionally mirrors `genie-scx`'s internal read order (see crate `format.rs`).
    // We only parse up to the per-player object lists.
    // Use `Scenario` to obtain the parsed format version (SCXVersion) since its constructor is not public.
    let scen = genie_scx::Scenario::read_from(bytes)?;
    let format_version = scen.version().format;
    let player_version = player_version_from_format_string(&format_version.to_string())
        .ok_or_else(|| anyhow::anyhow!("Unsupported format version: {}", format_version))?;

    let mut cursor = std::io::Cursor::new(bytes);
    // Consume container version bytes (already known from `format_version`).
    let _ = cursor.read_u32::<LE>()?;

    let _header = genie_scx::SCXHeader::read_from(&mut cursor, format_version)?;

    // Remaining data is deflate-compressed (raw DEFLATE stream).
    let mut decoder = DeflateDecoder::new(cursor);

    let _next_object_id = decoder.read_i32::<LE>()?;

    // Scenario data + map
    //
    // Victory settings + full diplomacy live inside the compressed payload before the map.
    // `genie-scx` does parse them, but does not expose them via public getters (TribeScen fields are private).
    //
    // To keep the bridge self-contained (without forking genie-scx), we recover these blocks by scanning the
    // decompressed payload for the distinctive `-99` separator and validating the following structure.
    let data_version = scen.version().data;
    let (victory, diplomacy_matrix, options) = scan_decompressed_for_tribe_scen_settings(bytes, data_version)?;

    // Still consume TribeScen in-stream so the subsequent map/player parsing is aligned.
    let tribe_scen = genie_scx::TribeScen::read_from(&mut decoder)?;
    let _map = genie_scx::Map::read_from(&mut decoder)?;

    // Players
    let num_players = decoder.read_u32::<LE>()?;

    // World player data exists for players 1..num_players (gaia excluded). We read the raw floats
    // here to avoid relying on private fields in `WorldPlayerData`.
    let mut world_players: Vec<serde_json::Value> = vec![];
    for player_id in 1..num_players {
        let mut food = 200.0f32;
        let mut wood = 200.0f32;
        let mut gold = 50.0f32;
        let mut stone = 100.0f32;
        let mut ore = 100.0f32;
        let mut goods = 0.0f32;
        let mut population = 75.0f32;

        if player_version > 1.06 {
            food = decoder.read_f32::<LE>()?;
            wood = decoder.read_f32::<LE>()?;
            gold = decoder.read_f32::<LE>()?;
            stone = decoder.read_f32::<LE>()?;
        }
        if player_version > 1.12 {
            ore = decoder.read_f32::<LE>()?;
            goods = decoder.read_f32::<LE>()?;
        }
        if player_version >= 1.14 {
            population = decoder.read_f32::<LE>()?;
        }

        world_players.push(serde_json::json!({
            "player_id": player_id,
            "food": food,
            "wood": wood,
            "gold": gold,
            "stone": stone,
            "ore": ore,
            "goods": goods,
            "population": population,
        }));
    }

    // Scenario players vs objects order depends on format_version.
    let mut scenario_players: Vec<serde_json::Value> = vec![];
    // (scenario player id, raw victory-condition blob). DE stores 16×720 bytes indexed by player slot id
    // (0 = Gaia unused, 1..8 = human slots); sequential packing was wrong for slot 0 vs P1.
    let mut scenario_player_victory_segments: Vec<(u32, Vec<u8>)> = vec![];

    let player_objects = if format_is_at_least(&format_version.to_string(), 1, 36) {
        // scenario players first
        let scenario_player_count = decoder.read_u32::<LE>()?;
        for player_id in 1..scenario_player_count {
            let (p, victory_segment) = read_scenario_player_with_victory(&mut decoder, player_version)?;
            scenario_players.push(serde_json::json!({
                "player_id": player_id,
                "name": p.name.as_ref().map(|s| s.as_str()),
                "view": [p.view.0, p.view.1],
                "location": [p.location.0, p.location.1],
                "allied_victory": p.allied_victory,
                "relations": p.relations,
                "unit_diplomacy": p.unit_diplomacy,
                "color": p.color,
                "victory_conditions": p.victory_json,
            }));
            scenario_player_victory_segments.push((player_id, victory_segment));
        }
        read_player_objects(&mut decoder, num_players, format_version)?
    } else {
        // objects first
        let objs = read_player_objects(&mut decoder, num_players, format_version)?;
        let scenario_player_count = decoder.read_u32::<LE>()?;
        for player_id in 1..scenario_player_count {
            let (p, victory_segment) = read_scenario_player_with_victory(&mut decoder, player_version)?;
            scenario_players.push(serde_json::json!({
                "player_id": player_id,
                "name": p.name.as_ref().map(|s| s.as_str()),
                "view": [p.view.0, p.view.1],
                "location": [p.location.0, p.location.1],
                "allied_victory": p.allied_victory,
                "relations": p.relations,
                "unit_diplomacy": p.unit_diplomacy,
                "color": p.color,
                "victory_conditions": p.victory_json,
            }));
            scenario_player_victory_segments.push((player_id, victory_segment));
        }
        objs
    };

    // Encode per-player VictoryConditions into DE's `Diplomacy.individual_victories` 11520-byte block:
    // 16 fixed segments of 720 bytes; segment index == scenario player id (Gaia slot stays zero).
    let individual_victories_bytes = if !scenario_player_victory_segments.is_empty() {
        let mut out: Vec<u8> = vec![0u8; 16 * 720];
        for (player_id, seg) in scenario_player_victory_segments.into_iter() {
            let pid = player_id as usize;
            if pid >= 16 {
                continue;
            }
            let start = pid * 720;
            let copy_len = std::cmp::min(720, seg.len());
            out[start..start + copy_len].copy_from_slice(&seg[..copy_len]);
        }
        Some(out)
    } else {
        None
    };

    // Triggers + embedded AI tail (same order as genie-scx `SCXFormat::load_inner`).
    let mut embedded_ai_files: Vec<genie_scx::AIFile> = Vec::new();
    let fv = format_version.to_string();
    if format_is_at_least(&fv, 1, 14) {
        let _ = genie_scx::TriggerSystem::read_from(&mut decoder)?;
    }
    // Mirrors genie-scx: AI tail exists for `> 1.17 && < 2.00` (avoid private `SCXVersion` ctor here).
    if format_is_at_least(&fv, 1, 18) && !fv.starts_with("2.") {
        if let Ok(Some(info)) = genie_scx::AIInfo::read_from(&mut decoder) {
            embedded_ai_files.extend(info.files().iter().cloned());
        }
    }

    let legacy_ai = legacy_ai_export_json(&tribe_scen, &embedded_ai_files);

    Ok(ParsedPlayersObjects {
        world_players,
        scenario_players,
        player_objects,
        victory,
        diplomacy_matrix,
        individual_victories_bytes,
        options,
        legacy_ai,
    })
}

#[derive(Debug)]
struct ScenarioPlayerExport {
    name: Option<String>,
    view: (f32, f32),
    location: (i16, i16),
    allied_victory: bool,
    relations: Vec<i8>,
    unit_diplomacy: Vec<i32>,
    color: Option<i32>,
    victory_json: serde_json::Value,
}

fn read_scenario_player_with_victory(
    input: &mut impl Read,
    player_version: f32,
) -> anyhow::Result<(ScenarioPlayerExport, Vec<u8>)> {
    let name = input.read_u16_length_prefixed_str()?.map(|s| s.to_string());
    let view = (input.read_f32::<LE>()?, input.read_f32::<LE>()?);
    let location = (input.read_i16::<LE>()?, input.read_i16::<LE>()?);

    let allied_victory = if player_version > 1.0 { input.read_u8()? != 0 } else { false };

    let diplo_count = input.read_i16::<LE>()?;
    let mut relations: Vec<i8> = Vec::with_capacity(diplo_count as usize);
    for _ in 0..diplo_count {
        relations.push(input.read_i8()?);
    }

    let unit_diplomacy: Vec<i32> = if player_version >= 1.08 {
        (0..9).map(|_| input.read_i32::<LE>()).collect::<Result<_, _>>()?
    } else {
        vec![0; 9]
    };

    let color: Option<i32> = if player_version >= 1.13 {
        Some(input.read_i32::<LE>()?)
    } else {
        None
    };

    // VictoryConditions block:
    let (victory_json, victory_bytes) = read_and_encode_victory_conditions(input, player_version >= 1.09)?;

    Ok((
        ScenarioPlayerExport {
            name,
            view,
            location,
            allied_victory,
            relations,
            unit_diplomacy,
            color,
            victory_json,
        },
        victory_bytes,
    ))
}

fn read_and_encode_victory_conditions(
    input: &mut impl Read,
    has_version: bool,
) -> anyhow::Result<(serde_json::Value, Vec<u8>)> {
    // Read into structured fields while also encoding into the on-disk format.
    let mut buf: Vec<u8> = vec![];

    // version
    let version = if has_version {
        let v = input.read_f32::<LE>()?;
        buf.write_all(&v.to_le_bytes())?;
        v
    } else {
        0.0
    };

    let num_conditions = input.read_i32::<LE>()?;
    buf.write_all(&num_conditions.to_le_bytes())?;
    let victory_state = input.read_u8()?;
    buf.push(victory_state);

    let mut entries: Vec<serde_json::Value> = Vec::with_capacity(num_conditions as usize);
    for _ in 0..num_conditions {
        let command = input.read_u8()?;
        let object_type = input.read_i32::<LE>()?;
        let player_id = input.read_i32::<LE>()?;
        let x0 = input.read_f32::<LE>()?;
        let y0 = input.read_f32::<LE>()?;
        let x1 = input.read_f32::<LE>()?;
        let y1 = input.read_f32::<LE>()?;
        let number = input.read_i32::<LE>()?;
        let count = input.read_i32::<LE>()?;
        let source_object = input.read_i32::<LE>()?;
        let target_object = input.read_i32::<LE>()?;
        let victory_group = input.read_i8()?;
        let ally_flag = input.read_i8()?;
        let state = input.read_i8()?;

        buf.push(command);
        buf.write_all(&object_type.to_le_bytes())?;
        buf.write_all(&player_id.to_le_bytes())?;
        buf.write_all(&x0.to_le_bytes())?;
        buf.write_all(&y0.to_le_bytes())?;
        buf.write_all(&x1.to_le_bytes())?;
        buf.write_all(&y1.to_le_bytes())?;
        buf.write_all(&number.to_le_bytes())?;
        buf.write_all(&count.to_le_bytes())?;
        buf.write_all(&source_object.to_le_bytes())?;
        buf.write_all(&target_object.to_le_bytes())?;
        buf.push(victory_group as u8);
        buf.push(ally_flag as u8);
        buf.push(state as u8);

        entries.push(serde_json::json!({
            "command": command,
            "object_type": object_type,
            "player_id": player_id,
            "area": [x0, y0, x1, y1],
            "number": number,
            "count": count,
            "source_object": source_object,
            "target_object": target_object,
            "victory_group": victory_group,
            "ally_flag": ally_flag,
            "state": state,
        }));
    }

    let mut total_points: i32 = 0;
    let mut point_entries: Vec<serde_json::Value> = vec![];
    if version >= 1.0 {
        total_points = input.read_i32::<LE>()?;
        let num_point_entries = input.read_i32::<LE>()?;
        buf.write_all(&total_points.to_le_bytes())?;
        buf.write_all(&num_point_entries.to_le_bytes())?;

        let mut starting_points: i32 = 0;
        let mut starting_group: i32 = 0;
        if version >= 2.0 {
            starting_points = input.read_i32::<LE>()?;
            starting_group = input.read_i32::<LE>()?;
            buf.write_all(&starting_points.to_le_bytes())?;
            buf.write_all(&starting_group.to_le_bytes())?;
        }

        for _ in 0..num_point_entries {
            let command = input.read_i8()?;
            let state = input.read_i8()?;
            let attribute = input.read_i32::<LE>()?;
            let amount = input.read_i32::<LE>()?;
            let points = input.read_i32::<LE>()?;
            let current_points = input.read_i32::<LE>()?;
            let id = input.read_i8()?;
            let group = input.read_i8()?;
            let current_attribute_amount = input.read_f32::<LE>()?;

            buf.push(command as u8);
            buf.push(state as u8);
            buf.write_all(&attribute.to_le_bytes())?;
            buf.write_all(&amount.to_le_bytes())?;
            buf.write_all(&points.to_le_bytes())?;
            buf.write_all(&current_points.to_le_bytes())?;
            buf.push(id as u8);
            buf.push(group as u8);
            buf.write_all(&current_attribute_amount.to_le_bytes())?;

            let mut attribute1 = -1;
            let mut current_attribute_amount1 = 0.0f32;
            if version >= 2.0 {
                attribute1 = input.read_i32::<LE>()?;
                current_attribute_amount1 = input.read_f32::<LE>()?;
                buf.write_all(&attribute1.to_le_bytes())?;
                buf.write_all(&current_attribute_amount1.to_le_bytes())?;
            }

            point_entries.push(serde_json::json!({
                "command": command,
                "state": state,
                "attribute": attribute,
                "amount": amount,
                "points": points,
                "current_points": current_points,
                "id": id,
                "group": group,
                "current_attribute_amount": current_attribute_amount,
                "attribute1": attribute1,
                "current_attribute_amount1": current_attribute_amount1,
            }));
        }
    }

    Ok((
        serde_json::json!({
            "version": version,
            "victory_state": victory_state,
            "total_points": total_points,
            "entries": entries,
            "point_entries": point_entries,
        }),
        buf,
    ))
}

fn scan_decompressed_for_tribe_scen_settings(
    bytes: &[u8],
    tribe_version: f32,
) -> anyhow::Result<(
    Option<serde_json::Value>,
    Option<Vec<Vec<i32>>>,
    Option<serde_json::Value>,
)> {
    // Decompress payload (same as AoE2ScenarioParser: raw DEFLATE stream after SCXHeader).
    let mut cursor = std::io::Cursor::new(bytes);
    let _ = cursor.read_u32::<LE>()?;
    let scen = genie_scx::Scenario::read_from(bytes)?;
    let format_version = scen.version().format;
    let _ = genie_scx::SCXHeader::read_from(&mut cursor, format_version)?;

    let mut decoder = DeflateDecoder::new(cursor);
    let mut decompressed = vec![];
    decoder.read_to_end(&mut decompressed)?;

    // Parse RGEScen text blocks (instructions/hints/victory/loss/history/scout + cinematics) from the
    // start of the decompressed payload. This is independent of the later victory/diplomacy scan.
    let rge_messages = parse_rge_messages_from_decompressed(&decompressed).ok();

    // Scan for separator -99 (i32 LE => 0x9D FF FF FF), then validate candidate structure.
    let sep = [0x9D, 0xFF, 0xFF, 0xFF];
    let mut idx = 0usize;
    while let Some(pos) = decompressed[idx..]
        .windows(4)
        .position(|w| w == sep)
        .map(|p| p + idx)
    {
        // Candidate starts right after sep.
        let start = pos + 4;
        if start + 4 * (6 + 1 + 3) + 4 * 16 * 16 > decompressed.len() {
            idx = start;
            continue;
        }

        let mut c = std::io::Cursor::new(&decompressed[start..]);

        let conquest = c.read_i32::<LE>().ok();
        let ruins = c.read_i32::<LE>().ok();
        let relics = c.read_i32::<LE>().ok();
        let discoveries = c.read_i32::<LE>().ok();
        let exploration = c.read_i32::<LE>().ok();
        let gold = c.read_i32::<LE>().ok();
        let all_flag = c.read_i32::<LE>().ok();
        let mp_victory_type = c.read_i32::<LE>().ok();
        let victory_score = c.read_i32::<LE>().ok();
        let victory_time = c.read_i32::<LE>().ok();

        if conquest.is_none()
            || ruins.is_none()
            || relics.is_none()
            || discoveries.is_none()
            || exploration.is_none()
            || gold.is_none()
            || all_flag.is_none()
            || mp_victory_type.is_none()
            || victory_score.is_none()
            || victory_time.is_none()
        {
            idx = start;
            continue;
        }

        let conquest = conquest.unwrap();
        let ruins = ruins.unwrap();
        let relics = relics.unwrap();
        let discoveries = discoveries.unwrap();
        let exploration = exploration.unwrap();
        let gold = gold.unwrap();
        let all_flag = all_flag.unwrap();
        let mp_victory_type = mp_victory_type.unwrap();
        let victory_score = victory_score.unwrap();
        let victory_time = victory_time.unwrap();

        // Plausibility checks
        if !matches!(conquest, 0 | 1) || !matches!(all_flag, 0 | 1) {
            idx = start;
            continue;
        }
        if ruins < 0
            || relics < 0
            || discoveries < 0
            || exploration < 0
            || gold < 0
            || exploration > 100
            || victory_score < 0
            || victory_time < 0
            || mp_victory_type < 0
            || mp_victory_type > 10
        {
            idx = start;
            continue;
        }

        // Read diplomacy matrix (16x16 i32). Values should be 0/1/3.
        let mut diplomacy_matrix: Vec<Vec<i32>> = Vec::with_capacity(16);
        let mut ok = true;
        for _row in 0..16 {
            let mut row = Vec::with_capacity(16);
            for _col in 0..16 {
                match c.read_i32::<LE>() {
                    Ok(v) if matches!(v, 0 | 1 | 3) => row.push(v),
                    _ => {
                        ok = false;
                        break;
                    }
                }
            }
            if !ok {
                break;
            }
            diplomacy_matrix.push(row);
        }
        if !ok || diplomacy_matrix.len() != 16 {
            idx = start;
            continue;
        }

        let victory = serde_json::json!({
            "conquest_required": conquest,
            "ruins": ruins,
            "artifacts_required": relics,
            "discovery": discoveries,
            "explored_percent_of_map_required": exploration,
            "gold_required": gold,
            "all_custom_conditions_required": all_flag,
            "mode": mp_victory_type,
            "required_score_for_score_victory": victory_score,
            "time_for_timed_game_in_10ths_of_a_year": victory_time,
        });

        // After diplomacy matrix comes legacy_victory_info (16*12*60 bytes) for AoE2.
        // Then another -99 separator, then allied_victory[16], then a bunch of options.
        //
        // We best-effort parse those options here so Python can map them into DE `Options`/`Diplomacy`.
        let options = parse_options_after_diplomacy(
            &decompressed[start..],
            4 * (6 + 1 + 3) + 4 * 16 * 16,
            tribe_version,
        )
        .ok();

        let mut options = options.unwrap_or_else(|| serde_json::json!({}));
        if let Some(obj) = options.as_object_mut() {
            if let Some(msg) = rge_messages {
                obj.insert("rge_messages".to_string(), msg);
            }
        }

        return Ok((Some(victory), Some(diplomacy_matrix), Some(options)));
    }

    // No victory/diplomacy block found; still return RGEScen messages if available.
    if let Some(msg) = rge_messages {
        return Ok((None, None, Some(serde_json::json!({ "rge_messages": msg }))));
    }

    Ok((None, None, None))
}

fn parse_rge_messages_from_decompressed(decompressed: &[u8]) -> anyhow::Result<serde_json::Value> {
    // Decompressed payload begins with `next_object_id: i32`, then `TribeScen`, which begins with `RGEScen`.
    let mut c = std::io::Cursor::new(decompressed);
    let _next_object_id = c.read_i32::<LE>()?;

    let version = c.read_f32::<LE>()?;

    let mut player_names: Vec<String> = vec![String::new(); 16];
    let mut player_string_table: Vec<i64> = vec![-1; 16];
    let mut player_base_properties: Vec<serde_json::Value> = vec![];

    // player_names (16 * 256) if version > 1.13
    if version > 1.13 {
        let mut tmp = vec![0u8; 16 * 256];
        c.read_exact(&mut tmp)?;
        for i in 0..16 {
            let slice = &tmp[(i * 256)..((i + 1) * 256)];
            let nul = slice.iter().position(|b| *b == 0).unwrap_or(slice.len());
            let s = String::from_utf8_lossy(&slice[..nul]).to_string();
            player_names[i] = s;
        }
    }

    // player_string_table (16 * opt u32) if version > 1.16
    if version > 1.16 {
        for i in 0..16 {
            let raw = c.read_u32::<LE>()?;
            player_string_table[i] = if raw == 0xFFFF_FFFF { -1 } else { raw as i64 };
        }
    }

    // player_base_properties (16 * 4 i32) if version > 1.13
    if version > 1.13 {
        for pid in 1..=16 {
            let active = c.read_i32::<LE>()?;
            let player_type = c.read_i32::<LE>()?;
            let civilization = c.read_i32::<LE>()?;
            let posture = c.read_i32::<LE>()?;
            player_base_properties.push(serde_json::json!({
                "player_id": pid,
                "active": active,
                "player_type": player_type,
                "civilization": civilization,
                "posture": posture,
            }));
        }
    }

    // victory_conquest (u8) if version >= 1.07
    if version >= 1.07 {
        let _ = c.read_u8()?;
    }

    // timeline: i16,i16,f32 (always present in genie-scx RGEScen parser)
    let _ = c.read_i16::<LE>()?;
    let _ = c.read_i16::<LE>()?;
    let _ = c.read_f32::<LE>()?;

    // civ_lock (16*u32) if version >= 1.28
    if version >= 1.28 {
        let mut tmp = vec![0u8; 16 * 4];
        c.read_exact(&mut tmp)?;
    }

    // name (u16-len-prefixed string)
    let name = c.read_u16_length_prefixed_str()?.unwrap_or_default();

    // string table keys (opt u32) if version >= 1.16
    if version >= 1.16 {
        let mut tmp = vec![0u8; 5 * 4];
        c.read_exact(&mut tmp)?;
    }
    // scout_string_table if version >= 1.22
    if version >= 1.22 {
        let mut tmp = vec![0u8; 4];
        c.read_exact(&mut tmp)?;
    }

    let description = c.read_u16_length_prefixed_str()?.unwrap_or_default();

    let (hints, win_message, loss_message, history) = if version >= 1.11 {
        (
            c.read_u16_length_prefixed_str()?.unwrap_or_default(),
            c.read_u16_length_prefixed_str()?.unwrap_or_default(),
            c.read_u16_length_prefixed_str()?.unwrap_or_default(),
            c.read_u16_length_prefixed_str()?.unwrap_or_default(),
        )
    } else {
        (String::new(), String::new(), String::new(), String::new())
    };

    let scout = if version >= 1.22 {
        c.read_u16_length_prefixed_str()?.unwrap_or_default()
    } else {
        String::new()
    };

    let pregame_cinematic = c.read_u16_length_prefixed_str()?.unwrap_or_default();
    let victory_cinematic = c.read_u16_length_prefixed_str()?.unwrap_or_default();
    let loss_cinematic = c.read_u16_length_prefixed_str()?.unwrap_or_default();

    Ok(serde_json::json!({
        "version": version,
        "player_names": player_names,
        "player_string_table": player_string_table,
        "player_base_properties": player_base_properties,
        "name": name,
        "description": description,
        "hints": hints,
        "victory": win_message,
        "loss": loss_message,
        "history": history,
        "scouts": scout,
        "cinematics": {
            "pregame": pregame_cinematic,
            "victory": victory_cinematic,
            "loss": loss_cinematic,
        }
    }))
}

fn parse_options_after_diplomacy(
    tribe_block: &[u8],
    offset_after_diplomacy: usize,
    version: f32,
) -> anyhow::Result<serde_json::Value> {
    let mut c = std::io::Cursor::new(&tribe_block[offset_after_diplomacy..]);

    // legacy_victory_info (always present for AoE2 tribe versions we care about)
    // 16 players * 12 entries * 60 bytes each
    let legacy_victory_info_bytes = 16 * 12 * 60;
    if (c.get_ref().len() as i64) < (legacy_victory_info_bytes as i64) {
        anyhow::bail!("not enough bytes for legacy_victory_info");
    }
    let mut legacy_victory_info_raw = vec![0u8; legacy_victory_info_bytes];
    c.read_exact(&mut legacy_victory_info_raw)?;

    // sep -99 (>= 1.02)
    if version >= 1.02 {
        let sep = c.read_i32::<LE>()?;
        if sep != -99 {
            anyhow::bail!("expected -99 separator after legacy_victory_info, got {}", sep);
        }
    }

    // allied_victory: 16 i32
    let mut allied_victory: Vec<i32> = vec![];
    for _ in 0..16 {
        allied_victory.push(c.read_i32::<LE>()?);
    }

    // team flags
    let (teams_locked, can_change_teams, random_start_locations, max_teams) = if version >= 1.24 {
        (
            c.read_i8()? != 0,
            c.read_i8()? != 0,
            c.read_i8()? != 0,
            c.read_u8()?,
        )
    } else if (version - 1.23).abs() < 1e-6 {
        (c.read_i32::<LE>()? != 0, true, true, 4)
    } else {
        (false, true, true, 4)
    };

    // Disabled lists
    let mut num_disabled_techs = vec![0i32; 16];
    let mut disabled_techs: Vec<Vec<i32>> = vec![vec![]; 16];
    let mut num_disabled_units = vec![0i32; 16];
    let mut disabled_units: Vec<Vec<i32>> = vec![vec![]; 16];
    let mut num_disabled_buildings = vec![0i32; 16];
    let mut disabled_buildings: Vec<Vec<i32>> = vec![vec![]; 16];

    if version >= 1.28 {
        // not expected for legacy (<1.36), but keep for completeness
        for i in 0..16 {
            num_disabled_techs[i] = c.read_i32::<LE>()?;
        }
        for i in 0..16 {
            let n = num_disabled_techs[i].max(0) as usize;
            let mut v = vec![0i32; n];
            for j in 0..n {
                v[j] = c.read_i32::<LE>()?;
            }
            disabled_techs[i] = v;
        }
        for i in 0..16 {
            num_disabled_units[i] = c.read_i32::<LE>()?;
        }
        for i in 0..16 {
            let n = num_disabled_units[i].max(0) as usize;
            let mut v = vec![0i32; n];
            for j in 0..n {
                v[j] = c.read_i32::<LE>()?;
            }
            disabled_units[i] = v;
        }
        for i in 0..16 {
            num_disabled_buildings[i] = c.read_i32::<LE>()?;
        }
        for i in 0..16 {
            let n = num_disabled_buildings[i].max(0) as usize;
            let mut v = vec![0i32; n];
            for j in 0..n {
                v[j] = c.read_i32::<LE>()?;
            }
            disabled_buildings[i] = v;
        }
    } else if version >= 1.18 {
        for i in 0..16 {
            num_disabled_techs[i] = c.read_i32::<LE>()?;
        }
        for i in 0..16 {
            let mut v = vec![0i32; 30];
            for j in 0..30 {
                v[j] = c.read_i32::<LE>()?;
            }
            disabled_techs[i] = v[..(num_disabled_techs[i].max(0) as usize).min(v.len())]
                .iter()
                .copied()
                .filter(|x| *x > 0)
                .collect();
        }
        for i in 0..16 {
            num_disabled_units[i] = c.read_i32::<LE>()?;
        }
        for i in 0..16 {
            let mut v = vec![0i32; 30];
            for j in 0..30 {
                v[j] = c.read_i32::<LE>()?;
            }
            disabled_units[i] = v[..(num_disabled_units[i].max(0) as usize).min(v.len())]
                .iter()
                .copied()
                .filter(|x| *x > 0)
                .collect();
        }
        for i in 0..16 {
            num_disabled_buildings[i] = c.read_i32::<LE>()?;
        }
        let max_disabled_buildings = if version >= 1.25 { 30 } else { 20 };
        for i in 0..16 {
            let mut v = vec![0i32; max_disabled_buildings as usize];
            for j in 0..(max_disabled_buildings as usize) {
                v[j] = c.read_i32::<LE>()?;
            }
            disabled_buildings[i] =
                v[..(num_disabled_buildings[i].max(0) as usize).min(v.len())]
                    .iter()
                    .copied()
                    .filter(|x| *x > 0)
                    .collect();
        }
    } else {
        // Older versions not handled here
    }

    let combat_mode = if version > 1.04 { c.read_i32::<LE>()? } else { 0 };
    let (naval_mode, all_techs) = if version >= 1.12 {
        (c.read_i32::<LE>()?, c.read_i32::<LE>()? != 0)
    } else {
        (0, false)
    };

    // starting ages
    let mut player_start_ages: Vec<i32> = vec![-1; 16];
    if version > 1.05 {
        for i in 0..16 {
            player_start_ages[i] = c.read_i32::<LE>()?;
        }
    }

    if version >= 1.02 {
        let sep2 = c.read_i32::<LE>()?;
        if sep2 != -99 {
            anyhow::bail!("expected -99 separator before view/map_type, got {}", sep2);
        }
    }

    let view = if version >= 1.19 {
        Some((c.read_i32::<LE>()?, c.read_i32::<LE>()?))
    } else {
        None
    };

    let map_type = if version >= 1.21 {
        let id = c.read_i32::<LE>()?;
        if id == -2 || id == -1 { None } else { Some(id) }
    } else {
        None
    };

    let mut base_priorities: Vec<i32> = vec![0; 16];
    if version >= 1.24 {
        for i in 0..16 {
            base_priorities[i] = c.read_i8()? as i32;
        }
    }

    // Tail fields (later legacy/DE2 variants)
    let mut water_definition: Option<String> = None;
    let mut color_mood: Option<String> = None;
    let mut collide_and_correct: Option<bool> = None;
    let mut villager_force_drop: Option<bool> = None;

    if version >= 1.35 {
        // Duplicated trigger count (TriggerSystem reads it again later)
        let _ = c.read_u32::<LE>()?;
    }
    if version >= 1.30 {
        let _ = c.read_u16::<LE>()?; // string signature
        water_definition = c.read_u16_length_prefixed_str()?.map(|s| s.to_string());
    }
    if version >= 1.32 {
        let _ = c.read_u16::<LE>()?; // string signature
        color_mood = c.read_u16_length_prefixed_str()?.map(|s| s.to_string());
    }
    if version >= 1.36 {
        collide_and_correct = Some(c.read_u8()? != 0);
    }
    if version >= 1.37 {
        villager_force_drop = Some(c.read_u8()? != 0);
    }

    Ok(serde_json::json!({
        "legacy_victory_info_base64": base64::engine::general_purpose::STANDARD.encode(legacy_victory_info_raw),
        "allied_victory": allied_victory,
        "teams_locked": teams_locked,
        "can_change_teams": can_change_teams,
        "random_start_locations": random_start_locations,
        "max_teams": max_teams,
        "disabled_techs": disabled_techs,
        "disabled_units": disabled_units,
        "disabled_buildings": disabled_buildings,
        "combat_mode": combat_mode,
        "naval_mode": naval_mode,
        "all_techs": all_techs,
        "player_start_ages": player_start_ages,
        "view": view.map(|(x,y)| vec![x,y]),
        "map_type": map_type,
        "base_priorities": base_priorities,
        "water_definition": water_definition,
        "color_mood": color_mood,
        "collide_and_correct": collide_and_correct,
        "villager_force_drop": villager_force_drop,
    }))
}

fn read_player_objects(
    input: &mut impl Read,
    num_players: u32,
    version: genie_scx::SCXVersion,
) -> anyhow::Result<Vec<Vec<genie_scx::ScenarioObject>>> {
    let mut player_objects: Vec<Vec<genie_scx::ScenarioObject>> = Vec::with_capacity(num_players as usize);
    for _ in 0..num_players {
        let num_objects = input.read_u32::<LE>()?;
        let mut objects: Vec<genie_scx::ScenarioObject> = Vec::with_capacity(num_objects as usize);
        for _ in 0..num_objects {
            objects.push(genie_scx::ScenarioObject::read_from(&mut *input, version)?);
        }
        player_objects.push(objects);
    }
    Ok(player_objects)
}

fn format_is_at_least(format: &str, major: u32, minor: u32) -> bool {
    let (m, n) = match format.split_once('.') {
        Some((a, b)) => (a.parse::<u32>().ok(), b.parse::<u32>().ok()),
        None => (None, None),
    };
    match (m, n) {
        (Some(m), Some(n)) => (m, n) >= (major, minor),
        _ => false,
    }
}

fn player_version_from_format_string(format: &str) -> Option<f32> {
    // Copied from genie-scx `types.rs` mapping (private in crate).
    match format {
        "1.07" => Some(1.07),
        "1.09" | "1.10" | "1.11" => Some(1.11),
        "1.12" | "1.13" | "1.14" | "1.15" | "1.16" => Some(1.12),
        "1.18" | "1.19" => Some(1.13),
        "1.20" | "1.21" | "1.32" | "1.36" | "1.37" => Some(1.14),
        _ => None,
    }
}

