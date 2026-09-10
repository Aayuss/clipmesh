#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../android"
./gradlew :app:assembleDebug
mkdir -p ../dist/android
cp app/build/outputs/apk/debug/app-debug.apk ../dist/android/ClipMesh-debug.apk
echo "Built installable debug APK: dist/android/ClipMesh-debug.apk"
