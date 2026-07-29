"""Тесты передачи сырых сегментов воркер -> шлюз (dep-free).

Запуск: python tests/test_asr_types.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.asr_types import RawSegment, Word, raw_from_json, raw_to_json  # noqa: E402


def _seg():
    return RawSegment(1.0, 3.0, "сәлем әлем",
                      [Word(1.0, 1.8, "сәлем"), Word(1.9, 3.0, "әлем")])


def test_roundtrip_keeps_words_and_times():
    """Слова обязаны пережить дорогу: без них караоке-режим не собрать."""
    back = raw_from_json(raw_to_json([_seg()]))
    assert len(back) == 1
    assert back[0].text == "сәлем әлем"
    assert [w.text for w in back[0].words] == ["сәлем", "әлем"]
    assert (back[0].start, back[0].end) == (1.0, 3.0)
    assert (back[0].words[0].start, back[0].words[1].end) == (1.0, 3.0)


def test_offset_shifts_segment_and_every_word():
    """Длинный ролик режется на куски: без сдвига слов караоке разъедется.

    Сегмент сдвинуть мало — тайм-коды слов живут отдельно, и именно по ним
    строится пословный режим.
    """
    back = raw_from_json(raw_to_json([_seg()]), offset=180.0)
    assert (back[0].start, back[0].end) == (181.0, 183.0)
    assert [(w.start, w.end) for w in back[0].words] == [(181.0, 181.8), (181.9, 183.0)]


def test_missing_fields_do_not_crash():
    """Ответ воркера — внешние данные: половина полей может не приехать."""
    assert raw_from_json([]) == []
    assert raw_from_json(None) == []
    out = raw_from_json([{"start": 1.0}])
    assert (out[0].start, out[0].end, out[0].text, out[0].words) == (1.0, 0.0, "", [])


def test_segment_without_words_survives():
    """Whisper иногда отдаёт сегмент без пословных меток — это не повод падать."""
    back = raw_from_json(raw_to_json([RawSegment(0.0, 2.0, "текст", [])]))
    assert back[0].words == [] and back[0].text == "текст"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты передачи сегментов пройдены.")
