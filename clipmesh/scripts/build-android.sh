#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../android"
./gradlew :app:assembleRelease
mkdir -p ../dist/android
cp app/build/outputs/apk/release/app-release.apk ../dist/android/ClipMesh-unsigned.apk
echo "Built unsigned APK: dist/android/ClipMesh-unsigned.apk"
echo "Sign it with your own key before installing a release build, or use assembleDebug for a debug-signed APK."
