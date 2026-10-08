# AI Editor

Describe a video edit once in Python, then export it to the editor you actually use: **Final Cut Pro, DaVinci Resolve, Premiere Pro, Kdenlive, Shotcut, Blender or CapCut**.

You build a `Timeline` (clips, trims, overlays, music, titles, zoom, speed, fades, crossfades, stills). One exporter per editor turns it into that editor's native project format. The timeline is also a plain JSON file, so scripts, other tools or an LLM can write edits and this project does the conversion.

```python
from editor import Timeline
from editor.export import export

tl = Timeline("demo")
tl.add_clip("interview.mp4", dur=8, src=12, fade_in=0.5)   # 8 s starting 12 s into the file
tl.add_clip("broll.mp4", dur=5, crossfade=1)               # dissolves in over the last second of the previous clip
tl.add_audio("music.mp3", volume=0.4, fade_out=2)
tl.add_title("Opening scene", start=1, dur=3, fade=0.5)
export(tl, "fcp", "out")                                    # -> out/demo.fcpxml, import it in Final Cut
```

## Contents

- [Requirements](#requirements) · [Install](#install) · [Try it in two minutes](#try-it-in-two-minutes)
- [How it works](#how-it-works) · [Timeline reference](#timeline-reference)
- [Exporting](#exporting) · [Opening the result in each editor](#opening-the-result-in-each-editor)
- [Voiceover and subtitles](#voiceover-and-subtitles) · [Click zoom](#click-zoom) · [Saved timelines (JSON)](#saved-timelines-json)
- [Feature support](#feature-support) · [How well it's tested](#how-well-its-tested) · [Limitations](#limitations)
- [Development](#development) · [License](#license)

## Requirements

- Python 3.10 or newer
- [ffmpeg](https://ffmpeg.org) (it provides `ffprobe`, used to read media durations and sizes): `brew install ffmpeg` on macOS, `apt install ffmpeg` on Debian/Ubuntu, `winget install Gyan.FFmpeg` on Windows
- The editor you want to export to. Only needed to open the result, not to generate it.

The core has no Python dependencies.

## Install

```bash
git clone https://github.com/zandy700/AI-Editor.git
cd AI-Editor
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .                     # core only
pip install -e '.[narrate,capcut]'   # optional: voiceover (edge-tts) and CapCut export (pyJianYingDraft)
```

## Try it in two minutes

Make two test clips with ffmpeg (skip this if you have your own footage):

```bash
mkdir -p demo && cd demo
ffmpeg -f lavfi -i testsrc=duration=10:size=1280x720:rate=30 -f lavfi -i sine=duration=10 -shortest -pix_fmt yuv420p a.mp4
ffmpeg -f lavfi -i smptebars=duration=10:size=1280x720:rate=30 -f lavfi -i sine=frequency=330:duration=10 -shortest -pix_fmt yuv420p b.mp4
```

Then run:

```python
from editor import Timeline
from editor.export import export

tl = Timeline("demo")
tl.add_clip("a.mp4", dur=4, src=2, fade_in=0.5)     # a.mp4 from 2 s to 6 s, placed at 0-4 s
tl.add_clip("b.mp4", dur=4, crossfade=1)            # starts at 3 s, dissolving over a.mp4's last second
tl.add_title("Hello", start=1, dur=2, fade=0.5)

for path in export(tl, "fcp", "out"):               # or "premiere", "resolve", "kdenlive", ...
    print(path)
```

This writes `out/demo.fcpxml`. To preview it without any editor, export to `kdenlive` and render with `melt` (see [below](#kdenlive-and-shotcut)).

## How it works

```
 your script / JSON / LLM
          │
          ▼
   Timeline (editor-neutral)        clips, titles, times in seconds
          │
          ├── fcp, resolve ──► FCPXML 1.9
          ├── premiere ──────► FCP7 XML (xmeml v4) + .srt
          ├── kdenlive, shotcut ► MLT XML
          ├── blender ───────► a Python script Blender runs
          └── capcut ────────► a CapCut draft folder
```

Editing is just placing segments on tracks. A **clip** says "play seconds `src`…`src+dur` of this file at timeline position `start`". Your media files are never modified or copied; the project files point at them by absolute path, so keep the originals where they are (or re-link in the editor if you move them).

## Timeline reference

### `Timeline(name="Edit", width=1920, height=1080, fps=30)`

`name` becomes the project and output file name. All times are in **seconds**.

| Method | What it does |
|---|---|
| `add_clip(path, dur=None, src=0, start=None, track=0, **options)` | Adds video (or a still image). Returns the `Clip` so you can adjust it. |
| `add_audio(path, dur=None, src=0, start=None, track=0, **options)` | Adds an audio file. Each `track` number is its own audio lane. |
| `add_title(text, start, dur, **options)` | Adds on-screen text. |
| `save(path)` / `Timeline.load(path)` | Write / read the timeline as JSON. |
| `srt()` | The titles as SRT subtitle text. |
| `duration` | Total length in seconds. |

Defaults that make scripts short:
- **`start` defaults to the end of the track**, so repeated `add_clip` calls chain one after another.
- **`dur` defaults to the rest of the file** (after `src`, divided by `speed`). **Stills must be given a `dur`.**
- **`track=0` is the main video track**; `track=1, 2, …` are overlays drawn on top.

### Clip options

| Option | Default | Meaning |
|---|---|---|
| `src` | `0` | In-point inside the source file, in seconds. This is the trim. |
| `track` | `0` | Video: 0 = main, 1+ = overlays. Audio: lane number. |
| `volume` | `1.0` | Sound level, `0.5` is half. |
| `speed` | `1.0` | `2.0` plays twice as fast. `dur` is still the length on the timeline, so a 2× clip with `dur=2` consumes 4 s of the source. |
| `opacity` | `1.0` | Picture transparency, `0.5` is half. |
| `fade_in`, `fade_out` | `0` | Seconds. Fades the picture from/to black (transparent on overlays) **and** the sound from/to silence. |
| `crossfade` | `0` | Seconds. The clip **overlaps** the previous clip on its track by this much and the two dissolve across the overlap. `start` is set for you (previous end − crossfade), so the timeline gets shorter by the overlap. Video clips on the main track only. |
| `zoom` | `[]` | Zoom keyframes as `[(seconds_into_clip, scale), …]`, `1.0` = no zoom. Usually set with [`apply_click_zoom`](#click-zoom). |

### Title options

| Option | Default | Meaning |
|---|---|---|
| `y` | `-0.8` | Vertical position, `-1` bottom … `1` top. The default is subtitle position. |
| `size` | `60` | Font size in pixels at 1080p. |
| `color` | `"#ffffff"` | Text colour as hex. |
| `fade` | `0` | Seconds of fade in and fade out. |

### Example with everything

```python
tl = Timeline("promo", width=1920, height=1080, fps=30)
main = tl.add_clip("a.mp4", dur=6, src=3, fade_in=0.5)
tl.add_clip("b.mp4", dur=5, crossfade=1)                      # dissolve from a to b
tl.add_clip("logo.png", dur=3)                                # still image
tl.add_clip("a.mp4", dur=2, speed=2)                          # 2x speed, consumes 4 s of source
tl.add_clip("watermark.png", dur=14, start=0, track=1, opacity=0.4)   # overlay for the whole edit
tl.add_audio("music.mp3", volume=0.5, fade_in=1, fade_out=2)
tl.add_title("Summer 2026", start=1, dur=3, y=0.6, size=96, color="#ffd400", fade=0.5)
```

## Exporting

From Python:

```python
from editor.export import export
paths = export(tl, "premiere", "out")      # returns the files it wrote
```

From the command line, on a [saved timeline](#saved-timelines-json):

```bash
python -m editor export timeline.json fcp resolve premiere -o out
python -m editor export timeline.json all -o out        # every target
```

| Target | Files written (in the output folder) |
|---|---|
| `fcp` | `Name.fcpxml` |
| `resolve` | `Name.fcpxml`, `Name.resolve.py` |
| `premiere` | `Name.premiere.xml`, `Name.srt` (when there are titles) |
| `kdenlive`, `shotcut` | `Name.mlt` (the same file for both) |
| `blender` | `Name.blender.py` |
| `capcut` | a draft folder `Name/` inside the output folder |

## Opening the result in each editor

### Final Cut Pro
**File → Import → XML…**, choose `Name.fcpxml`. The project appears in a new event named after the timeline.

### DaVinci Resolve
Either **File → Import → Timeline…** and pick `Name.fcpxml`, or let the generated script do it. With Resolve open:

```bash
python3 out/Name.resolve.py                    # import the timeline
python3 out/Name.resolve.py --render ~/Movies  # import, then queue and run a render
```

The script uses Resolve's scripting API, so Resolve must be running with external scripting allowed (**DaVinci Resolve → Preferences → System → General → External scripting using: Local**). On some Resolve versions external scripting is limited to the paid Studio edition; importing the `.fcpxml` by hand always works.

### Premiere Pro
**File → Import…**, choose `Name.premiere.xml`. If you have titles, also import `Name.srt` and drag it onto the timeline as captions (it carries the text and timing as a fallback in case Premiere drops the title generators in the XML).

### Kdenlive and Shotcut
**Shotcut:** **File → Open File…** and choose `Name.mlt`.
**Kdenlive:** try **File → Open**; if it doesn't accept the file, render it with `melt` instead or open it in Shotcut.
**No editor at all:** the MLT file can be rendered from the command line with [`melt`](https://www.mltframework.org) (`brew install mlt`):

```bash
melt out/Name.mlt -consumer avformat:video.mp4 vcodec=libx264 acodec=aac
```

### Blender
Builds the edit in Blender's Video Sequencer. Blender 5.x is what this has been run against.

```bash
blender -b --python out/Name.blender.py                              # build only (nothing saved)
blender -b --python out/Name.blender.py -- --render video.mp4        # build and render to MP4
```

On macOS the executable is `/Applications/Blender.app/Contents/MacOS/Blender`. To edit the result by hand, run `blender --python out/Name.blender.py` (without `-b`) and the edit is built in the Video Editing workspace's sequencer when Blender opens.

### CapCut
`export` writes a draft folder into whatever output folder you give it. To have CapCut see it, point the output at CapCut's drafts directory (use the full path) and restart CapCut:

```python
export(tl, "capcut", "/Users/you/Movies/CapCut/User Data/Projects/com.lveditor.draft")   # macOS
export(tl, "capcut", r"C:\Users\you\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft")   # Windows
```

Requires `pip install -e '.[capcut]'`. The folder location can differ between CapCut versions, and newer versions may encrypt drafts, in which case they won't open.

## Voiceover and subtitles

`narrate` turns a script into a spoken voiceover plus subtitles that appear exactly while each sentence is spoken.

```python
from editor.narrate import narrate

narrate(tl, "Welcome back. Today we are cutting a short film. Let's begin.")
narrate(tl, "这是一个中文句子。", start=12)        # Chinese sentences use the Chinese voice automatically
```

It splits the script into sentences, speaks each one, places the audio on the timeline and adds a title of equal length. Options: `voice="en-US-AriaNeural"`, `zh_voice="zh-CN-XiaoxiaoNeural"`, `start=` (default: after the existing audio), `gap=0.1` seconds between sentences, `out_dir=` for the generated mp3 files (default: a temp folder).

Requires `pip install -e '.[narrate]'` and an internet connection. It uses [`edge-tts`](https://github.com/rany2/edge-tts), which calls Microsoft Edge's read-aloud service. That service is unofficial and could change or stop working, so don't build anything critical on it. The generated mp3 files must stay where they are for the exported project to find them, so pass an `out_dir` you want to keep.

## Click zoom

Adds a smooth zoom in and out around moments you choose, typical for screen recordings:

```python
from editor.zoom import apply_click_zoom

rec = tl.add_clip("screen-recording.mp4")
apply_click_zoom(rec, [3.2, 7.8, 12.5])            # times in seconds from the start of the clip
apply_click_zoom(rec, "clicks.json", scale=2.0)    # or a JSON file containing a list of times
```

`scale` (default `1.5`) is the zoom factor, `ramp` (`0.25`) the seconds to zoom in or out, `hold` (`0.6`) how long to stay zoomed.

## Saved timelines (JSON)

`tl.save("timeline.json")` and `Timeline.load("timeline.json")` round-trip the whole edit. The format is plain JSON, so you can write it from any language or have an LLM produce it:

```json
{
  "name": "demo", "width": 1920, "height": 1080, "fps": 30,
  "clips": [
    {"path": "/abs/path/a.mp4", "start": 0, "dur": 4, "src": 2, "kind": "video", "track": 0,
     "volume": 1.0, "speed": 1.0, "opacity": 1.0, "fade_in": 0.5, "fade_out": 0.0,
     "crossfade": 0.0, "zoom": []},
    {"path": "/abs/path/music.mp3", "start": 0, "dur": 8, "src": 0, "kind": "audio", "track": 0,
     "volume": 0.5, "speed": 1.0, "opacity": 1.0, "fade_in": 1.0, "fade_out": 2.0,
     "crossfade": 0.0, "zoom": []}
  ],
  "titles": [
    {"text": "Hello", "start": 1, "dur": 2, "y": -0.8, "size": 60, "fade": 0.5, "color": "#ffffff"}
  ]
}
```

Use absolute paths in JSON. In JSON, `start` is required on every clip (the chaining default only exists in `add_clip`).

## Feature support

Every target supports every feature below, and a test fails if an exporter stops declaring one.

| Feature | Final Cut | Resolve | Premiere | Kdenlive / Shotcut | Blender | CapCut |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Trim and sequence clips | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Multiple video / audio tracks | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Volume | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Titles (position, size, colour, fade) | ✓ | ✓ | ✓ ¹ | ✓ | ✓ | ✓ |
| Zoom keyframes | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Speed change | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Opacity | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Fades (picture and sound) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Crossfade | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ ² |
| Still images | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

¹ Also written as an `.srt`, because Premiere may not keep text generators from XML.
² Pictures only. CapCut audio tracks can't overlap, so crossfade audio by putting the clips on separate audio tracks with `fade_in`/`fade_out`.

## How well it's tested

Each exporter is checked against one shared timeline that uses every feature, but how far the check goes depends on what could be run here:

| Target | Checked by | Not checked |
|---|---|---|
| Kdenlive / Shotcut | **Rendered with real `melt`**; colours, timing, titles and audio levels measured on the output | Not opened in the Kdenlive or Shotcut apps |
| Blender | **Rendered headless in Blender 5.2**; same measurements | Blender versions before 5.0 untested |
| Final Cut Pro | Well-formed XML, every reference resolves, times are frame-aligned, source-time math checked | **Not opened in Final Cut.** The Basic Title template ID, the title position parameter and `timeMap` details come from reference knowledge |
| Resolve | Same FCPXML, and the generated script parses | **Not opened in Resolve.** It may ignore some elements (speed changes, keyframed fades, title styling) |
| Premiere | Well-formed XML, unique IDs, frame math | **Not opened in Premiere.** Some effect IDs, the meaning of keyframe times and the text generator are unconfirmed |
| CapCut | The generated draft file is read back and its time ranges, speed, opacity, fades, transition and text colour checked | **Not opened in CapCut** |

If an export looks wrong in your editor, please [open an issue](https://github.com/zandy700/AI-Editor/issues) with the editor name and version, a screenshot, and the `.json` timeline that produced it. Those are the most useful reports.

## Limitations

- Titles are simple white/coloured text with a fade. Fonts, animations and styled templates are not covered, since each editor has its own.
- No effects, filters, colour grading or transitions other than the crossfade dissolve. They are different in every editor and can't be mapped to a common description.
- Crossfade works between video clips on the main track.
- Project files reference media by absolute path. Moving the media means re-linking in the editor.
- The exporters write new projects. They don't read existing editor projects.
- Voiceover needs internet and relies on an unofficial service (see above).

## Development

```bash
pip install -e '.[narrate,capcut]'
for t in tests/test_*.py; do python "$t"; done
```

Each test file is a plain script that prints `ok <name>` per check. They generate their own media with ffmpeg, and skip with a message when an optional tool is missing (`melt` for `test_mlt.py`, Blender for `test_blender.py`, internet for `test_narrate.py`).

```
editor/
  timeline.py        the Timeline, Clip, Title model and media probing
  narrate.py         voiceover + subtitles
  zoom.py            click zoom keyframes
  export/            one module per target: fcpxml, resolve, premiere, mlt, blender, capcut
tests/
  features.py        the shared timeline that uses every feature
  test_*.py          one test file per exporter, plus narration
```

To add an editor: write `editor/export/<name>.py` with `SUPPORTS = set(FEATURES)` and `export(timeline, out_dir) -> list[Path]`, register it in `editor/export/__init__.py`, and add a test against `tests/features.py::full_timeline`.

## License

[MIT](LICENSE)
