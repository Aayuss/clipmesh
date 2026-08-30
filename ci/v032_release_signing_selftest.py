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
assert "manifest application-id" in android_script
assert "manifest version-name" in android_script
assert "manifest version-code" in android_script
assert "ClipMesh-release.apk" in android_script
assert "trap cleanup EXIT INT TERM" in android_script

runtime_index = workflow.index("Runtime-test Android background send and receive on Android 15")
release_signing_index = workflow.index("Build and verify release-signed Android APK")
assert runtime_index < release_signing_index
assert "python ci/patch-v031-dev-test.py" in workflow
assert 'test ! -e "$J/CiBackgroundCaptureReceiver.kt"' in workflow
release_job = workflow[workflow.index("\n  release:\n") :]
assert "ClipMesh-release.apk" in release_job
assert "ClipMesh-debug.apk" not in release_job

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

# The physical dev harness must retain a separate permanent local identity.
assert 'STATE="${CLIPMESH_DEV_STATE:-$HOME/.clipmesh-dev}"' in dev_script
assert 'ANDROID_KEYSTORE="$STATE/android-dev.keystore"' in dev_script
assert "-alias clipmesh-dev" in dev_script
assert "CLIPMESH_ANDROID_KEYSTORE_B64" not in dev_script

assert "uninstall clipmesh once" in docs.lower()
assert "BACK UP" in docs
assert "CN=Android Debug" in docs

generated_gradle = root / "clipmesh/android/app/build.gradle.kts"
if system == "Linux" and generated_gradle.is_file():
    generated = generated_gradle.read_text(encoding="utf-8")
    assert "releaseTaskRequested" in generated
    assert "versionCode = 19" in generated
    assert 'versionName = "0.2.9"' in generated

print("ClipMesh release-signing policy self-test passed")
