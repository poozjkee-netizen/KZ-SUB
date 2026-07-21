"""Обёртка над faster-whisper для распознавания казахской речи.

Модель загружается лениво (при первом запросе) и кэшируется в процессе.
На проде процесс должен жить на GPU-инстансе, иначе транскрибация медленная.
"""
from __future__ import annotations

import logging

from .config import settings
from .srt import Segment

logger = logging.getLogger("kzsub.transcribe")

_model = None  # кэш загруженной модели на процесс


def _get_model():
    global _model
    if _model is None:
        # Импорт внутри функции — чтобы приложение поднималось даже без
        # установленной тяжёлой зависимости (например, в тестах SRT-логики).
        from faster_whisper import WhisperModel

        logger.info(
            "Загрузка Whisper: model=%s device=%s compute=%s",
            settings.whisper_model, settings.device, settings.compute_type,
        )
        _model = WhisperModel(
            settings.whisper_model,
            device=settings.device,
            compute_type=settings.compute_type,
        )
    return _model


def transcribe_file(path: str) -> tuple[list[Segment], float]:
    """Транскрибирует аудиофайл на казахском.

    Возвращает (список сегментов, длительность аудио в секундах).
    Язык жёстко зафиксирован (settings.language = 'kk'): продукт про казахский,
    авто-детект языка тут только вредит (Whisper часто путает kk с ru/tt/ky).
    """
    model = _get_model()

    segments_iter, info = model.transcribe(
        path,
        language=settings.language,
        task="transcribe",
        vad_filter=True,              # отсекаем тишину -> точнее тайм-коды
        vad_parameters={"min_silence_duration_ms": 400},
        beam_size=5,
        condition_on_previous_text=True,
    )

    segments = [
        Segment(start=s.start, end=s.end, text=s.text)
        for s in segments_iter
    ]
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    logger.info("Готово: %d сегментов, %.1f сек аудио", len(segments), duration)
    return segments, duration
