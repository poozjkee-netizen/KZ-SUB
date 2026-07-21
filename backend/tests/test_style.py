"""Тесты оформления субтитров (чистая логика, без Whisper)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.srt import Segment  # noqa: E402
from app.style import apply_style  # noqa: E402


def test_noop_when_disabled():
    segs = [Segment(0, 1, "Сәлем, әлем.")]
    out = apply_style(segs, uppercase=False, strip_punctuation=False)
    assert out is segs  # без изменений — тот же объект


def test_uppercase():
    segs = [Segment(0, 1, "сәлем әлем")]
    out = apply_style(segs, uppercase=True, strip_punctuation=False)
    assert out[0].text == "СӘЛЕМ ӘЛЕМ"


def test_strip_punctuation():
    segs = [Segment(0, 1, "Сәлем, әлем!")]
    out = apply_style(segs, uppercase=False, strip_punctuation=True)
    assert out[0].text == "Сәлем әлем"


def test_strip_keeps_exclamation():
    segs = [Segment(0, 1, "Сәлем, әлем! Қалайсың?")]
    out = apply_style(segs, uppercase=False, strip_punctuation=True, punct_keep="!")
    assert out[0].text == "Сәлем әлем! Қалайсың"


def test_keeps_hyphen_and_apostrophe():
    segs = [Segment(0, 1, "тайм-код, o'zbek.")]
    out = apply_style(segs, uppercase=False, strip_punctuation=True)
    assert out[0].text == "тайм-код o'zbek"


def test_combined_uppercase_and_strip():
    segs = [Segment(0, 1, "Қалыңыз қалай?")]
    out = apply_style(segs, uppercase=True, strip_punctuation=True)
    assert out[0].text == "ҚАЛЫҢЫЗ ҚАЛАЙ"


def test_drops_empty_after_strip():
    segs = [Segment(0, 1, "—"), Segment(1, 2, "сөз")]
    out = apply_style(segs, uppercase=False, strip_punctuation=True)
    assert [s.text for s in out] == ["сөз"]


def test_preserves_newlines():
    segs = [Segment(0, 1, "бір, екі\nүш, төрт!")]
    out = apply_style(segs, uppercase=False, strip_punctuation=True)
    assert out[0].text == "бір екі\nүш төрт"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты оформления пройдены.")
