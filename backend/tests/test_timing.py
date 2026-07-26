"""Тесты привязки начала субтитров к началу речи (stdlib wave/audioop).

Запуск: python tests/test_timing.py
"""
import io
import math
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.srt import Segment  # noqa: E402
from app.timing import snap_starts_to_speech  # noqa: E402

RATE = 16000


def _wav(spans, total_seconds):
    """WAV 16 kHz mono: тон в интервалах spans=[(нач, кон)], иначе тишина."""
    n = int(total_seconds * RATE)
    frames = bytearray(n * 2)
    for start, end in spans:
        for i in range(int(start * RATE), min(int(end * RATE), n)):
            v = int(12000 * math.sin(2 * math.pi * 220 * i / RATE))
            struct.pack_into("<h", frames, i * 2, v)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def test_cue_starting_in_silence_is_pulled_to_speech():
    # Речь с 3.0 c, а реплика начинается в 2.0 c — ровно случай «текст раньше речи».
    wav = _wav([(3.0, 4.0)], 5.0)
    out = snap_starts_to_speech([Segment(2.0, 2.9, "ДӘЛ")], wav, window_seconds=1.5)
    assert abs(out[0].start - 3.0) < 0.05


def test_short_cue_is_shifted_whole_preserving_duration():
    # Караоке-реплика короткая: сдвиг «съел» бы её целиком, поэтому двигаем всю.
    wav = _wav([(3.0, 4.0)], 5.0)
    seg = Segment(2.0, 2.4, "СӨЗ")
    out = snap_starts_to_speech([seg], wav, window_seconds=1.5)
    assert abs(out[0].start - 3.0) < 0.05
    assert abs((out[0].end - out[0].start) - (seg.end - seg.start)) < 0.05


def test_cue_already_on_speech_untouched():
    # Реплика началась на речи — двигать нельзя, иначе отрежем начало слова.
    wav = _wav([(1.0, 4.0)], 5.0)
    seg = Segment(2.0, 2.5, "СӨЗ")
    out = snap_starts_to_speech([seg], wav, window_seconds=1.5)
    assert out[0].start == seg.start and out[0].end == seg.end


def test_never_moves_earlier():
    # Речь позади реплики — назад не двигаем ни при каких условиях.
    wav = _wav([(0.5, 1.0)], 5.0)
    seg = Segment(3.0, 3.5, "СӨЗ")
    out = snap_starts_to_speech([seg], wav, window_seconds=1.5)
    assert out[0].start >= seg.start


def test_no_speech_within_window_keeps_cue():
    wav = _wav([(4.5, 5.0)], 6.0)
    seg = Segment(1.0, 1.5, "СӨЗ")
    out = snap_starts_to_speech([seg], wav, window_seconds=0.5)
    assert out[0].start == seg.start


def test_order_and_no_overlap_preserved():
    wav = _wav([(2.0, 2.3), (2.5, 2.8), (3.0, 3.3)], 5.0)
    segs = [Segment(1.0, 1.4, "А"), Segment(1.5, 1.9, "Б"), Segment(2.0, 2.4, "В")]
    out = snap_starts_to_speech(segs, wav, window_seconds=1.5)
    starts = [s.start for s in out]
    assert starts == sorted(starts)                       # порядок сохранён
    for prev, nxt in zip(out, out[1:]):
        assert nxt.start >= prev.end - 1e-6               # без наложений
    assert [s.text for s in out] == ["А", "Б", "В"]       # текст не перепутан


def test_disabled_by_zero_window():
    wav = _wav([(3.0, 4.0)], 5.0)
    seg = Segment(2.0, 2.5, "СӨЗ")
    out = snap_starts_to_speech([seg], wav, window_seconds=0)
    assert out[0].start == seg.start


def test_broken_audio_returns_segments_unchanged():
    segs = [Segment(1.0, 2.0, "СӨЗ")]
    assert snap_starts_to_speech(segs, b"not-a-wav", 1.0) == segs
    assert snap_starts_to_speech(segs, b"", 1.0) == segs


def test_click_is_not_mistaken_for_speech():
    """Одиночный щелчок (20 мс) короче MIN_RUN_FRAMES — не считается речью."""
    wav = _wav([(2.4, 2.42), (3.0, 4.0)], 5.0)
    out = snap_starts_to_speech([Segment(2.0, 2.9, "СӨЗ")], wav, window_seconds=1.5)
    assert abs(out[0].start - 3.0) < 0.08     # подтянулись к речи, а не к щелчку


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты таймингов пройдены.")
