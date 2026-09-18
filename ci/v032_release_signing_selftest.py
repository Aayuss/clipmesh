from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())
workflow = (root / ".github/workflows/build.yml").read_text(encoding="utf-8")
release_workflow = (root / ".github/workflows/release-v0.2.20.yml").read_text(encoding="utf-8")
fixed_gradle = (root / "ci/android-app-build.gradle.kts.fixed").read_text(encoding="utf-8")
android_script = (root / "ci/build-android-release.sh").read_text(encoding="utf-8")
mac_script = (root / "ci/macos-release-signing.sh").read_text(encoding="utf-8")
dev_script = (root / "dev-test.sh").read_text(encoding="utf-8")
docs = (root / "RELEASE_SIGNING.md").read_text(encoding="utf-8")
readme = (root / "README.md").read_text(encoding="utf-8")
setup_script = (root / "scripts/setup-android-release-signing.sh").read_text(encoding="utf-8")
ignore_rules = (root / ".gitignore").read_text(encoding="utf-8")
reconstruct = (root / "ci/reconstruct.py").read_text(encoding="utf-8")
previous_release_patch = (root / "ci/patch-v051-release.py").read_text(encoding="utf-8")
release_patch = (root / "ci/patch-v056-release.py").read_text(encoding="utf-8")

CURRENT_VERSION = "0.2.20"
CURRENT_CODE = "30"
CURRENT_TAG = "v0.2.20-alpha"
BASE_VERSION = "0.2.11"
BASE_CODE = "21"
VERIFIED_PRODUCT_VERSION = "0.2.12"
VERIFIED_PRODUCT_CODE = "22"

# Android release signing must remain fail-closed and use the permanent key.
for name in (
    "CLIPMESH_ANDROID_KEYSTORE_PATH",
    "CLIPMESH_ANDROID_KEYSTORE_PASSWORD",
    "CLIPMESH_ANDROID_KEY_ALIAS",
    "CLIPMESH_ANDROID_KEY_PASSWORD",
):
    assert name in fixed_gradle
assert "releaseTaskRequested" in fixed_gradle
assert 'signingConfig = signingConfigs.getByName("release")' in fixed_gradle
assert "Release signing is mandatory" in fixed_gradle

for name in (
    "CLIPMESH_ANDROID_KEYSTORE_B64",
    "CLIPMESH_ANDROID_KEYSTORE_PASSWORD",
    "CLIPMESH_ANDROID_KEY_ALIAS",
    "CLIPMESH_ANDROID_KEY_PASSWORD",
    "CLIPMESH_ANDROID_SIGNING_CERT_SHA256",
):
    assert name in workflow
    assert name in android_script

for guard in (
    "apksigner",
    "--print-certs",
    "Signer #1 certificate SHA-256 digest",
    "V2 Signer: certificate SHA-256 digest",
    "reported_certificate_count",
    "manifest application-id",
    "manifest version-name",
    "manifest version-code",
    "ClipMesh-release.apk",
    "trap cleanup EXIT INT TERM",
):
    assert guard in android_script

for forbidden_component in (
    "dev.clipmesh.CiBackgroundCaptureReceiver",
    "dev.clipmesh.DevTestReceiver",
    "dev.clipmesh.DevTestFileProvider",
    "dev.clipmesh.testdriver",
):
    assert forbidden_component in android_script

# Canonical CI must build the same current generation on all three platforms.
for target in ("Darwin", "Windows", "Linux"):
    assert f"python ci/reconstruct.py --platform {target}" in workflow
assert workflow.count("python ci/patch-v036-release.py") == 3
assert workflow.count("python ci/patch-v046-release.py") == 3
assert workflow.count("python ci/patch-v048-release.py") == 3
assert workflow.count("python ci/patch-v051-release.py") == 3
assert workflow.count("python ci/patch-v056-release.py") == 3
assert f"CLIPMESH_ANDROID_EXPECTED_VERSION_NAME: {CURRENT_VERSION}" in workflow
assert f"CLIPMESH_ANDROID_EXPECTED_VERSION_CODE: '{CURRENT_CODE}'" in workflow
assert f"versionCode = {CURRENT_CODE}" in workflow
assert f'versionName = "{CURRENT_VERSION}"' in workflow
assert f'^version = "{CURRENT_VERSION}"$' in workflow

assert f"name: Release ClipMesh v{CURRENT_VERSION}" in release_workflow
assert f"RELEASE_VERSION: {CURRENT_VERSION}" in release_workflow
assert f"RELEASE_TAG: {CURRENT_TAG}" in release_workflow
assert release_workflow.count("python ci/patch-v046-release.py") == 3
assert release_workflow.count("python ci/patch-v048-release.py") == 3
assert release_workflow.count("python ci/patch-v051-release.py") == 3
assert release_workflow.count("python ci/patch-v056-release.py") == 3
assert f"versionCode = {CURRENT_CODE}" in release_workflow
assert f'versionName = "{CURRENT_VERSION}"' in release_workflow
assert "a373fba1f5a8753123f0fa96a5400f3838ae4eb6" in release_workflow

# README download metadata must point at both the immutable current release and
# the continuously refreshed green development release.
assert readme.startswith("# ClipMesh\n")
download_section = readme.split("## Download", 1)[1].split("\n## ", 1)[0]
for asset_name in (
    "ClipMesh-macOS.dmg",
    "ClipMesh-Windows.exe",
    "ClipMesh-Android.apk",
    "SHA256SUMS.txt",
):
    assert f"releases/download/{CURRENT_TAG}/{asset_name}" in download_section
