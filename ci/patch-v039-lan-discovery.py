#!/usr/bin/env python3
"""Physical-LAN discovery hardening applied after the historical v0.2.11 stack."""

from pathlib import Path
import os
import platform

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "clipmesh"
SYSTEM = os.environ.get("CLIPMESH_PLATFORM", platform.system())


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if SYSTEM == "Darwin":
    transfer = ROOT / "ci/ClipMeshTransfer.swift"
    replace_once(
        transfer,
        '''    private func sendAnnouncement(announce: Bool) {
        guard isRunning && isServerReady else { return }
        let payload = info(announce: announce)
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        let fd = Darwin.socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard fd >= 0 else { return }
        defer { Darwin.close(fd) }
        var ttl: UInt8 = 1
        setsockopt(fd, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, socklen_t(MemoryLayout<UInt8>.size))
        var destination = sockaddr_in()
        destination.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        destination.sin_family = sa_family_t(AF_INET)
        destination.sin_port = in_port_t(Self.port.bigEndian)
        destination.sin_addr = in_addr(s_addr: inet_addr(Self.group))
        data.withUnsafeBytes { bytes in
            withUnsafePointer(to: &destination) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                    _ = sendto(fd, bytes.baseAddress, data.count, 0, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
                }
            }
        }
    }
''',
        '''    private func sendAnnouncement(announce: Bool) {
        guard isRunning && isServerReady else { return }
        let payload = info(announce: announce)
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        let fd = Darwin.socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard fd >= 0 else { return }
        defer { Darwin.close(fd) }
        var ttl: UInt8 = 1
        setsockopt(fd, IPPROTO_IP, IP_MULTICAST_TTL, &ttl, socklen_t(MemoryLayout<UInt8>.size))
        var broadcastEnabled: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &broadcastEnabled, socklen_t(MemoryLayout<Int32>.size))

        func sendPacket(_ address: in_addr_t) {
            var destination = sockaddr_in()
            destination.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            destination.sin_family = sa_family_t(AF_INET)
            destination.sin_port = in_port_t(Self.port.bigEndian)
            destination.sin_addr = in_addr(s_addr: address)
            data.withUnsafeBytes { bytes in
                withUnsafePointer(to: &destination) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                        _ = sendto(fd, bytes.baseAddress, data.count, 0, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
        }

        // Multicast remains the primary protocol. Limited IPv4 broadcast is a
        // fallback for real Wi-Fi stacks that pass TCP but suppress multicast.
        sendPacket(inet_addr(Self.group))
        sendPacket(inet_addr("255.255.255.255"))
    }
''',
        "macOS multicast plus broadcast discovery",
    )
    final = transfer.read_text(encoding="utf-8")
    for needle in ("SO_BROADCAST", 'inet_addr("255.255.255.255")', "sendPacket(inet_addr(Self.group))"):
        if needle not in final:
            raise SystemExit(f"macOS LAN discovery guard missing: {needle}")

elif SYSTEM == "Linux":
    transfer = PROJECT / "android/app/src/main/java/dev/clipmesh/fileshare/LocalTransferEngine.kt"
    replace_once(
        transfer,
        '''    private fun sendAnnouncement(announce: Boolean) {
        if (!serverReady.get()) return
        val context = requireContext()
        val bytes = myInfo(context, announce).toString().toByteArray(Charsets.UTF_8)
        val destination = InetAddress.getByName(MULTICAST_GROUP)
        val outbound = MulticastSocket().apply { timeToLive = 1 }
        outbound.use { it.send(java.net.DatagramPacket(bytes, bytes.size, destination, PORT)) }
    }
''',
        '''    private fun sendAnnouncement(announce: Boolean) {
        if (!serverReady.get()) return
        val context = requireContext()
        val bytes = myInfo(context, announce).toString().toByteArray(Charsets.UTF_8)

        runCatching {
            val destination = InetAddress.getByName(MULTICAST_GROUP)
            MulticastSocket().apply { timeToLive = 1 }.use { socket ->
                socket.send(java.net.DatagramPacket(bytes, bytes.size, destination, PORT))
            }
        }
        runCatching {
            val destination = InetAddress.getByName("255.255.255.255")
            java.net.DatagramSocket().use { socket ->
                socket.broadcast = true
                socket.send(java.net.DatagramPacket(bytes, bytes.size, destination, PORT))
            }
        }
    }
''',
        "Android multicast plus broadcast discovery",
    )
    final = transfer.read_text(encoding="utf-8")
    for needle in ('InetAddress.getByName("255.255.255.255")', "socket.broadcast = true", "MulticastSocket().apply { timeToLive = 1 }"):
        if needle not in final:
            raise SystemExit(f"Android LAN discovery guard missing: {needle}")

elif SYSTEM == "Windows":
    # Windows already uses its own discovery implementation. Keep the patch
    # pipeline cross-platform without altering a platform not implicated by the
    # Mac <-> Android physical failure.
    pass
else:
    raise SystemExit(f"unsupported platform: {SYSTEM}")

print(f"Applied resilient ClipMesh LAN discovery fallback on {SYSTEM}")
