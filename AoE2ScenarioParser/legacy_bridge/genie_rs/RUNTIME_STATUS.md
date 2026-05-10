## genie_rs (legacy bridge)

This tree is a **vendored upstream snapshot** of `genie-scx` / related crates, kept **only for human
reference** (diffing behaviour, struct layouts, historical parity notes). It is **not** part of the
supported runtime path for this fork.

### Active runtime

Legacy parsing and bridge conversion run **in-process** from **`genie_scx_py`** vendored as a **git
submodule** at `AoE2ScenarioParser/legacy_bridge/genie-scx-py` (`import genie_scx_py`; upstream repo
[genie-scx-py](https://github.com/UnluckyForSome/genie-scx-py)).  
`AoE2ScenarioParser/legacy_bridge/bridge_wireup.py` does **not** spawn Rust binaries.

McMinimap under `legacy_bridge/workbench/othertools/aoe2mcminimap` is a **git submodule** pointing at
[AOE2-McMinimap](https://github.com/UnluckyForSome/AOE2-McMinimap).

After cloning this fork run:

`git submodule update --init --recursive`
