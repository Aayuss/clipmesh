from pathlib import Path
import platform
import runpy

root = Path(__file__).resolve().parents[1]
base = root / "ci" / "patch-v022-hotfix-base.py"
runpy.run_path(str(base), run_name="__main__")

if platform.system() == "Darwin":
    path = root / "ci" / "ClipMeshTransfer.swift"
    text = path.read_text(encoding="utf-8")
    old = '''        guard let action = button.action, let target = button.target else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button target/action was not retained"]) }
        guard NSApp.sendAction(action, to: target, from: button), fired else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button handler did not fire"]) }'''
    new = '''        guard let action = button.action,
              action == #selector(CMActionTarget.invoke(_:)),
              let target = button.target as? CMActionTarget else {
            throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button target/action was not retained"])
        }
        target.invoke(button)
        guard fired else { throw NSError(domain: "ClipMesh", code: 70, userInfo: [NSLocalizedDescriptionKey: "Transfer button handler did not fire"]) }'''
    if text.count(old) != 1:
        raise SystemExit("macOS headless action smoke-test anchor missing")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    for required in ('action == #selector(CMActionTarget.invoke(_:))', 'let target = button.target as? CMActionTarget', 'target.invoke(button)'):
        if required not in text:
            raise SystemExit(f"macOS headless action smoke-test guard missing: {required}")

print("Applied ClipMesh v0.2.2 headless action smoke-test fix")
