# ClipMesh v0.2.11 continuation

## Verified and included

- macOS direct file receiving now explicitly uses an IPv4 Network.framework listener on port `53421`. The installed test app was verified with `lsof` as `IPv4 *:53421 (LISTEN)`; Android reached it with `toybox nc`.
- The macOS bundle includes `NSLocalNetworkUsageDescription` for LAN discovery and transfers.
- Android and macOS build metadata, CI assertions, release workflow, README download links, and Android release-signing checks are updated for `0.2.11` / Android `versionCode 21`.
- `dev-test.sh` finds Java 17 and Cargo, uses one canonical ADB transport, disables ADB mDNS auto-connect, reconstructs only in isolated copies, and performs IPv4/network preflight checks.
- `scripts/setup-adb-single-device.sh` and its scoped LaunchAgent persist `ADB_MDNS_AUTO_CONNECT=0` without hard-coded device addresses.
- Real-device direct tests on the installed builds passed for Android-to-Mac and Mac-to-Android text clipboard transfer. The connected Android device reached the Mac on both ports.

## Remaining work

- The all-in-one `dev-test.sh` sequence still reports a false Mac-to-Android text timeout after a fresh rebuild, while the same installed binaries and equivalent direct two-way commands pass. This is a composite-harness ordering issue, not an IPv4 listener or network reachability failure.
- Do not publish the GitHub release until that composite-harness discrepancy is either fixed or replaced by a deterministic targeted test sequence that covers clipboard, image, and file transfers in both directions.
- No GitHub release artifact has been verified or published from this change yet.
