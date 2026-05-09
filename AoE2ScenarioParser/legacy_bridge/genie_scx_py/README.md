## genie_scx_py

This directory is the pure-Python port of the Rust crate `genie-scx`, used by the legacy bridge.

### Layout

Sources live directly under `genie_scx_py/` (for example `genie_scx_py/ai.py`, `genie_scx_py/header.py`).
`bridge_wireup.py` adds `legacy_bridge/` to `sys.path` so `import genie_scx_py` resolves this folder as the package.

### Runtime status

- **Runtime path**: `AoE2ScenarioParser/legacy_bridge/bridge_wireup.py` reads legacy scenarios using `genie_scx_py.Scenario` from this directory (in-process; no subprocess).
- **Rust workspace**: `AoE2ScenarioParser/legacy_bridge/genie_rs/` is a **reference-only vendored copy** of upstream Rust sources; it is not invoked by the bridge.
