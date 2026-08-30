from pathlib import Path
import os
import platform
import re

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
release_patch = (root / "ci/patch-v032-release.py").read_text(encoding="utf-8")
reconstruct = (root / "ci/reconstruct.py").read_text(encoding="utf-8")

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
assert "apksigner" in android_script
assert "--print-certs" in android_script
assert "Signer #1 certificate SHA-256 digest" in android_script
assert "V2 Signer: certificate SHA-256 digest" in android_script
assert "reported_certificate_count" in android_script
assert "manifest application-id" in android_script
assert "manifest version-name" in android_script
assert "manifest version-code" in android_script
assert "ClipMesh-release.apk" in android_script
assert "trap cleanup EXIT INT TERM" in android_script
for forbidden_component in (
    "dev.clipmesh.CiBackgroundCaptureReceiver",
    "dev.clipmesh.DevTestReceiver",
    "dev.clipmesh.DevTestFileProvider",
    "dev.clipmesh.testdriver",
):
    assert forbidden_component in android_script

runtime_index = workflow.index("Runtime-test Android background send and receive on Android 15")
release_signing_index = workflow.index("Build and verify release-signed Android APK")
assert runtime_index < release_signing_index
assert "python ci/patch-v031-dev-test.py" in workflow
assert workflow.count("python ci/patch-v032-release.py") == 3
assert 'test ! -e "$J/CiBackgroundCaptureReceiver.kt"' in workflow
release_job = workflow[workflow.index("\n  release:\n") :]
assert "ClipMesh-release.apk" in release_job
assert "ClipMesh-debug.apk" not in release_job
workflow_tag_match = re.search(r'^\s*tag="(v\d+\.\d+\.\d+-alpha)"$', release_job, re.MULTILINE)
assert workflow_tag_match is not None
workflow_tag = workflow_tag_match.group(1)
assert workflow_tag == "v0.2.11-alpha"
current_version = workflow_tag.removeprefix("v").removesuffix("-alpha")

# README current-download metadata must stay in lockstep with the immutable
# release tag selected by the workflow. Historical migration references remain
# valid outside this section.
assert readme.startswith(f"# ClipMesh v{current_version}\n")
download_section = readme.split("## Download", 1)[1].split("\n## ", 1)[0]
expected_download_assets = (
    "ClipMesh-macOS.dmg",
    "ClipMesh-Windows.exe",
    "ClipMesh-Android.apk",
    "SHA256SUMS.txt",
)
for asset_name in expected_download_assets:
    assert f"releases/download/{workflow_tag}/{asset_name}" in download_section
readme_download_tags = set(re.findall(r"releases/download/([^/]+)/", download_section))
assert readme_download_tags == {workflow_tag}
assert "releases/download/v0.2.9-alpha/" not in download_section
assert f"publishes `{workflow_tag}`" in download_section
assert f"## What changed in v{current_version}" in readme

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
assert mac_script.index('done < "$macho_manifest"') < mac_script.index('done < "$bundle_manifest"')
outer_app_signing = '''codesign --force --options runtime --timestamp \\
    --sign "$CLIPMESH_MACOS_SIGNING_IDENTITY" \\
    --keychain "$CLIPMESH_MACOS_SIGNING_KEYCHAIN" "$APP"'''
assert mac_script.index('done < "$bundle_manifest"') < mac_script.index(outer_app_signing)
assert "partially configured" in mac_script

# The physical dev harness must retain a separate permanent local identity.
assert 'STATE="${CLIPMESH_DEV_STATE:-$HOME/.clipmesh-dev}"' in dev_script
assert 'ANDROID_KEYSTORE="$STATE/android-dev.keystore"' in dev_script
assert "-alias clipmesh-dev" in dev_script
assert "CLIPMESH_ANDROID_KEYSTORE_B64" not in dev_script

# Permanent release-key provisioning must be local, persistent, non-overwriting,
# Keychain-backed, idempotent, and distinct from the physical dev identity.
for setup_guard in (
    '${HOME}/.clipmesh-release-signing',
    "clipmesh-android-release.jks",
    'KEY_ALIAS="clipmesh-release"',
    "ClipMesh Android Release Keystore Password",
    "ClipMesh Android Release Key Password",
    "gh auth status",
    'gh repo view "${REPOSITORY}"',
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

assert 'patch-v032-release.py' in reconstruct
assert 'patch-v033-ipv4-transfer.py' in reconstruct
assert 'v0.2.10' in release_patch
assert 'versionCode = 20' in release_patch
assert 'version = "0.2.10"' in release_patch

assert "uninstall clipmesh once" in docs.lower()
assert "BACK UP" in docs
assert "CN=Android Debug" in docs

generated_gradle = root / "clipmesh/android/app/build.gradle.kts"
if system == "Linux" and generated_gradle.is_file():
    generated = generated_gradle.read_text(encoding="utf-8")
    assert "releaseTaskRequested" in generated
    assert "versionCode = 21" in generated
    assert 'versionName = "0.2.11"' in generated

print("ClipMesh release-signing policy self-test passed")
