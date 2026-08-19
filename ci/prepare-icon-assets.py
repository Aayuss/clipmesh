from __future__ import annotations

import base64
import hashlib
from pathlib import Path

CI = Path(__file__).resolve().parent


def restore(pattern: str, expected_parts: int, output_name: str, expected_sha256: str) -> None:
    parts = sorted(CI.glob(pattern))
    if len(parts) != expected_parts:
        raise SystemExit(f"Expected {expected_parts} parts for {output_name}, found {len(parts)}")

    encoded = "".join(part.read_text(encoding="utf-8").strip() for part in parts)
    raw = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise SystemExit(
            f"{output_name} SHA-256 mismatch: expected {expected_sha256}, got {digest}"
        )

    (CI / output_name).write_text(encoded, encoding="utf-8")
    print(f"Restored {output_name}: {len(raw)} bytes, sha256={digest}")


restore(
    "clipmesh-icon-png.part*.b64",
    5,
    "clipmesh-icon.png.b64",
    "89f77dcf9b638abcc09baeb5680cb24b322577d55356cba4d8ad8f4b2452b597",
)
restore(
    "clipmesh-icon-ico.part*.b64",
    3,
    "clipmesh-icon.ico.b64",
    "da0ae4f36f3fcbd38b1ae4702e17b1e38911b0549bc97c4cc7be23137bd6654f",
)
