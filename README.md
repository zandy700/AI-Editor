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

## Supported editors

Projects are generated on any OS. You only need the editor itself to open the result.

| Editor | Output | Status |
| --- | --- | --- |
| Final Cut Pro | `.fcpxml` | Supported, not opened in the app yet |
| DaVinci Resolve | `.fcpxml` plus an optional import/render script | Supported, not opened in the app yet |
| Premiere Pro | `.xml` plus `.srt` for titles | Supported, not opened in the app yet |
| Kdenlive / Shotcut | `.mlt` | Supported, **rendered and measured** with `melt` |
| Blender | `.py` script that builds the edit | Supported, **rendered and measured** in Blender 5.2 |
| CapCut | draft folder | Supported, not opened in the app yet |
| iMovie, Filmora | none | Not supported: they can't import an editable timeline |

## What it can't do

- **Not an editor.** It builds the timeline; previewing, polishing and the final render happen in your editor.
- **Doesn't watch your footage.** It never decides what to cut. You or your AI agent do.
- **No effects, filters or colour grading.** Each editor has its own, so only the crossfade is mapped across.
- **Writes new projects only.** It can't read or modify an existing editor project.
- **Absolute media paths.** If you move your footage, re-link it in the editor.

## Contents

- [What it can do](#what-it-can-do) · [How it works](#how-it-works) · [Using it with an AI agent](#using-it-with-an-ai-agent)
- [Requirements](#requirements) · [Install](#install) · [Try it in two minutes](#try-it-in-two-minutes) · [Timeline reference](#timeline-reference)
- [Exporting](#exporting) · [Opening the result in each editor](#opening-the-result-in-each-editor)
- [Voiceover and subtitles](#voiceover-and-subtitles) · [Click zoom](#click-zoom) · [Saved timelines (JSON)](#saved-timelines-json)
- [Feature support](#feature-support) · [How well it's tested](#how-well-its-tested) · [Limitations](#limitations)
- [Development](#development) · [License](#license)

## What it can do

**Editing**
- Cut and trim clips from any video file, and play them one after another
- Stack clips on extra video tracks as overlays (logos, picture-in-picture, watermarks)
- Add audio on as many lanes as you need (music, voiceover, sound effects)
- Use still images (png, jpg, bmp, tif, webp) as clips
- Change speed (slow motion or fast forward)
- Change a clip's opacity and volume
- Fade picture and sound in and out
- Dissolve (crossfade) from one clip into the next
- Add titles with position, size, colour and a fade
- Zoom in and out with keyframes, including automatic zooms around click times in screen recordings
- Set the project's resolution and frame rate

**Automation**
- Generate a spoken voiceover from a script, with subtitles timed exactly to the speech (English and Chinese)
- Export titles as an `.srt` subtitle file
- Save and load a whole edit as JSON, so a script, another program or an AI agent can write it
- Export from the command line or from Python

**Export targets**: Final Cut Pro, DaVinci Resolve, Premiere Pro, Kdenlive, Shotcut, Blender and CapCut. Every feature above is supported by every target (one caveat for CapCut audio, see [Feature support](#feature-support)).

**Rendering without an editor**: Kdenlive/Shotcut projects render with `melt`, Blender projects render headless, and Resolve can queue a render from the generated script.

## How it works

`AI Editor` is a library, not an app. You describe an edit as a `Timeline`, and an exporter writes a project file that your editor opens. Your footage is never changed. The project file only says which parts of which files to play, where, and with what effects.

```
 footage + a description of the edit
          │
          ▼
   script, JSON, or an AI agent writes the Timeline
          │
          ▼
   Timeline  ──►  exporter  ──►  project file  ──►  open it in your editor, finish and render
```

Nothing in it looks at your footage or decides what to cut. **You (or your AI agent) decide the edit; this project turns that decision into a real project file for the editor you use.**

## Using it with an AI agent

Out of the box this is **not** a chat app: there's no drag-and-drop window, and it doesn't analyse video on its own. But because the whole edit is a few lines of Python or a JSON file, any AI coding agent (Claude Code, Codex, Cursor and similar) can drive it. The workflow looks like this:

1. **Open your agent in this project's folder** (or any folder with your footage and this project installed) and tell it what you want, for example:
   > "Use AI Editor (read the README). Take the clips in `~/footage`, cut a 30-second highlight with a title at the start, background music from `song.mp3` at low volume, a dissolve between clips, and export it for Premiere."
2. **The agent looks at your footage with its own tools.** It can read file lengths with `ffprobe`, pull still frames with ffmpeg to see what's in them, or transcribe speech with a tool such as Whisper. This part comes from the agent, not from this project.
3. **The agent writes the edit**, either a short Python script using `Timeline` or a `timeline.json`.
4. **The agent runs the export** (`export(tl, "premiere", "out")` or `python -m editor export ...`).
5. **You open the file in your editor** and review, adjust and render as usual.

How good step 2 is depends on the agent and which tools it has. The agent can only cut on what it can see or hear, so for best results give it a transcript or a note of what's in each clip.

Not built yet, but it would make this smoother: a ready-made agent instruction file for Claude Code, and helpers that transcribe a video and detect scene changes so the agent doesn't need to assemble those itself.

### Things to try saying

> "Cut `~/footage/trip.mp4` down to a 30-second highlight with a title at the start, and export it for Premiere."

> "Put `song.mp3` under these clips at low volume, fade it out at the end, and dissolve between clips."

> "Write a short voiceover about autumn coffee, add subtitles, use these three clips as the pictures, and export for Final Cut."

> "I recorded my screen with clicks at these times. Zoom in on each click and export for DaVinci Resolve."

> "Make the same edit for Kdenlive and Blender so I can render it without opening anything."

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

## FAQ

1. **I can't see the new project in my editor.**
   Import the generated file (File > Import in Final Cut, Resolve and Premiere; open it in Kdenlive and Shotcut). For CapCut, restart the app after writing the draft folder.

2. **Footage shows as missing.**
   Project files use absolute paths. Re-link the media in the editor if you moved it.

3. **Something looks wrong after import.**
   [Open an issue](https://github.com/zandy700/AI-Editor/issues) with the editor and version, a screenshot and the timeline `.json`.

## License

[MIT](LICENSE)

---

## Inspiration and credits

This project was inspired by [**jianying-editor-skill**](https://github.com/luoluoluo22/jianying-editor-skill), an AI skill that builds video edits for JianYing from plain-language requests. Its idea of letting an AI agent write the timeline is what AI Editor carries over to other editors. No code was copied. Thank you to the people who built it:

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/luoluoluo22">
        <img src="https://github.com/luoluoluo22.png" width="80px;" alt="luoluoluo22"/><br />
        <sub><b>luoluoluo22</b></sub>
      </a><br />
      <sub>Project author / Maintainer</sub>
    </td>
    <td align="center">
      <a href="https://github.com/twodogegg">
        <img src="https://github.com/twodogegg.png" width="80px;" alt="twodogegg"/><br />
        <sub><b>twodogegg</b></sub>
      </a><br />
      <sub>macOS compatibility / ffprobe fallback / unit tests</sub>
    </td>
    <td align="center">
      <a href="https://github.com/shaozheliu">
        <img src="https://github.com/shaozheliu.png" width="80px;" alt="shaozheliu"/><br />
        <sub><b>shaozheliu</b></sub>
      </a><br />
      <sub>Missing-media fix / self-contained assets</sub>
    </td>
    <td align="center">
      <a href="https://github.com/Maxinsomnia">
        <img src="https://github.com/Maxinsomnia.png" width="80px;" alt="Maxinsomnia"/><br />
        <sub><b>Maxinsomnia</b></sub>
      </a><br />
      <sub>macOS 5.9+ execution support</sub>
    </td>
  </tr>
</table>

The optional CapCut export uses [**pyJianYingDraft**](https://github.com/GuanYixuan/pyJianYingDraft) by [GuanYixuan](https://github.com/GuanYixuan) (Apache-2.0), installed as a separate dependency.
