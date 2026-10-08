"""DaVinci Resolve: write FCPXML plus a script that imports it through Resolve's Python API and can queue a render."""
from pathlib import Path

from . import fcpxml

# Resolve reads the same FCPXML, so it gets the same feature set. Unverified here: Resolve's own FCPXML importer
# may ignore some elements (timeMap retimes, keyframed opacity fades, audio fades, Basic Title styling).
SUPPORTS = set(fcpxml.SUPPORTS)

SCRIPT = r'''"""Run with Resolve open:  python3 {script} [--render OUT_DIR]
Needs Resolve's scripting API (external scripting is a Studio feature, or enable it under Preferences > General)."""
import os, sys, time

API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
LIB = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
os.environ.setdefault("RESOLVE_SCRIPT_API", API)
os.environ.setdefault("RESOLVE_SCRIPT_LIB", LIB)
sys.path.append(os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules"))
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp("Resolve")
if resolve is None:
    sys.exit("Resolve is not running (or external scripting is disabled).")
pm = resolve.GetProjectManager()
project = pm.CreateProject({name!r}) or pm.GetCurrentProject()
timeline = project.GetMediaPool().ImportTimelineFromFile({fcpxml!r}, {{"timelineName": {name!r}}})
if not timeline:
    sys.exit("Resolve rejected the FCPXML.")
project.SetCurrentTimeline(timeline)
print("Imported timeline:", timeline.GetName())

if "--render" in sys.argv:
    project.SetRenderSettings({{"TargetDir": sys.argv[sys.argv.index("--render") + 1], "CustomName": {name!r}}})
    project.AddRenderJob()
    project.StartRendering()
    while project.IsRenderingInProgress():
        time.sleep(1)
    print("Render finished.")
'''


def export(tl, out_dir):
    xml, = fcpxml.export(tl, out_dir)
    script = Path(out_dir) / f"{tl.name}.resolve.py"
    script.write_text(SCRIPT.format(script=script.name, name=tl.name, fcpxml=str(xml.resolve())))
    return [xml, script]
