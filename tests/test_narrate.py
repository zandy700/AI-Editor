"""Narrate a short mixed English/Chinese script and check audio and titles line up.
Run: .venv/bin/python tests/test_narrate.py   (needs edge-tts and network; skips cleanly without them)"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from editor import Timeline
from editor.narrate import narrate, split_sentences

TEXT = "Hello there. This is a test, with a comma! 这是一个测试。"
GAP = 0.1


def test_split():
    parts = split_sentences(TEXT)
    assert parts == ["Hello there.", "This is a test,", "with a comma!", "这是一个测试。"], parts


def test_narrate():
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("  skipped (edge-tts not installed)")
        return
    tl = Timeline("n")
    voice = "en-US-AriaNeural"
    try:
        narrate(tl, "Hello there.", voice=voice, out_dir=tempfile.mkdtemp())   # network probe
    except Exception as e:
        print(f"  skipped (TTS unavailable: {e})")
        return
    tl = Timeline("n")
    end = narrate(tl, TEXT, voice=voice, gap=GAP, out_dir=tempfile.mkdtemp())
    n = len(split_sentences(TEXT))
    audio = sorted((c for c in tl.clips if c.kind == "audio"), key=lambda c: c.start)
    titles = sorted(tl.titles, key=lambda t: t.start)
    assert len(audio) == len(titles) == n, (len(audio), len(titles), n)
    for a, t in zip(audio, titles):
        assert t.start == a.start and t.dur == a.dur, (a, t)
    for a, b in zip(audio, audio[1:]):
        assert abs(b.start - (a.start + a.dur + GAP)) < 1e-9, (a, b)
    assert abs(end - (audio[-1].start + audio[-1].dur + GAP)) < 1e-9


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
