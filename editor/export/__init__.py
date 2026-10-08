"""One exporter per editor. Each `export(timeline, out_dir)` writes files and returns their paths."""
import importlib
from pathlib import Path

TARGETS = {          # target name -> module
    "fcp": "fcpxml",
    "resolve": "resolve",
    "premiere": "premiere",
    "kdenlive": "mlt",
    "shotcut": "mlt",
    "blender": "blender",
    "capcut": "capcut",
}


def export(tl, target, out_dir="."):
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}; choose from {', '.join(TARGETS)}")
    if target != "capcut":
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    return importlib.import_module(f".{TARGETS[target]}", __package__).export(tl, out_dir)
