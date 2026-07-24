"""Тесты нарезки длинного аудио на куски (stdlib wave/audioop, без сети/GPU).

Запуск: python tests/test_audio_chunk.py
"""
import io
import os
import struct
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.audio_chunk import split_wav_for_runpod  # noqa: E402

RATE = 16000
_tmpdir = tempfile.mkdtemp()


def _wav_bytes(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _tone(n_frames, amp=8000):
    # Простой «громкий» сигнал (постоянная амплитуда), чтобы RMS был высоким.
    return struct.pack("<h", amp) * n_frames


def _frames_in(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.getnframes()


def test_short_audio_single_chunk():
    wav = _wav_bytes(_tone(2 * RATE))            # 2 сек
    chunks = split_wav_for_runpod(wav, chunk_seconds=3)
    assert len(chunks) == 1
    assert chunks[0][1] == 0.0


def test_long_audio_splits_and_preserves_total():
    wav = _wav_bytes(_tone(10 * RATE))           # 10 сек
    chunks = split_wav_for_runpod(wav, chunk_seconds=3, search_seconds=0)
    assert len(chunks) >= 3
    # Смещения строго возрастают и начинаются с нуля.
    offsets = [off for _, off in chunks]
    assert offsets[0] == 0.0
    assert all(b > a for a, b in zip(offsets, offsets[1:]))
    # Ни один кадр не потерян и не задублирован.
    assert sum(_frames_in(b) for b, _ in chunks) == 10 * RATE


def test_each_chunk_under_runpod_limit():
    # 8 минут при 16 kHz mono; куски по 180 c должны влезать в 10 MiB base64.
    wav = _wav_bytes(_tone(8 * 60 * RATE))
    chunks = split_wav_for_runpod(wav, chunk_seconds=180)
    assert len(chunks) >= 2
    for b, _ in chunks:
        assert len(b) * 4 // 3 < 10 * 1024 * 1024


def test_cut_lands_in_silence():
    # Громко везде, кроме тихого окна вокруг границы 3 c → рез должен попасть в тишину.
    total = 6 * RATE
    pcm = bytearray(_tone(total))
    sil_start, sil_end = int(2.9 * RATE), int(3.1 * RATE)
    for i in range(sil_start, sil_end):
        struct.pack_into("<h", pcm, i * 2, 0)     # зануляем окно тишины
    chunks = split_wav_for_runpod(_wav_bytes(bytes(pcm)), chunk_seconds=3, search_seconds=1)
    first_len = _frames_in(chunks[0][0])
    # Точка реза (конец первого куска) — внутри тихого окна (с допуском на анализ-окно).
    assert sil_start - int(0.1 * RATE) <= first_len <= sil_end + int(0.1 * RATE)


def test_offsets_match_cut_points():
    wav = _wav_bytes(_tone(7 * RATE))
    chunks = split_wav_for_runpod(wav, chunk_seconds=3, search_seconds=0)
    # Смещение i-го куска = сумма длительностей предыдущих.
    acc = 0.0
    for b, off in chunks:
        assert abs(off - acc) < 1e-6
        acc += _frames_in(b) / RATE


def test_non_wav_returned_as_single():
    chunks = split_wav_for_runpod(b"garbage-not-wav", chunk_seconds=3)
    assert len(chunks) == 1 and chunks[0][1] == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты нарезки аудио пройдены.")
