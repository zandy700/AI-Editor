"""python -m editor export timeline.json fcp resolve premiere kdenlive shotcut blender capcut [-o DIR]"""
import argparse

from .export import TARGETS, export
from .timeline import Timeline

p = argparse.ArgumentParser(prog="editor", description=__doc__)
sub = p.add_subparsers(dest="cmd", required=True)
e = sub.add_parser("export", help="export a saved timeline JSON to one or more editors")
e.add_argument("timeline")
e.add_argument("targets", nargs="+", choices=[*TARGETS, "all"])
e.add_argument("-o", "--out", default="out")
a = p.parse_args()

tl = Timeline.load(a.timeline)
for target in (TARGETS if "all" in a.targets else a.targets):
    for path in export(tl, target, a.out):
        print(f"{target:9} {path}")
