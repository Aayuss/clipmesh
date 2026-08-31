#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source_path = ROOT / "ci/patch-acceptance-v4.py"
source = source_path.read_text(encoding="utf-8")

# v4 correctly builds the isolated passwordless acceptance environment, but its
# final incoming-prompt rewrite accidentally targets ClipMeshApp.swift. The real
# TransferDialogs implementation was created by acceptance-v2 in
# ClipMeshTransfer.swift. Redirect only that one replacement while preserving
# every other audited v4 transformation unchanged.
old = '''    replace_once(
        app,
        ''' + "'''" + '''            defaults.synchronize()
            let policy = defaults.string(forKey: \"ClipMesh.Acceptance.IncomingPolicy\") ?? \"\"
'''
new = '''    replace_once(
        ROOT / \"ci/ClipMeshTransfer.swift\",
        ''' + "'''" + '''            defaults.synchronize()
            let policy = defaults.string(forKey: \"ClipMesh.Acceptance.IncomingPolicy\") ?? \"\"
'''

count = source.count(old)
if count != 1:
    raise SystemExit(f"acceptance v5 prompt-target repair: expected one v4 anchor, found {count}")
source = source.replace(old, new, 1)

# v4's safety guard searched for the text `keyring::Entry` anywhere in the
# generated acceptance source. The acceptance-only source intentionally mentions
# the production backend in a comment, so that check rejected its own
# documentation. Reject executable Keychain API usage instead.
old_guard = '''    if "keyring::Entry" in final_secrets or "set_password" in final_secrets:
        raise SystemExit("macOS acceptance build still touches production Keychain")
'''
new_guard = '''    if "use keyring::Entry;" in final_secrets or "Entry::new(" in final_secrets or "set_password(" in final_secrets:
        raise SystemExit("macOS acceptance build still touches production Keychain")
'''
count = source.count(old_guard)
if count != 1:
    raise SystemExit(f"acceptance v5 Keychain-guard repair: expected one v4 anchor, found {count}")
source = source.replace(old_guard, new_guard, 1)

namespace = {
    "__name__": "__main__",
    "__file__": str(source_path),
}
exec(compile(source, str(source_path), "exec"), namespace, namespace)

system = os.environ.get("CLIPMESH_PLATFORM", "")
if system == "Darwin":
    transfer = (ROOT / "ci/ClipMeshTransfer.swift").read_text(encoding="utf-8")
    app = (ROOT / "ci/ClipMeshApp.swift").read_text(encoding="utf-8")
    secrets = (ROOT / "clipmesh/apps/desktop/src/secrets.rs").read_text(encoding="utf-8")
    for needle in (
        "acceptance-incoming-policy.txt",
        "ClipMesh.Acceptance.LastPromptDecision",
        "alert.buttons[index].performClick(nil)",
    ):
        if needle not in transfer:
            raise SystemExit(f"acceptance v5 transfer guard missing: {needle}")
    if "last_prompt_decision=" not in app:
        raise SystemExit("acceptance v5 app decision-state guard missing")
    for forbidden in ("use keyring::Entry;", "Entry::new(", "set_password("):
        if forbidden in secrets:
            raise SystemExit(f"acceptance v5 executable Keychain API remained: {forbidden}")

print(f"Applied ClipMesh physical acceptance v5 prompt/Keychain guard repairs on {system or 'unknown'}")
