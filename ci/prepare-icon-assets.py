from __future__ import annotations

import base64
import hashlib
from pathlib import Path

CI = Path(__file__).resolve().parent

PNG_PART_HASHES = [
    "5a5391118bce8ea9910b51180c12197fd1c3c50fbcdeb92c558c244f70834661",
    "64311802160b421e4af608bc80397c8a6ba7dcfb72ad7567a8654a1f9ed42021",
    "2142de6ea5af5fe832af637a68cc012b3219ae022d4b42671e39073af8868abf",
    "3c92b94b5efc76b451a63693ef336e63e465088aad2622a5e4a8a51081e871c9",
    "c1a583dc78fa0640f1847e4716c750439f730b9acfe38fc684180e1043f6b5d1",
]
ICO_PART_HASHES = [
    "b2643deacf1057d1add07223ea7a13a24cd3c4bddaf5fafabedf12e109c51575",
    "cb6b2e95c5ea03059fcc28cadbb7c21bcb2a61c6756774f1f2daa4f6bc8ebd81",
    "6676f62333eb869d783155a0e22868c4e8adef9d87e73d2620dd74801d0c0416",
    "180b6dcbde29c9a331a64a318b6a778fb9407fc772f42c46a7206b2ea1f87f4d",
    "64e4880359da2244be76c171f6c93168ad0bfc1725045639d2a342ed8cf58a92",
    "fc612c44c407262ad1dbed9e154cd54c3aa167ad5459349a4272be13535ec125",
]


def restore(
    parts: list[Path],
    expected_part_hashes: list[str],
    output_name: str,
    expected_sha256: str,
) -> None:
    if len(parts) != len(expected_part_hashes):
        raise SystemExit(
            f"Expected {len(expected_part_hashes)} parts for {output_name}, found {len(parts)}"
        )

    errors: list[str] = []
    texts: list[str] = []
    for part, expected_hash in zip(parts, expected_part_hashes, strict=True):
        text = part.read_text(encoding="utf-8").strip()
        texts.append(text)
        actual_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        print(f"{part.name}: chars={len(text)} sha256={actual_hash}")
        if actual_hash != expected_hash:
            errors.append(
                f"{part.name}: expected {expected_hash}, got {actual_hash}"
            )

    if errors:
        raise SystemExit("Icon chunk validation failed:\n" + "\n".join(errors))

    encoded = "".join(texts)
    raw = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise SystemExit(
            f"{output_name} SHA-256 mismatch: expected {expected_sha256}, got {digest}"
        )

    (CI / output_name).write_text(encoded, encoding="utf-8")
    print(f"Restored {output_name}: {len(raw)} bytes, sha256={digest}")


png_parts = sorted(CI.glob("clipmesh-icon-png.part*.b64"))
ico_parts = sorted(CI.glob("clipmesh-icon-ico-head.part*.b64")) + [
    CI / "clipmesh-icon-ico.part01.b64",
    CI / "clipmesh-icon-ico.part02.b64",
]

restore(
    png_parts,
    PNG_PART_HASHES,
    "clipmesh-icon.png.b64",
    "89f77dcf9b638abcc09baeb5680cb24b322577d55356cba4d8ad8f4b2452b597",
)
restore(
    ico_parts,
    ICO_PART_HASHES,
    "clipmesh-icon.ico.b64",
    "da0ae4f36f3fcbd38b1ae4702e17b1e38911b0549bc97c4cc7be23137bd6654f",
)
