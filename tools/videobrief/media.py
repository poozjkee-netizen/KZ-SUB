"""Получение материала по ссылке: метаданные, готовые субтитры, аудио.

yt-dlp вызывается как внешняя программа, а не импортируется: она обновляется
чуть ли не еженедельно (площадки меняют выдачу), и держать её версию отдельно
от Python-окружения проще. Разбор её ответа — чистые функции ниже, они
тестируются без установки yt-dlp.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess

YTDLP = os.environ.get("VIDEOBRIEF_YTDLP", "yt-dlp")


class MediaError(RuntimeError):
    """Не удалось получить материал (нет yt-dlp, ссылка недоступна и т.п.)."""


def ensure_ytdlp() -> None:
    if shutil.which(YTDLP) is None:
        raise MediaError(
            f"Не найден {YTDLP}. Установи: pipx install yt-dlp (или brew install yt-dlp)."
        )


def _run(args: list[str], timeout: int = 900) -> str:
    try:
        done = subprocess.run([YTDLP, *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("yt-dlp не ответил вовремя") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()
        raise MediaError("yt-dlp не смог обработать ссылку: "
                         + (tail[-1] if tail else f"код {done.returncode}"))
    return done.stdout


def probe(url: str) -> dict:
    """Метаданные ролика одним запросом (без скачивания)."""
    ensure_ytdlp()
    raw = _run(["-J", "--no-playlist", "--no-warnings", url], timeout=180)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MediaError("yt-dlp вернул не JSON — ссылка не похожа на видео") from exc


def meta_from_info(info: dict) -> dict:
    """Из ответа yt-dlp — только то, что пригодится в разборе и шапке отчёта."""
    return {
        "id": (info.get("id") or "").strip(),
        "title": (info.get("title") or "").strip(),
        "uploader": (info.get("uploader") or info.get("channel") or "").strip(),
        "duration": float(info.get("duration") or 0.0),
        "url": info.get("webpage_url") or info.get("original_url") or "",
        "platform": (info.get("extractor_key") or "").strip(),
        "language": (info.get("language") or "").strip(),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "upload_date": (info.get("upload_date") or "").strip(),
        "description": (info.get("description") or "").strip(),
    }


def _by_language(track: dict) -> dict[str, str]:
    """Дорожки по базовому языку: 'en-US' и 'en' -> 'en'.

    Точное совпадение выигрывает у регионального: 'en' общее, а 'en-US' может
    оказаться машинным переводом с другого языка.
    """
    out: dict[str, str] = {}
    for key in track:
        base = key.split("-")[0]
        if base not in out or key == base:
            out[base] = key
    return out


def pick_subtitle_track(info: dict, priority: list[str],
                        allow_auto: bool) -> tuple[str, bool] | None:
    """Какую дорожку субтитров брать: (язык, авто-субтитры ли) или None.

    Порядок: ручные субтитры на языке ролика -> ручные из списка приоритета ->
    любые ручные -> то же среди авто-субтитров (только если разрешены).
    Ручные всегда выше авто: у авто нет пунктуации и они путают слова, а от
    качества расшифровки зависит весь разбор.
    """
    manual = _by_language(info.get("subtitles") or {})
    auto = _by_language(info.get("automatic_captions") or {})
    own = (info.get("language") or "").split("-")[0]
    order = [lang for lang in [own, *priority] if lang]

    for track, is_auto in ((manual, False), (auto, True)):
        if is_auto and not allow_auto:
            continue
        if not track:
            continue
        for lang in order:
            if lang in track:
                return track[lang], is_auto
        return sorted(track.values())[0], is_auto
    return None


def fetch_subtitles(url: str, lang: str, is_auto: bool, workdir: str) -> str:
    """Скачивает дорожку субтитров и возвращает её содержимое (.vtt)."""
    ensure_ytdlp()
    template = os.path.join(workdir, "subs.%(ext)s")
    _run([
        "--skip-download", "--no-playlist", "--no-warnings",
        "--write-auto-subs" if is_auto else "--write-subs",
        "--sub-langs", lang, "--sub-format", "vtt/srt/best",
        "-o", template, url,
    ], timeout=300)
    files = sorted(glob.glob(os.path.join(workdir, "subs*.vtt"))
                   + glob.glob(os.path.join(workdir, "subs*.srt")))
    if not files:
        raise MediaError(f"Субтитры '{lang}' не скачались")
    with open(files[0], "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def fetch_audio(url: str, workdir: str) -> str:
    """Скачивает только аудиодорожку (mp3) — для распознавания видео не нужно."""
    ensure_ytdlp()
    template = os.path.join(workdir, "audio.%(ext)s")
    args = ["-f", "bestaudio/best", "--no-playlist", "--no-warnings", "-o", template, url]
    if shutil.which("ffmpeg"):
        # Ровный mp3 удобнее для повторных прогонов и меньше весит.
        args = ["-x", "--audio-format", "mp3", *args]
    # Без ffmpeg скачиваем дорожку как есть: faster-whisper декодирует m4a/webm
    # сам (через PyAV), поэтому отдельный ffmpeg для распознавания не нужен.
    _run(args)
    files = sorted(glob.glob(os.path.join(workdir, "audio.*")))
    if not files:
        raise MediaError("Аудио не скачалось")
    return files[0]
