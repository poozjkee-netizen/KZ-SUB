"""Распознавание речи, когда готовых субтитров у ролика нет.

Отдельно от backend/app/transcribe.py намеренно: там язык жёстко зафиксирован
казахским (продукт про казахский), а сюда прилетает виральный контент на любом
языке — нужен авто-детект. Общего кода почти нет, а связывать два режима ради
экономии десяти строк значит рисковать продом ради утилиты.
"""
from __future__ import annotations

from .transcript import Segment

_model = None
_model_key: tuple[str, str, str] | None = None


def _get_model(name: str, device: str, compute_type: str):
    global _model, _model_key
    key = (name, device, compute_type)
    if _model is None or _model_key != key:
        # Импорт внутри функции: без faster-whisper инструмент обязан работать
        # на готовых субтитрах и на своём файле расшифровки.
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover — зависит от окружения
            raise RuntimeError(
                "Не установлен faster-whisper. Поставь его (pip install faster-whisper) "
                "или возьми ролик с готовыми субтитрами."
            ) from exc
        _model = WhisperModel(name, device=device, compute_type=compute_type)
        _model_key = key
    return _model


def transcribe(path: str, model_name: str, device: str, compute_type: str,
               language: str | None = None) -> tuple[list[Segment], str]:
    """Аудиофайл -> (сегменты, определённый язык).

    language=None — авто-детект: ролик может быть на любом языке, и угадывать
    за пользователя тут нельзя. VAD включён: он отсекает музыкальные проигрыши,
    на которых Whisper любит выдумывать реплики.
    """
    model = _get_model(model_name, device, compute_type)
    segments_iter, info = model.transcribe(
        path,
        language=language or None,
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    segments = [
        Segment(start=float(s.start), end=float(s.end), text=(s.text or "").strip())
        for s in segments_iter
        if (s.text or "").strip()
    ]
    return segments, (getattr(info, "language", "") or "")
