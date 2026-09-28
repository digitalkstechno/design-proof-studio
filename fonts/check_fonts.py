#!/usr/bin/env python3
from pathlib import Path

HERE = Path(__file__).resolve().parent
groups = {
    "regular": ["Proof-Regular.ttf"],
    "bold": ["Proof-Bold.ttf"],
    "italic": ["Proof-Italic.ttf"],
    "script": ["Proof-Script.ttf", "Proof-Script.otf", "Proof-Script.ttc"],
}

missing = []
print("Design Proof font folder:", HERE)
for kind, names in groups.items():
    found = next((HERE / name for name in names if (HERE / name).is_file()), None)
    if found:
        print(f"OK      {kind:7} -> {found.name}")
    else:
        print(f"MISSING {kind:7} -> expected one of: {', '.join(names)}")
        missing.append(kind)

if missing:
    print("\nAdd licensed font files before production if you need deterministic rendering.")
    raise SystemExit(1)

print("\nAll proof font slots are configured.")
