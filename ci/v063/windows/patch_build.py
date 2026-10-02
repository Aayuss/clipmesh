# v063 Windows build integration.
#
# Executed by ci/patch-v063-ember-ui.py with the globals ROOT, PROJECT, LAYER,
# FONTS, replace_once, regex_once and install.
#
# Embeds the bundled Sora typeface into clipmesh.exe as manifest resources
# (ClipMesh.Font.SoraRegular/Medium/SemiBold/Bold). ClipMeshWindows.cs loads them
# at runtime with PrivateFontCollection.AddMemoryFont + AddFontMemResourceEx and
# falls back to Segoe UI when a resource is missing.

build = PROJECT / "scripts/build-windows.ps1"

for _font in FONTS:
    if not (LAYER / "fonts" / _font).is_file():
        raise SystemExit(f"v063 Windows build: missing font {_font}")

_names = {
    "sora_regular.ttf": "SoraRegular",
    "sora_medium.ttf": "SoraMedium",
    "sora_semibold.ttf": "SoraSemiBold",
    "sora_bold.ttf": "SoraBold",
}

_declarations = "".join(
    f"$font{_names[f]} = (Resolve-Path (Join-Path $PSScriptRoot '..\\..\\ci\\v063\\fonts\\{f}')).Path\n" for f in FONTS
)
_resources = "".join(
    f"    /resource:\"$font{_names[f]},ClipMesh.Font.{_names[f]}\" `\n" for f in FONTS
)

replace_once(
    build,
    "$pairingSource = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshNearbyPairing.cs'\n",
    "$pairingSource = Join-Path $PSScriptRoot '..\\..\\ci\\ClipMeshNearbyPairing.cs'\n" + _declarations,
    "v063 Windows font paths",
)

replace_once(
    build,
    "    /resource:\"$engine,ClipMesh.Engine\" `\n",
    "    /resource:\"$engine,ClipMesh.Engine\" `\n" + _resources,
    "v063 Windows font resources",
)

_text = build.read_text(encoding="utf-8")
for _name in _names.values():
    if f"ClipMesh.Font.{_name}" not in _text:
        raise SystemExit(f"v063 Windows build guard missing font resource {_name}")
