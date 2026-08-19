# ClipMesh

Private LAN-only encrypted clipboard sync for macOS, Windows, and Android.

This repository is used to build the private ClipMesh source package created for personal/family/friends use.

## Downloads

The easiest way to install ClipMesh is from **GitHub Releases**:

**[Download the latest ClipMesh release](https://github.com/Aayuss/clipmesh/releases/latest)**

Each tagged release publishes these files automatically after all three native builds pass:

- `ClipMesh-macOS.dmg`
- `ClipMesh-Windows.exe`
- `ClipMesh-Android.apk`
- `SHA256SUMS.txt`

For alpha/beta builds, open the repository's **Releases** page and select the newest pre-release if `/releases/latest` does not point to it.

> This repository is private. Only GitHub accounts that have access to the repository can open its Releases page. For friends/family who are not repository collaborators, send them the release files directly or add them as repository collaborators.

## CI builds

Every pull request and push to `main` builds and tests macOS, Windows, and Android. Successful workflow runs also expose temporary **Artifacts** under the Actions run for debugging/testing.

## Publishing a release

After the verified changes are merged to `main`, create and push a tag beginning with `v`, for example:

```bash
git tag v0.1.0-alpha
git push origin v0.1.0-alpha
```

GitHub Actions will build all three platforms and, only if every build succeeds, automatically create the GitHub Release and attach the `.dmg`, `.exe`, `.apk`, and combined SHA-256 checksum file.