assert f"`{CURRENT_TAG}`" in download_section
assert "releases/tag/dev-latest" in download_section
assert f"## What's new in {CURRENT_TAG}" in readme

# v0.2.20 is a metadata-only version advance on top of the v0.2.17 product generation.
for value in (
    '0.2.17',
    '0.2.20',
    'versionCode = 27',
    'versionCode = 30',
):
    assert value in release_patch
for value in ('0.2.16', '0.2.17', 'versionCode = 26', 'versionCode = 27'):
    assert value in previous_release_patch

# macOS signing remains structured for Developer ID/notarization with ad-hoc fallback.
for name in (
    "CLIPMESH_MACOS_CERTIFICATE_P12_B64",
    "CLIPMESH_MACOS_CERTIFICATE_PASSWORD",
    "CLIPMESH_MACOS_SIGNING_IDENTITY",
    "CLIPMESH_MACOS_NOTARY_APPLE_ID",
    "CLIPMESH_MACOS_NOTARY_TEAM_ID",
    "CLIPMESH_MACOS_NOTARY_PASSWORD",
):
    assert name in workflow
    assert name in mac_script
assert "--options runtime" in mac_script
assert "notarytool submit" in mac_script
assert "Signature=adhoc" in mac_script
for nested_signing_guard in (
    'file -b "$daemon"',
    "clipmesh-bin",
    "-name '*.framework'",
    "-name '*.xpc'",
    "-name '*.appex'",
    "-name '*.app'",
    'done < "$macho_manifest"',
    'done < "$bundle_manifest"',
    'Authority=$CLIPMESH_MACOS_SIGNING_IDENTITY',
    "TeamIdentifier=",
    'verify_nested_code "$code_path"',
    'verify_nested_code "$bundle_path"',
):
    assert nested_signing_guard in mac_script

# Physical DEV signing must stay separate from official Android release signing.
assert 'STATE="${CLIPMESH_DEV_STATE:-$HOME/.clipmesh-dev}"' in dev_script
assert 'ANDROID_KEYSTORE="$STATE/android-dev.keystore"' in dev_script
assert "-alias clipmesh-dev" in dev_script
assert "CLIPMESH_ANDROID_KEYSTORE_B64" not in dev_script

# Permanent release-key provisioning must stay local, persistent and non-overwriting.
for setup_guard in (
    '${HOME}/.clipmesh-release-signing',
    "clipmesh-android-release.jks",
    'KEY_ALIAS="clipmesh-release"',
    "ClipMesh Android Release Keystore Password",
    "ClipMesh Android Release Key Password",
    "gh auth status",
    "-storetype JKS",
    "-keyalg RSA",
    "-keysize 4096",
    "-validity 10000",
    'ln "${temporary_keystore}" "${KEYSTORE_PATH}"',
    "Partial signing state detected",
    "CLIPMESH_ANDROID_KEYSTORE_B64",
    "CLIPMESH_ANDROID_SIGNING_CERT_SHA256",
    "BACKUP REQUIRED",
):
    assert setup_guard in setup_script
assert "clipmesh-dev" not in setup_script
for ignored_key_type in ("*.jks", "*.keystore", "*.p12", "*.pfx"):
    assert ignored_key_type in ignore_rules

# Reconstruction must retain every product repair through the optimized generation.
for patch in (
    "patch-v032-release.py",
    "patch-v033-ipv4-transfer.py",
    "patch-v034-shizuku-clipboard.py",
    "patch-v035-e2e-observability.py",
    "patch-v047-file-transfer-progress.py",
    "patch-v049-event-driven-performance.py",
    "patch-v050-ultra-idle.py",
):
    assert patch in reconstruct

assert "uninstall clipmesh once" in docs.lower()
assert "BACK UP" in docs
assert "CN=Android Debug" in docs

generated_gradle = root / "clipmesh/android/app/build.gradle.kts"
if system == "Linux" and generated_gradle.is_file():
    generated = generated_gradle.read_text(encoding="utf-8")
    assert "releaseTaskRequested" in generated

    # reconstruct.py intentionally stops at the base product generation. Release
    # patch layers then advance the same verified product metadata through 0.2.12,
    # 0.2.15, 0.2.16, 0.2.17, and finally 0.2.20. Accept exactly one coherent stage so
    # development and release workflows can reuse this policy test.
    base_generation = (
        f"versionCode = {BASE_CODE}" in generated
        and f'versionName = "{BASE_VERSION}"' in generated
    )
    verified_product_generation = (
        f"versionCode = {VERIFIED_PRODUCT_CODE}" in generated
        and f'versionName = "{VERIFIED_PRODUCT_VERSION}"' in generated
    )
    v015_generation = (
        "versionCode = 25" in generated
        and 'versionName = "0.2.15"' in generated
    )
    v016_generation = (
        "versionCode = 26" in generated
        and 'versionName = "0.2.16"' in generated
    )
    v017_generation = (
        "versionCode = 27" in generated
        and 'versionName = "0.2.17"' in generated
    )
    current_release_generation = (
        f"versionCode = {CURRENT_CODE}" in generated
        and f'versionName = "{CURRENT_VERSION}"' in generated
    )
    assert sum((base_generation, verified_product_generation, v015_generation, v016_generation, v017_generation, current_release_generation)) == 1

print(f"ClipMesh v{CURRENT_VERSION} release-signing policy self-test passed")
