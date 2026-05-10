## genie_rs (legacy bridge)

This tree is a **vendored upstream snapshot** of `genie-scx` / related crates, kept **only for human
reference** (diffing behaviour, struct layouts, historical parity notes). It is **not** part of the
supported runtime path for this fork.

### Active runtime

Legacy parsing and bridge conversion run **in-process** from the Python port under
`AoE2ScenarioParser/legacy_bridge/genie_scx_py/` via `import genie_scx_py`.  
`AoE2ScenarioParser/legacy_bridge/bridge_wireup.py` does **not** spawn Rust binaries.
