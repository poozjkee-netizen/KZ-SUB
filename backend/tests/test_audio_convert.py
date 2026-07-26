"""Тесты конвертации аудио в 16 kHz mono (stdlib wave/audioop, без сети/GPU).

Запуск: python tests/test_audio_convert.py
"""
import io
import os
import struct
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


def _make_tone_wav(freq_hz, seconds, rate, channels=1):
    """WAV с синусоидой заданной частоты — для проверки антиалиасинга."""
    import math
    path = os.path.join(_tmpdir, f"tone_{freq_hz}_{rate}_{channels}.wav")
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        v = int(20000 * math.sin(2 * math.pi * freq_hz * i / rate))
        frames += struct.pack("<h", v) * channels
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))
    return path


def _rms(data):
    import audioop
    return audioop.rms(data, 2)


def test_highfreq_is_filtered_not_aliased():
    """Тон 18 кГц (выше Найквиста цели) должен подавляться, а не заворачиваться.

    Без антиалиасинг-фильтра ratecv отразил бы 18 кГц в ~2 кГц как шум —
    именно это поднимало шумовой пол и приводило к пропускам в субтитрах.
    """
    path = _make_tone_wav(18000, 0.5, 48000)
    out = to_16k_mono_wav_bytes(path)
    with wave.open(io.BytesIO(out), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    # Исходный тон громкий (RMS ~14000); после фильтра остаток должен быть мал.
    assert _rms(pcm) < 4000


def test_speech_band_tone_survives():
    """Тон 500 Гц (речевой диапазон) должен пройти почти без потерь."""
    path = _make_tone_wav(500, 0.5, 48000)
    out = to_16k_mono_wav_bytes(path)
    with wave.open(io.BytesIO(out), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    assert _rms(pcm) > 10000


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
