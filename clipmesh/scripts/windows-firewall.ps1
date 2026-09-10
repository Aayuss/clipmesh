$ErrorActionPreference = "Stop"
$exe = Resolve-Path "$PSScriptRoot\..\dist\windows\clipmesh.exe"
Get-NetFirewallRule -DisplayName "ClipMesh TCP LAN" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -DisplayName "ClipMesh UDP LAN" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "ClipMesh TCP LAN" -Direction Inbound -Action Allow -Program $exe -Protocol TCP -LocalPort 41474 -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName "ClipMesh UDP LAN" -Direction Inbound -Action Allow -Program $exe -Protocol UDP -LocalPort 41473 -RemoteAddress LocalSubnet
Write-Host "ClipMesh firewall rules created for LocalSubnet only."
