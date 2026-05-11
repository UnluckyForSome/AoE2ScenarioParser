## genie_rs (legacy bridge)

This tree is a **vendored upstream snapshot** of `genie-scx` / related crates, kept **only for human
reference** (diffing behaviour, struct layouts, historical parity notes). It is **not** part of the
supported runtime path for this fork.

### Active runtime

Legacy parsing and bridge conversion run **in-process** from the **`AOE2-McGenieSCX`** distribution
(`pip install` / project dependency) via `import aoe2_mcgeniescx`.  
`AoE2ScenarioParser/legacy_bridge/bridge_wireup.py` does **not** spawn Rust binaries.
