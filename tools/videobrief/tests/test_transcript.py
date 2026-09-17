"""Тесты расшифровки: чистка повторов, блоки, чистый текст, тайм-коды.

Запуск: python tools/videobrief/tests/test_transcript.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from videobrief.transcript import (  # noqa: E402
    Segment, clean_text, dedupe_rolling, duration, format_tc, merge_blocks,
    parse_timed_text, timed_text,
)


def test_format_tc():
    assert format_tc(0) == "00:00"
    assert format_tc(7.4) == "00:07"
    assert format_tc(65) == "01:05"
    assert format_tc(3725) == "1:02:05"
    assert format_tc(-3) == "00:00"


def test_dedupe_rolling_strips_overlap():
    # Так выглядят авто-субтитры YouTube: каждая строка повторяет хвост прошлой.
    segments = [
        Segment(0.0, 2.0, "я расскажу вам"),
        Segment(2.0, 4.0, "я расскажу вам одну вещь"),
        Segment(4.0, 6.0, "одну вещь которая изменит всё"),
    ]
    out = dedupe_rolling(segments)
    assert [s.text for s in out] == ["я расскажу вам", "одну вещь", "которая изменит всё"]


def test_dedupe_rolling_keeps_unique():
    segments = [Segment(0.0, 1.0, "раз"), Segment(1.0, 2.0, "два")]
    assert [s.text for s in dedupe_rolling(segments)] == ["раз", "два"]


def test_dedupe_rolling_drops_full_duplicate():
    segments = [Segment(0.0, 1.0, "привет"), Segment(1.0, 2.0, "Привет")]
    assert [s.text for s in dedupe_rolling(segments)] == ["привет"]


def test_merge_blocks_joins_short_lines():
    segments = [Segment(i, i + 1.0, f"слово{i}") for i in range(10)]
    out = merge_blocks(segments, max_seconds=5.0, max_chars=500)
    assert len(out) == 2
    assert out[0].start == 0.0 and out[0].end == 5.0
    assert out[0].text == "слово0 слово1 слово2 слово3 слово4"


def test_merge_blocks_respects_chars():
    segments = [Segment(0.0, 1.0, "а" * 200), Segment(1.0, 2.0, "б" * 200)]
    out = merge_blocks(segments, max_seconds=60.0, max_chars=220)
    assert len(out) == 2


def test_clean_text_splits_paragraphs_on_pause():
    segments = [
        Segment(0.0, 2.0, "первая мысль"),
        Segment(2.5, 4.0, "её продолжение"),
        Segment(30.0, 32.0, "новая мысль"),
    ]
    assert clean_text(segments) == "первая мысль её продолжение\n\nновая мысль\n"


def test_timed_text_and_duration():
    segments = [Segment(0.0, 2.0, "хук"), Segment(65.0, 70.0, "вывод")]
    assert timed_text(segments) == "[00:00] хук\n[01:05] вывод\n"
    assert duration(segments) == 70.0
    assert duration([]) == 0.0


def test_parse_timed_text_roundtrip():
    segments = [Segment(0.0, 8.0, "хук"), Segment(8.0, 14.0, "вывод")]
    back = parse_timed_text(timed_text(segments))
    assert [s.text for s in back] == ["хук", "вывод"]
    assert [s.start for s in back] == [0.0, 8.0]
    assert back[0].end == 8.0
    assert back[1].end > back[1].start


def test_parse_timed_text_ignores_other_lines():
    assert parse_timed_text("просто текст\n\n# заголовок") == []
    assert parse_timed_text("[1:02:05] длинный ролик")[0].start == 3725.0


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok {name}")
    print("test_transcript: всё зелёное")


if __name__ == "__main__":
    run()
