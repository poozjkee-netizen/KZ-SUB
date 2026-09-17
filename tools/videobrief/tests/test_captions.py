"""Тесты разбора готовых субтитров (.vtt/.srt).

Запуск: python tools/videobrief/tests/test_captions.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from videobrief.captions import clean_cue_text, parse  # noqa: E402

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.359 --> 00:00:02.720 align:start position:0%
i will tell you<00:00:01.359><c> one thing</c>

00:00:02.720 --> 00:00:05.000 align:start position:0%
that&#39;s it &amp; nothing more
"""

SRT = """1
00:00:01,000 --> 00:00:03,500
Бірінші сөйлем

2
00:01:05,250 --> 00:01:07,000
Екінші сөйлем
"""


def test_clean_cue_text():
    assert clean_cue_text("привет<00:00:01.359><c> мир</c>") == "привет мир"
    assert clean_cue_text("a&nbsp;b &amp; c") == "a b & c"
    assert clean_cue_text("   ") == ""


def test_parse_vtt():
    segments = parse(VTT)
    assert len(segments) == 2
    assert segments[0].text == "i will tell you one thing"
    assert abs(segments[0].start - 0.359) < 1e-6
    assert abs(segments[0].end - 2.72) < 1e-6
    assert segments[1].text == "that's it & nothing more"


def test_parse_srt():
    segments = parse(SRT)
    assert [s.text for s in segments] == ["Бірінші сөйлем", "Екінші сөйлем"]
    assert segments[1].start == 65.25


def test_parse_multiline_cue():
    content = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nпервая строка\nвторая строка\n"
    assert parse(content)[0].text == "первая строка вторая строка"


def test_parse_plain_text_gives_nothing():
    assert parse("просто текст без тайм-кодов") == []


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok {name}")
    print("test_captions: всё зелёное")


if __name__ == "__main__":
    run()
