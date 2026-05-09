use anyhow::Context;
use clap::Parser;
use genie_scx_bridge::export::export_legacy_scenario;
use std::fs::File;
use std::io::{self, Read};

#[derive(Parser, Debug)]
#[command(
    name = "genie_scx_bridge",
    about = "Export legacy AoE2 scenarios to a stable JSON model for AoE2ScenarioParser."
)]
struct Args {
    /// Path to a legacy scenario file (.scn/.scx/.aoescn/etc).
    input: String,

    /// Emit JSON pretty-printed.
    #[arg(long)]
    pretty: bool,

    /// Also include raw/unmapped blocks when available (best-effort).
    #[arg(long)]
    include_raw: bool,
}

fn main() -> anyhow::Result<()> {
    let args = Args::parse();

    let mut f = File::open(&args.input).with_context(|| format!("open input '{}'", args.input))?;
    let mut buf = Vec::new();
    f.read_to_end(&mut buf)
        .with_context(|| format!("read input '{}'", args.input))?;

    let export = export_legacy_scenario(&args.input, &buf, args.include_raw)
        .with_context(|| "export legacy scenario")?;

    if args.pretty {
        serde_json::to_writer_pretty(io::stdout(), &export)?;
    } else {
        serde_json::to_writer(io::stdout(), &export)?;
    }
    Ok(())
}
