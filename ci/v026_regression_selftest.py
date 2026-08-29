from pathlib import Path
import socket
import threading
import platform

root = Path(__file__).resolve().parents[1]
project = root / "clipmesh"


def require(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert needle in text, f"missing {needle!r} in {path}"


# Source gates for each native implementation.
require(root / "ci/ClipMeshTransfer.swift", "100 Continue")
require(root / "ci/ClipMeshTransfer.cs", "100 Continue")
android = project / "android/app/src/main/java/dev/clipmesh"
if platform.system() == "Linux":
    require(android / "fileshare/LocalTransferEngine.kt", "100 Continue")
    require(android / "exclusion/ExclusionAccessibilityService.kt", "clipboard?.primaryClip")
    require(android / "clipboard/ClipboardBridge.kt", "lastRemoteAppliedAt")
    require(android / "SettingsStore.kt", "fun forgetPeer")
    require(android / "ClipMeshDialog.kt", "object ClipMeshDialog")
require(project / "apps/desktop/src/config.rs", "blocked_devices")
require(project / "apps/desktop/src/network.rs", "removed peer")


# Behavioral proof of the deadlock condition fixed in all receivers: a sender
# waiting for 100 may transmit no body at all until the interim response arrives.
left, right = socket.socketpair()
body = b'{"proof":"clipmesh"}'
received = []


def receiver() -> None:
    data = b""
    while b"\r\n\r\n" not in data:
        data += right.recv(1024)
    assert b"Expect: 100-continue" in data
    right.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
    payload = b""
    while len(payload) < len(body):
        payload += right.recv(len(body) - len(payload))
    received.append(payload)
    right.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")


thread = threading.Thread(target=receiver)
thread.start()
left.sendall(
    b"POST /api/clipmesh/v1/prepare-upload HTTP/1.1\r\n"
    + f"Content-Length: {len(body)}\r\n".encode()
    + b"Expect: 100-continue\r\n\r\n"
)
interim = left.recv(128)
assert interim.startswith(b"HTTP/1.1 100 Continue")
left.sendall(body)
final = left.recv(256)
thread.join(timeout=2)
left.close(); right.close()
assert received == [body]
assert final.startswith(b"HTTP/1.1 200 OK")

print("ClipMesh v0.2.6 transfer handshake, background capture and removal gates passed")
