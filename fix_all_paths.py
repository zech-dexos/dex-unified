"""
fix_all_paths.py — one-time patch.

Replaces every "<NAME>_PATH = Path.home() / "dexos-core" / "<file>"" with
a path resolved relative to the script's own file location, across every
.py file in the current directory.
"""

import re
from pathlib import Path

PATTERN = re.compile(
    r'(\w+_PATH)(\s*)=\s*Path\.home\(\)\s*/\s*"dexos-core"\s*/\s*("[^"]+")'
)
REPLACEMENT = r'\1\2= Path(__file__).resolve().parent / \3'

changed = []

for path in sorted(Path(".").glob("*.py")):
    text = path.read_text()
    new_text, n = PATTERN.subn(REPLACEMENT, text)
    if n == 0:
        continue
    path.write_text(new_text)
    changed.append((path.name, n))

print("Changed files (name, count):", changed)

for fname, _ in changed:
    text = Path(fname).read_text()
    assert 'Path.home() / "dexos-core"' not in text, f"{fname}: old pattern still present"

print("fix_all_paths.py: all patched files verified")
