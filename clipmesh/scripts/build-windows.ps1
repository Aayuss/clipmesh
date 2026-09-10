$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "Install Rust from https://rustup.rs first" }
cargo build --release -p clipmesh
New-Item -ItemType Directory -Force -Path dist/windows | Out-Null
Copy-Item target/release/clipmesh.exe dist/windows/clipmesh.exe -Force
Write-Host "Built: dist/windows/clipmesh.exe"
