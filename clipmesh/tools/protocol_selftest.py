#!/usr/bin/env python3
"""Independent protocol-v1 verifier used during development/review.
Requires Python cryptography (`pip install cryptography`). It never contacts a network.
"""
from pathlib import Path
import base64, json, struct, uuid
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROOT = Path(__file__).resolve().parents[1]
v = json.loads((ROOT / "test-vectors/protocol-v1.json").read_text())
master = bytes.fromhex(v["master_key_hex"])
space = uuid.UUID(v["space_id"])
sender = uuid.UUID(v["sender_id"])
message = uuid.UUID(v["message_id"])
ts = v["timestamp_ms"]
nonce = bytes.fromhex(v["nonce_hex"])
plain = v["plaintext_utf8"].encode()

def hkdf(info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=space.bytes, info=info).derive(master)

data_key = hkdf(b"clipmesh/aead/v1" + sender.bytes)
discovery_key = hkdf(b"clipmesh/discovery/v1")
assert data_key.hex() == v["data_key_hex"]
assert discovery_key.hex() == v["discovery_key_hex"]

header = (
    b"CM01" + bytes([1, 1]) + struct.pack(">H", 0) + sender.bytes + message.bytes
    + struct.pack(">q", ts) + nonce + struct.pack(">I", len(plain) + 16)
)
assert len(header) == 64 and header.hex() == v["header_hex"]
ciphertext = AESGCM(data_key).encrypt(nonce, plain, header)
assert ciphertext.hex() == v["ciphertext_hex"]
assert AESGCM(data_key).decrypt(nonce, ciphertext, header) == plain

name = v["discovery"]["name"]
port = v["discovery"]["port"]
canonical = "\0".join(["1", str(space), str(sender), name, str(port), str(ts)]).encode()
h = hmac.HMAC(discovery_key, hashes.SHA256()); h.update(canonical)
mac = base64.urlsafe_b64encode(h.finalize()).decode().rstrip("=")
assert mac == v["discovery"]["mac_b64url_no_pad"]

hello_nonce = bytes.fromhex(v["hello"]["nonce_hex"])
hello_body = b"CMH1" + space.bytes + sender.bytes + struct.pack(">q", ts) + hello_nonce
h = hmac.HMAC(discovery_key, hashes.SHA256()); h.update(hello_body)
assert h.finalize().hex() == v["hello"]["mac_hex"]
assert len(hello_body) + 32 == 92
print("ClipMesh protocol-v1 self-test: PASS")
