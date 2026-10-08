# AI Editor

The [jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill) idea, made editor-neutral: script an edit in Python once as a `Timeline`, then export it to Final Cut Pro, DaVinci Resolve, Premiere Pro, Kdenlive, Shotcut, Blender or CapCut. One exporter per editor, no dependencies for the core.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[narrate,capcut]'     # extras: edge-tts (voiceover), pyJianYingDraft (CapCut). Needs ffmpeg/ffprobe on PATH.
```

## Use

```python
from editor import Timeline
from editor.export import export
from editor.narrate import narrate
from editor.zoom import apply_click_zoom

tl = Timeline("demo", width=1920, height=1080, fps=30)
a = tl.add_clip("a.mp4", dur=4, src=2)              # a.mp4 seconds 2-6, placed at 0-4
tl.add_clip("b.mp4", dur=3, src=5)                  # chains after the previous clip: 4-7
tl.add_clip("logo.mp4", dur=2, start=1, track=1)    # overlay on video track 1
tl.add_audio("music.mp3", dur=7, volume=0.5)
tl.add_title("Hello", start=1, dur=2)
apply_click_zoom(a, [1.0, 2.5])                     # zoom in/out around click times (s)
narrate(tl, "First sentence. Second sentence.")     # edge-tts voiceover + subtitles timed to the speech
tl.save("demo.json")
export(tl, "fcp", "out")                            # -> out/demo.fcpxml
```

## CLI

```bash
python -m editor export demo.json fcp resolve premiere -o out   # any of the targets, or `all`
```

A saved Timeline JSON is the "storyboard": have an LLM (or anything) write it, then export it.

## Targets

| Target | Output | Open / render |
|---|---|---|
| `fcp` | `Name.fcpxml` | Final Cut Pro: File > Import > XML |
| `resolve` | `Name.fcpxml`, `Name.resolve.py` | Resolve: File > Import > Timeline, or with Resolve open `python3 Name.resolve.py [--render DIR]` |
| `premiere` | `Name.premiere.xml`, `Name.srt` | Premiere: File > Import (XML); import the `.srt` as captions (titles are not in the XML) |
| `kdenlive` / `shotcut` | `Name.mlt` | Shotcut: File > Open. Kdenlive: open/import the MLT. Headless: `melt Name.mlt -consumer avformat:out.mp4` |
| `blender` | `Name.blender.py` | `blender -b --python Name.blender.py -- --render out.mp4` (omit `--render` to just build the edit) |
| `capcut` | a draft folder (`-o` = CapCut's drafts dir) | Restart CapCut, open the draft. Default dir is CapCut's own on macOS/Windows |

## Features

Every exporter declares `SUPPORTS` and a test fails if any of these is missing: trim, tracks (overlays), volume, titles (colour, fade), zoom keyframes, speed, opacity, fades (picture and sound), crossfade, still images. `tests/features.py::full_timeline` uses all of them. Crossfade means the clip overlaps the previous one on its track by that many seconds.

## Status

How far each target has been checked (run all: `for t in tests/test_*.py; do python $t; done`):

| Target | Checked by | Not checked |
|---|---|---|
| Kdenlive / Shotcut | **Rendered with real `melt`**: colours, timing, titles, audio levels measured on the output | Never opened in Kdenlive or Shotcut; Kdenlive may not open a plain `.mlt` |
| Blender | **Rendered headless on Blender 5.2.2**, same measurements | Blender 4.x code paths and other versions untested |
| Final Cut Pro | Well-formed XML (`xmllint`), refs resolve, frame-aligned times, source-time math | **Not opened in FCP.** Basic Title uid and Position key, and `timeMap` start semantics, are from memory |
| Resolve | Same FCPXML, plus the script parses | **Not opened in Resolve.** It may ignore retimes, keyframed fades or title styling. External scripting may need Studio |
| Premiere | Well-formed XML, unique ids, frame math | **Not opened in Premiere.** Effect ids, keyframe `<when>` meaning, Text generator and Time Remap on audio are guesses; the `.srt` is the fallback for titles |
| CapCut | The generated `draft_content.json` (timeranges, speed, alpha, fades, transition, text colour) | **Not opened in CapCut.** Newer versions may encrypt drafts. Audio can't crossfade (tracks can't overlap) |

## Not ported from the JianYing skill

Effect/filter/transition ID catalogs, ByteDance cloud music and TTS voices, Windows UI-automation auto-export, the web-to-video (Playwright) recorder and screen recorder, and LLM storyboard / B-roll matching. Voiceover uses free `edge-tts` instead.

## Notes

- Voiceover uses [`edge-tts`](https://github.com/rany2/edge-tts), which calls Microsoft Edge's read-aloud service. That service is unofficial, so don't rely on it for anything important.
- Inspired by [jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill) (MIT). No code was copied from it.
- MIT licensed, see [LICENSE](LICENSE).
