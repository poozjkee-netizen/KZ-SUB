"""Тесты нарезки субтитров (чистая логика, без Whisper)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.asr_types import RawSegment, Word  # noqa: E402
from app.segmentation import _wrap, resegment  # noqa: E402


def _words(pairs, step=0.4, start=0.0):
    """Список (текст) -> Word'ы с последовательными тайм-кодами без пауз."""
    out = []
    t = start
    for text in pairs:
        out.append(Word(t, t + step, text))
        t += step
    return out


def test_wrap_two_lines():
    # Текст в пределах ёмкости реплики (max_line_chars * max_lines).
    text = "бір екі үш төрт"
    wrapped = _wrap(text, max_line_chars=10, max_lines=2)
    lines = wrapped.split("\n")
    assert len(lines) == 2
    assert len(lines[0]) <= 10                       # первая строка в лимите
    assert " ".join(lines).split() == text.split()   # ни одно слово не потеряно


def test_wrap_single_long_word_kept():
    wrapped = _wrap("супердлинноеслово", max_line_chars=5, max_lines=2)
    assert wrapped == "супердлинноеслово"  # не режем внутри слова


def test_split_by_char_limit():
    # Много коротких слов подряд без пауз -> должно разбиться на несколько реплик.
    words = _words(["аа", "бб", "вв", "гг", "дд", "ее", "жж", "зз"])
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment(raw, max_line_chars=6, max_lines=1, max_cue_seconds=99, max_gap_seconds=99)
    assert len(cues) > 1
    for c in cues:
        assert len(c.text) <= 6


def test_split_by_gap():
    a = _words(["сәлем", "әлем"], start=0.0)          # 0.0..0.8
    b = _words(["қалай", "жағдай"], start=5.0)          # большой разрыв
    raw = [RawSegment(0.0, 8.0, "x", a + b)]
    cues = resegment(raw, max_line_chars=99, max_lines=2, max_cue_seconds=99, max_gap_seconds=0.8)
    assert len(cues) == 2
    assert cues[0].text == "сәлем әлем"
    assert cues[1].text == "қалай жағдай"


def test_split_by_duration():
    words = _words(["бір", "екі", "үш", "төрт"], step=3.0)  # каждая пара уже >5с
    raw = [RawSegment(words[0].start, words[-1].end, "x", words)]
    cues = resegment(raw, max_line_chars=99, max_lines=2, max_cue_seconds=5.0, max_gap_seconds=99)
    assert len(cues) > 1


def test_fallback_without_words():
    raw = [RawSegment(0.0, 2.0, "мәтін сөзсіз тайм-кодтар", words=[])]
    cues = resegment(raw, max_line_chars=99, max_lines=2, max_cue_seconds=99, max_gap_seconds=99)
    assert len(cues) == 1
    assert cues[0].start == 0.0 and cues[0].end == 2.0
    assert "мәтін" in cues[0].text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты нарезки пройдены.")
