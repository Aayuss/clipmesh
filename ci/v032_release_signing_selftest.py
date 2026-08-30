from pathlib import Path
import os
import platform

root = Path(__file__).resolve().parents[1]
system = os.environ.get("CLIPMESH_PLATFORM", platform.system())
workflow = (root / ".github/workflows/build.yml").read_text(encoding="utf-8")
fixed_gradle = (root / "ci/android-app-build.gradle.kts.fixed").read_text(encoding="utf-8")
android_script = (root / "ci/build-android-release.sh").read_text(encoding="utf-8")
mac_script = (root / "ci/macos-release-signing.sh").read_text(encoding="utf-8")
dev_script = (root / "dev-test.sh").read_text(encoding="utf-8")
docs = (root / "RELEASE_SIGNING.md").read_text(encoding="utf-8")
readme = (root / "README.md").read_text(encoding="utf-8")
setup_script = (root / "scripts/setup-android-release-signing.sh").read_text(encoding="utf-8")
ignore_rules = (root / ".gitignore").read_text(encoding="utf-8")
reconstruct = (root / "ci/reconstruct.py").read_text(encoding="utf-8")
release_patch = (root / "ci/patch-v036-release.py").read_text(encoding="utf-8")

CURRENT_VERSION = "0.2.12"
CURRENT_CODE = "22"
CURRENT_TAG = "v0.2.12-alpha"
VERIFIED_DEV_VERSION = "0.2.11"
VERIFIED_DEV_CODE = "21"

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
assert f"CLIPMESH_ANDROID_EXPECTED_VERSION_NAME: {CURRENT_VERSION}" in workflow
assert f"CLIPMESH_ANDROID_EXPECTED_VERSION_CODE: '{CURRENT_CODE}'" in workflow
assert f"versionCode = {CURRENT_CODE}" in workflow
assert f'versionName = "{CURRENT_VERSION}"' in workflow
assert f'^version = "{CURRENT_VERSION}"$' in workflow

# README download metadata must describe the immutable current release.
assert readme.startswith(f"# ClipMesh v{CURRENT_VERSION}\n")
download_section = readme.split("## Download", 1)[1].split("\n## ", 1)[0]
for asset_name in (
    "ClipMesh-macOS.dmg",
    "ClipMesh-Windows.exe",
    "ClipMesh-Android.apk",
    "SHA256SUMS.txt",
):
    assert f"releases/download/{CURRENT_TAG}/{asset_name}" in download_section
assert f"publishes `{CURRENT_TAG}`" in download_section
assert f"## What changed in v{CURRENT_VERSION}" in readme

# Current release bump must be metadata-only on top of the physically verified v0.2.11 product code.
for value in (
    '0.2.11',
    '0.2.12',
    'versionCode = 21',
    'versionCode = 22',
):
    assert value in release_patch

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

# Reconstruction must retain every product repair through the physical-test generation.
for patch in (
    "patch-v032-release.py",
    "patch-v033-ipv4-transfer.py",
    "patch-v034-shizuku-clipboard.py",
    "patch-v035-e2e-observability.py",
):
    assert patch in reconstruct

assert "uninstall clipmesh once" in docs.lower()
assert "BACK UP" in docs
assert "CN=Android Debug" in docs

generated_gradle = root / "clipmesh/android/app/build.gradle.kts"
if system == "Linux" and generated_gradle.is_file():
    generated = generated_gradle.read_text(encoding="utf-8")
    assert "releaseTaskRequested" in generated

    # reconstruct.py intentionally stops at the physically verified v0.2.11
    # product generation. Canonical/release CI then applies patch-v036, which is
    # metadata-only, to produce v0.2.12. Accept exactly either coherent state so
    # the dev harness can validate the verified product boundary while release CI
    # still validates the public version/code pair.
    verified_dev_generation = (
        f"versionCode = {VERIFIED_DEV_CODE}" in generated
        and f'versionName = "{VERIFIED_DEV_VERSION}"' in generated
    )
    current_release_generation = (
        f"versionCode = {CURRENT_CODE}" in generated
        and f'versionName = "{CURRENT_VERSION}"' in generated
    )
    assert verified_dev_generation ^ current_release_generation

print(f"ClipMesh v{CURRENT_VERSION} release-signing policy self-test passed")
