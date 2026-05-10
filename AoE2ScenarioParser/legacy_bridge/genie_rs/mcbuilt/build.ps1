# Build genie-scx (via genie_scx_bridge CLI) in release mode and copy the exe into this folder.
# Run from repo:  powershell -File AoE2ScenarioParser/legacy_bridge/genie_rs/mcbuilt/build.ps1
# Or:             .\mcbuilt\build.ps1   (from genie_rs)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$genieRs = Split-Path -Parent $here
Set-Location $genieRs

Write-Host "cargo build --release -p genie_scx_bridge (workspace: $genieRs)" -ForegroundColor Cyan
cargo build --release -p genie_scx_bridge
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$src = Join-Path $genieRs 'target/release/genie_scx_bridge.exe'
if (-not (Test-Path -LiteralPath $src)) {
    Write-Error "Expected binary not found: $src"
    exit 1
}
$dst = Join-Path $here 'genie_scx_bridge.exe'
Copy-Item -LiteralPath $src -Destination $dst -Force
Write-Host "Copied: $dst" -ForegroundColor Green
Write-Host "Example: .\genie_scx_bridge.exe `"\\server\share\scenario.scx`" --pretty" -ForegroundColor DarkGray
