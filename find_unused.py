import os
import glob
import re

all_py_files = glob.glob("**/*.py", recursive=True)
basenames = {}

for f in all_py_files:
    if "venv" in f or ".venv" in f: continue
    name = os.path.basename(f)
    if name == "__init__.py": continue
    base = os.path.splitext(name)[0]
    basenames[base] = f

unused = []

for base, filepath in basenames.items():
    # If it's a test file, or main init, or a command, it's probably entry point or test
    if filepath.startswith("tests/"): continue
    if filepath == "InitGui.py": continue
    if base.startswith("command_"): continue
    if base == "conftest": continue
    
    # search for `base` in all other files
    found = False
    for other_f in all_py_files:
        if other_f == filepath: continue
        with open(other_f, 'r', encoding='utf-8', errors='ignore') as file:
            content = file.read()
            # check for exact word match
            if re.search(r'\b' + re.escape(base) + r'\b', content):
                found = True
                break
    if not found:
        unused.append(filepath)

print("Potentially unused files:")
for u in unused:
    print(u)
