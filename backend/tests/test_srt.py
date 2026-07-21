"""Тесты форматирования SRT (чистая логика, без Whisper)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.srt import Segment, _format_timestamp, segments_to_srt  # noqa: E402


def test_format_timestamp_basic():
    assert _format_timestamp(0) == "00:00:00,000"
    assert _format_timestamp(1.5) == "00:00:01,500"
    assert _format_timestamp(61.25) == "00:01:01,250"
    assert _format_timestamp(3661.007) == "01:01:01,007"


def test_format_timestamp_negative_clamped():
    assert _format_timestamp(-5) == "00:00:00,000"


def test_segments_to_srt():
    segs = [
        Segment(0.0, 1.5, "Сәлеметсіз бе"),
        Segment(1.5, 3.0, "  Қалыңыз қалай  "),
    ]
    out = segments_to_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:01,500\nСәлеметсіз бе\n" in out
    assert "2\n00:00:01,500 --> 00:00:03,000\nҚалыңыз қалай\n" in out


def test_segments_skip_empty():
    segs = [Segment(0.0, 1.0, "   "), Segment(1.0, 2.0, "мәтін")]
    out = segments_to_srt(segs)
    # Пустой сегмент пропущен, нумерация начинается с непустого
    assert out.startswith("1\n00:00:01,000 --> 00:00:02,000\nмәтін\n")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты пройдены.")
