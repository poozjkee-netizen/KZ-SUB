"""Сбор датасета казахской речи для будущего дообучения модели.

Зачем: открытые дообученные модели мы уже проверили — они наш `large-v3` не
бьют (docs/ASR_PROVIDERS.md §5). Значит, отрыв по качеству даст только своя
модель, а для неё нужны часы казахской речи именно того типа, что монтируют
наши пользователи. Датасет — единственная часть продукта, которую конкурент не
скопирует за неделю, и копить его надо с первого дня: время идёт в нашу пользу
только если запись началась.

Что храним: аудио 16 kHz mono (то самое, что уходило в распознавание) и
распознанный текст с тайм-кодами. Текст — это «черновая» разметка: перед
дообучением её правит человек, но она экономит основную часть работы.

Приватность и осознанность:
- **Выключено по умолчанию** (`KZSUB_COLLECT_DATASET`).
- Собираем только с явно перечисленных ключей (`KZSUB_COLLECT_KEYS`) —
  начинать имеет смысл со своих же роликов, где вопрос согласия не стоит.
  Для чужих записей нужно согласие пользователя, а не молчаливый сбор.
- В манифест пишем хеш ключа, не сам ключ.
- Том на Fly маленький (1 ГБ), поэтому есть жёсткий потолок по объёму и
  вытеснение самых старых записей: датасет не должен положить прод.

Только stdlib — модуль обязан оставаться dep-free-тестируемым.

CLI:
    python -m app.dataset stats
    python -m app.dataset prune
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from .config import settings
from .events import anon

MANIFEST = "manifest.jsonl"


def root_dir() -> str:
    """Куда складываем: том состояния, иначе временная директория."""
    base = settings.state_dir or settings.tmp_dir
    return os.path.join(base, "dataset")


def should_collect(api_key: str) -> bool:
    """Собирать ли этот прогон.

    Пустой список ключей означает «ни с кого»: включённый сбор без явного
    указания, чью речь собираем, — это ровно тот молчаливый сбор, которого мы
    не хотим.
    """
    if not settings.collect_dataset or not api_key:
        return False
    allowed = {k.strip() for k in settings.collect_keys.split(",") if k.strip()}
    return api_key in allowed


def store(api_key: str, wav_bytes: bytes, segments: list, duration: float) -> str:
    """Сохранить один прогон. Возвращает путь к аудио или "" при отказе.

    Никогда не бросает исключений: сбор датасета не имеет права сорвать выдачу
    субтитров пользователю.
    """
    if not wav_bytes:
        return ""
    try:
        day = time.strftime("%Y-%m-%d")
        folder = os.path.join(root_dir(), day)
        os.makedirs(folder, exist_ok=True)

        name = f"{int(time.time() * 1000)}"
        wav_path = os.path.join(folder, f"{name}.wav")
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)

        # Черновая разметка рядом: с ней запись пригодна для дообучения после
        # вычитки, без неё — просто аудиофайл, который надо расшифровывать с нуля.
        with open(os.path.join(folder, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "duration": duration,
                    "language": settings.language,
                    "model": settings.whisper_model,
                    "segments": [
                        {"start": s.start, "end": s.end, "text": s.text.strip()}
                        for s in segments
                    ],
                },
                f, ensure_ascii=False,
            )

        with open(os.path.join(root_dir(), MANIFEST), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "at": time.time(), "day": day, "name": name,
                "key_hash": anon(api_key), "duration": duration,
                "bytes": len(wav_bytes), "segments": len(segments),
            }, ensure_ascii=False) + "\n")

        prune()
        return wav_path
    except Exception:  # noqa: BLE001 — сбор датасета не ломает прод
        return ""


@dataclass
class Stats:
    files: int
    minutes: float
    megabytes: float
    days: int


def stats() -> Stats:
    """Сколько уже накоплено — по самим файлам, а не по манифесту.

    Манифест дописывается, а вытеснение удаляет файлы, поэтому источником
    истины об объёме может быть только диск.
    """
    files = 0
    total = 0
    minutes = 0.0
    days = set()
    for path, dur in _iter_records():
        files += 1
        total += os.path.getsize(path)
        minutes += dur / 60.0
        days.add(os.path.basename(os.path.dirname(path)))
    return Stats(files=files, minutes=minutes,
                 megabytes=total / (1 << 20), days=len(days))


def _iter_records() -> list[tuple[str, float]]:
    """Пары (путь к .wav, длительность) — по всем дням, старые первыми."""
    out: list[tuple[str, float]] = []
    base = root_dir()
    if not os.path.isdir(base):
        return out
    for day in sorted(os.listdir(base)):
        folder = os.path.join(base, day)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".wav"):
                continue
            wav = os.path.join(folder, name)
            meta = wav[:-4] + ".json"
            duration = 0.0
            try:
                with open(meta, encoding="utf-8") as f:
                    duration = float(json.load(f).get("duration") or 0.0)
            except Exception:  # noqa: BLE001 — запись без метаданных всё равно считаем
                pass
            out.append((wav, duration))
    return out


def prune() -> int:
    """Удалить самые старые записи, пока объём выше потолка. Вернуть сколько удалено.

    Потолок нужен не ради экономии, а ради живучести: том шлюза общий с БД
    лицензий, и переполнение диска остановило бы продажи.
    """
    limit = settings.dataset_max_mb * (1 << 20)
    if limit <= 0:
        return 0
    records = _iter_records()
    total = sum(os.path.getsize(p) for p, _ in records if os.path.exists(p))
    removed = 0
    for path, _ in records:          # старые первыми
        if total <= limit:
            break
        try:
            total -= os.path.getsize(path)
            os.remove(path)
            meta = path[:-4] + ".json"
            if os.path.exists(meta):
                os.remove(meta)
            removed += 1
        except OSError:
            continue
    return removed


def _main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Датасет казахской речи (NP SUB)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats", help="сколько накоплено")
    sub.add_parser("prune", help="вытеснить старые записи по потолку объёма")
    args = p.parse_args()

    if args.cmd == "prune":
        print(f"Удалено записей: {prune()}")
        return

    s = stats()
    print(f"Папка: {root_dir()}")
    print(f"Записей: {s.files} за {s.days} дн.")
    print(f"Речи: {s.minutes:.1f} мин ({s.minutes / 60:.1f} ч)")
    print(f"Объём: {s.megabytes:.1f} МБ из {settings.dataset_max_mb} МБ")
    if not settings.collect_dataset:
        print("Сбор ВЫКЛЮЧЕН (KZSUB_COLLECT_DATASET=false)")
    elif not settings.collect_keys.strip():
        print("Сбор включён, но KZSUB_COLLECT_KEYS пуст — не собирается ничего")


if __name__ == "__main__":
    _main()
