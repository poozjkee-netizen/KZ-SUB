"""Тесты конвертации аудио в 16 kHz mono (stdlib wave/audioop, без сети/GPU).

Запуск: python tests/test_audio_convert.py
"""
import io
import os
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.audio_convert import to_16k_mono_wav_bytes  # noqa: E402

_tmpdir = tempfile.mkdtemp()


def _make_wav(seconds, rate, channels, width=2):
    path = os.path.join(_tmpdir, f"in_{seconds}_{rate}_{channels}_{width}.wav")
    n = int(seconds * rate)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(b"\x01\x00" * n * channels if width == 2 else b"\x80" * n * channels)
    return path


def _read_wav_params(data):
    with wave.open(io.BytesIO(data), "rb") as wf:
        return wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()


def test_48k_stereo_becomes_16k_mono():
    # Ровно случай панели: 48 kHz stereo → должно стать 16 kHz mono 16-bit.
    path = _make_wav(2.0, rate=48000, channels=2)
    out = to_16k_mono_wav_bytes(path)
    ch, width, rate, frames = _read_wav_params(out)
    assert (ch, width, rate) == (1, 2, 16000)
    assert abs(frames / 16000 - 2.0) < 0.05          # длительность сохранилась


def test_conversion_shrinks_payload_under_runpod_limit():
    # 2.5 мин 48k stereo ~ 29 МБ (как в проде) → после сжатия должно резко упасть.
    path = _make_wav(150.0, rate=48000, channels=2)
    original = os.path.getsize(path)
    out = to_16k_mono_wav_bytes(path)
    assert len(out) < original / 4                   # минимум в ~4-6 раз меньше
    # base64 такого куска влезает в лимит Runpod 10 MiB.
    assert len(out) * 4 // 3 < 10 * 1024 * 1024


def test_already_16k_mono_passthrough():
    path = _make_wav(1.0, rate=16000, channels=1)
    out = to_16k_mono_wav_bytes(path)
    ch, width, rate, _ = _read_wav_params(out)
    assert (ch, width, rate) == (1, 2, 16000)


def test_non_wav_returned_as_is():
    path = os.path.join(_tmpdir, "blob.bin")
    with open(path, "wb") as f:
        f.write(b"not a wav file at all")
    out = to_16k_mono_wav_bytes(path)
    assert out == b"not a wav file at all"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты конвертации аудио пройдены.")
