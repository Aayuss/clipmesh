#!/usr/bin/env python3
import re
import sys
import xml.etree.ElementTree as ET

raw = sys.stdin.read()
try:
    root = ET.fromstring(raw)
except Exception:
    raise SystemExit(0)

for node in root.iter("node"):
    text = (node.attrib.get("text", "") + " " + node.attrib.get("content-desc", "")).strip().lower()
    resource = node.attrib.get("resource-id", "").lower()
    if text in {"allow", "grant", "ok", "authorize"} or "button1" in resource:
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.attrib.get("bounds", ""))
        if match:
            x = (int(match.group(1)) + int(match.group(3))) // 2
            y = (int(match.group(2)) + int(match.group(4))) // 2
            print(x, y)
            break
