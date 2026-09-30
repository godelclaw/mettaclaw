"""Prepare isolated Iter state; no account settings or live channels are read."""
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent


def prepare(root, scenario):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "scenario.json").write_text(json.dumps(scenario))
    shutil.copy2(HERE / "upstream/prompt.txt", root)
    tools = root / "tools"
    tools.mkdir()
    shutil.copy2(HERE / "upstream/tools/nop.py", tools)
    (tools / "echo.py").write_text('DESCRIPTION = "Fixture echo"\ndef run(text): return text\n')
    (tools / "raise_error.py").write_text('DESCRIPTION = "Fixture failure"\ndef run(): raise ValueError("fixture tool failure")\n')
    (root / "memory").mkdir()
    (root / "transformations").mkdir()
    for name, text in scenario.get("files", {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if "experience" in scenario:
        (root / "experience.json").write_text(json.dumps(scenario["experience"]))
    entry = root / "run.metta"
    entry.write_text(f'!(import! &self "{HERE}/core.metta")\n!(iter:start)\n')
    return entry
