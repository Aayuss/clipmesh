# ClipMesh release signing

As audited on 2026-08-30, GitHub Actions had no release-signing secrets configured. The `Build ClipMesh` workflow therefore keeps pull-request and manual debug builds available, but a trusted push to `main` fails closed after tests instead of publishing a randomly debug-signed Android APK.

## Android: create the permanent release key once

Run this once on a trusted Mac. Choose strong, unique store and key passwords when `keytool` prompts:

```bash
keytool -genkeypair -v \
  -keystore clipmesh-android-release.jks \
  -alias clipmesh-release \
  -keyalg RSA -keysize 4096 -validity 10000 \
  -dname "CN=ClipMesh Android Release,O=ClipMesh,C=NP"
```

Copy the single-line base64 keystore value on macOS:

```bash
base64 < clipmesh-android-release.jks | tr -d '\n' | pbcopy
```

Calculate the expected certificate SHA-256 fingerprint. This value is public and safe to store as a GitHub Actions variable:

```bash
keytool -exportcert \
  -keystore clipmesh-android-release.jks \
  -alias clipmesh-release \
  | openssl dgst -sha256
```

In GitHub, open **Settings -> Secrets and variables -> Actions**. Create these repository secrets exactly:

- `CLIPMESH_ANDROID_KEYSTORE_B64`: the base64 value copied above.
- `CLIPMESH_ANDROID_KEYSTORE_PASSWORD`: the keystore password.
- `CLIPMESH_ANDROID_KEY_ALIAS`: `clipmesh-release` if the command above was used.
- `CLIPMESH_ANDROID_KEY_PASSWORD`: the private-key password.

Create this repository variable exactly:

- `CLIPMESH_ANDROID_SIGNING_CERT_SHA256`: the 64 hexadecimal characters from the `openssl` output. Colons and letter case are accepted.

Then rerun the failed `Build ClipMesh` workflow or push the next intended release commit. The workflow decodes the keystore only into the runner's temporary directory, builds `assembleRelease`, deletes the temporary keystore, and refuses publication unless all of these checks pass:

- `apksigner verify --verbose --print-certs` succeeds.
- The signer certificate matches `CLIPMESH_ANDROID_SIGNING_CERT_SHA256`.
- Package name is `dev.clipmesh`.
- `versionName` and `versionCode` match the release workflow.
- The publication job receives `ClipMesh-release.apk`; it has no debug-APK fallback.

> **BACK UP THE KEYSTORE AND BOTH PASSWORDS OFFLINE IN AT LEAST TWO SECURE LOCATIONS.** Losing this key prevents future APKs from updating installations signed by it. Do not commit the keystore, its base64 form, or either password.

### One-time migration from v0.2.9

The published `v0.2.9-alpha` APK was signed by a GitHub runner's ephemeral `CN=Android Debug` certificate with SHA-256 `b9f37a2f5b9d4cf523cd0d82baada9a38a924c92fabf01a7afede8d2c9e2eca6`. That private key was not retained and cannot be reproduced.

Android will reject an update from that APK to the first APK signed by the permanent release key. Users of the GitHub `v0.2.9-alpha` Android APK must uninstall ClipMesh once, install the first permanently signed APK, and pair their devices again. Every later APK signed with the backed-up permanent key will update normally.

The local `./dev-test.sh` identity is deliberately separate. It continues to use `~/.clipmesh-dev/android-dev.keystore` with alias `clipmesh-dev`; never upload that development key as the release key.

## macOS: current and future signing

The app identifier is `dev.clipmesh.private`. No Apple signing credentials are currently configured in GitHub, so the workflow verifies and labels the DMG's app as ad-hoc signed. It does not claim Developer ID signing or notarization.

When an Apple Developer ID Application certificate is available, export it with its private key as a password-protected `.p12`, then add all three repository secrets:

- `CLIPMESH_MACOS_CERTIFICATE_P12_B64`: `base64 < certificate.p12 | tr -d '\n'` on macOS.
- `CLIPMESH_MACOS_CERTIFICATE_PASSWORD`: the `.p12` export password.
- `CLIPMESH_MACOS_SIGNING_IDENTITY`: the full identity, such as `Developer ID Application: Name (TEAMID)`.

The workflow imports that certificate into a temporary keychain, signs the Finder Share extension and app inside-out with the hardened runtime and timestamp, recreates and signs the DMG, verifies the identity, and removes the temporary keychain.

Optional notarization requires all three additional repository secrets:

- `CLIPMESH_MACOS_NOTARY_APPLE_ID`
- `CLIPMESH_MACOS_NOTARY_TEAM_ID`
- `CLIPMESH_MACOS_NOTARY_PASSWORD` (an app-specific password)

Partial Apple signing or notarization configuration fails instead of silently downgrading. Without any Apple secrets, the documented ad-hoc path remains functional.
