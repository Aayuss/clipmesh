$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$src = Join-Path $root "dist\windows\clipmesh.exe"
if (!(Test-Path $src)) { throw "Build first with scripts\build-windows.ps1" }
$dir = Join-Path $env:LOCALAPPDATA "ClipMesh"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Copy-Item $src (Join-Path $dir "clipmesh.exe") -Force
Write-Host "Installed: $dir\clipmesh.exe"
Write-Host "Initialize: & '$dir\clipmesh.exe' init --name 'My Windows PC'"
