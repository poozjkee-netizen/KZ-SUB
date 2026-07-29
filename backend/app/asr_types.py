"""Общие типы данных ASR (чтобы избежать циклических импортов между модулями)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class RawSegment:
    """Сегмент, как его вернул Whisper (до пересборки в аккуратные субтитры)."""
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


# --- Передача сырых сегментов между воркером и шлюзом ------------------------
# Воркер только распознаёт, реплики собирает шлюз (там правки катятся деплоем).
# Формат общий, поэтому и упаковка, и разбор живут здесь: разъедутся — тайм-коды
# поедут молча, а это худший вид поломки.

def raw_to_json(segments: list[RawSegment]) -> list[dict]:
    """Сырые сегменты -> JSON-совместимый список (ответ воркера)."""
    return [
        {
            "start": s.start,
            "end": s.end,
            "text": s.text,
            "words": [{"start": w.start, "end": w.end, "text": w.text}
                      for w in (s.words or [])],
        }
        for s in segments
    ]


def raw_from_json(items: list[dict], offset: float = 0.0) -> list[RawSegment]:
    """JSON -> сырые сегменты со сдвигом на смещение куска в исходном аудио.

    Сдвиг применяется и к словам: без этого пословный режим разъехался бы на
    длинных роликах, которые шлюз режет на куски.
    """
    out: list[RawSegment] = []
    for s in items or []:
        out.append(RawSegment(
            start=float(s.get("start") or 0.0) + offset,
            end=float(s.get("end") or 0.0) + offset,
            text=str(s.get("text") or ""),
            words=[
                Word(float(w.get("start") or 0.0) + offset,
                     float(w.get("end") or 0.0) + offset,
                     str(w.get("text") or ""))
                for w in (s.get("words") or [])
            ],
        ))
    return out
