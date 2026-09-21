"""Весь прогон целиком: ссылка -> файлы на диске.

Один путь на всё: окно программы (webapp.py) и командная строка (cli.py) зовут
отсюда `run`. О ходе дела сообщает колбэк `on_step` — ни print, ни HTTP тут нет.

Порядок: метаданные -> текст (субтитры ролика или распознавание) -> чистка ->
разбор локальной моделью -> файлы.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
import time
from dataclasses import dataclass, field
from typing import Callable

from . import asr, captions, llm, media, prompt as prompt_mod, transcript as tr
from .settings import load as load_settings

Step = Callable[[str], None]
# Обновление последней строки статуса. Нужно отдельно от `on_step`: пока модель
# пишет ответ, новых шагов нет — меняется только счётчик внутри текущего.
Tick = Callable[[str], None]

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ә": "a", "ғ": "g", "қ": "q", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "і": "i",
}


@dataclass
class Options:
    """Что и как разбираем. Пустые поля берутся из настроек программы."""
    source: str                    # ссылка или путь к файлу
    out_root: str = ""
    audience: str = ""
    model_path: str = ""           # .gguf; пусто = выбрать самой
    whisper: str = ""
    ctx: int = 0
    max_chars: int = 0
    mode: str = "auto"             # auto | subs | asr
    transcript: str | None = None  # готовая расшифровка с диска
    lang: str | None = None        # язык речи для распознавания
    analyze: bool = True
    keep_work: bool = False

    def filled(self) -> "Options":
        """Подставляет настройки туда, где пусто. Настройки читаются один раз."""
        cfg = load_settings()
        return Options(
            source=self.source,
            out_root=self.out_root or cfg["out_dir"],
            audience=self.audience or cfg["audience"],
            model_path=self.model_path or cfg["model_path"],
            whisper=self.whisper or cfg["whisper"],
            ctx=self.ctx or cfg["ctx"],
            max_chars=self.max_chars or cfg["max_chars"],
            mode=self.mode, transcript=self.transcript, lang=self.lang,
            analyze=self.analyze, keep_work=self.keep_work,
        )


@dataclass
class Result:
    """Итог прогона: куда что легло, чем расшифровано и чем разобрано."""
    out_dir: str
    transcript_path: str
    timed_path: str
    prompt_path: str
    meta_path: str
    meta: dict
    source_note: str
    brief_path: str | None = None
    analysis_error: str | None = None
    model_note: str = ""
    files: dict = field(default_factory=dict)


def _noop(_: str) -> None:
    pass


def extract_section(markdown: str, number: int) -> str:
    """Достаёт раздел разбора по номеру: '## 5. …' до следующего '## '.

    Зачем: раздел «Сценарий целиком на русском» — это и есть текст ролика
    по-русски. Показать его отдельной вкладкой дешевле, чем гонять модель ещё
    раз ради перевода.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    taking = False
    for line in lines:
        if line.startswith("## "):
            if taking:
                break
            head = line[3:].lstrip()
            taking = head.startswith(f"{number}.") or head.startswith(f"{number} ")
            continue
        if taking:
            out.append(line)
    return "\n".join(out).strip()


def _fill(meta: dict, key: str, value) -> None:
    """Проставляет поле, если его нет ИЛИ оно пустое.

    setdefault тут не годится: yt-dlp кладёт пустые строки вместо отсутствующих
    полей, и они молча побеждали бы наши запасные значения.
    """
    if not meta.get(key):
        meta[key] = value


def _short(exc: Exception, limit: int = 60) -> str:
    """Короткая причина отказа для строки статуса — без простыни из stderr."""
    text = " ".join(str(exc).split())
    if "429" in text:
        return "площадка ограничила запросы"
    return text[:limit] + ("…" if len(text) > limit else "")


def slugify(title: str, fallback: str = "video") -> str:
    """Название ролика -> имя папки: латиница, дефисы, не длиннее 60 символов.

    Кириллица транслитерируется, а не выбрасывается: иначе все казахские и
    русские ролики получили бы одно имя папки и затирали друг друга.
    """
    text = unicodedata.normalize("NFKC", title or "").lower()
    out = []
    for ch in text:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-{2,}", "-", "".join(out)).strip("-")[:60].strip("-")
    return slug or fallback


def folder_name(meta: dict) -> str:
    """Имя папки ролика: '<название>-<id площадки>'.

    Идентификатор в имени нужен против совпадений: у виральных роликов названия
    повторяются, и без него один разбор затирал бы другой. Повторный прогон
    того же ролика, наоборот, обязан попадать в ту же папку — поэтому
    идентификатор, а не дата.
    """
    slug = slugify(meta.get("title") or "")
    video_id = re.sub(r"[^A-Za-z0-9_-]", "", str(meta.get("id") or ""))[:12]
    return f"{slug}-{video_id}" if video_id else slug


def header(meta: dict, source_note: str, model_note: str) -> str:
    """Шапка brief.md: откуда ролик, чем расшифрован, чем разобран."""
    lines = [f"# Разбор: {meta.get('title') or 'ролик без названия'}", ""]
    rows = [
        ("Ссылка", meta.get("url")),
        ("Автор", meta.get("uploader")),
        ("Площадка", meta.get("platform")),
        ("Длительность", tr.format_tc(meta["duration"]) if meta.get("duration") else None),
        ("Просмотры", meta.get("view_count")),
        ("Расшифровка", source_note),
        ("Разбор", model_note),
    ]
    lines += [f"- **{name}:** {value}" for name, value in rows if value not in (None, "")]
    lines.append("")
    return "\n".join(lines)


def read_transcript_file(path: str) -> list[tr.Segment]:
    """Готовая расшифровка с диска: .vtt/.srt/наш '[MM:SS] …' или сплошной текст."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    for parse in (captions.parse, tr.parse_timed_text):
        segments = parse(content)
        if segments:
            return segments
    text = " ".join(content.split())
    return [tr.Segment(start=0.0, end=0.0, text=text)] if text else []


def collect(opts: Options, workdir: str,
            on_step: Step = _noop) -> tuple[list[tr.Segment], dict, str, bool]:
    """Достаёт расшифровку и метаданные. -> (сегменты, мета, чем расшифровано, авто?)."""
    is_local = os.path.exists(opts.source)

    if opts.transcript:
        meta = ({} if is_local or not opts.source.startswith("http")
                else media.meta_from_info(media.probe(opts.source)))
        _fill(meta, "title", os.path.splitext(os.path.basename(opts.source))[0])
        _fill(meta, "url", opts.source)
        on_step(f"Беру готовую расшифровку: {os.path.basename(opts.transcript)}")
        return read_transcript_file(opts.transcript), meta, "файл на диске", False

    if is_local:
        meta = {"title": os.path.splitext(os.path.basename(opts.source))[0],
                "url": os.path.abspath(opts.source)}
        audio_path = opts.source
    else:
        on_step("Читаю ролик по ссылке…")
        info = media.probe(opts.source)
        meta = media.meta_from_info(info)
        if meta.get("title"):
            on_step(f"Ролик: {meta['title']}")
        if opts.mode != "asr":
            segments, note, is_auto = _try_subtitles(opts, info, meta, workdir, on_step)
            if segments:
                return segments, meta, note, is_auto
        if opts.mode == "subs":
            raise media.MediaError(
                "Субтитров у ролика нет, а режим «только субтитры» запрещает "
                "распознавание.")
        on_step("Скачиваю аудиодорожку…")
        audio_path = media.fetch_audio(opts.source, workdir)

    on_step(f"Распознаю речь ({opts.whisper}) — это самая долгая часть")
    segments, detected = asr.transcribe(audio_path, opts.whisper, opts.lang)
    if detected:
        _fill(meta, "language", detected)
    return segments, meta, f"Whisper {opts.whisper}, язык {detected or 'не определён'}", False


def _try_subtitles(opts: Options, info: dict, meta: dict, workdir: str,
                   on_step: Step) -> tuple[list[tr.Segment], str, bool]:
    """Готовые субтитры ролика, если они есть и площадка их отдаёт.

    Отказ площадки (429, приватный ролик, битая дорожка) не валит прогон: звук
    всё равно можно распознать. Исключение — режим «только субтитры».
    """
    track = media.pick_subtitle_track(info, ["ru", "en", "kk"], allow_auto=True)
    if not track:
        on_step("Готовых субтитров нет — распознаю звук")
        return [], "", False

    lang, is_auto = track
    kind = "авто-субтитры" if is_auto else "субтитры автора"
    on_step(f"Беру {kind} ({lang}) — это быстро")
    try:
        segments = captions.parse(
            media.fetch_subtitles(opts.source, lang, is_auto, workdir))
    except media.MediaError as exc:
        if opts.mode == "subs":
            raise
        on_step(f"Субтитры не отдались ({_short(exc)}) — распознаю звук")
        return [], "", False

    if not segments:
        on_step("Субтитры пустые — распознаю звук")
        return [], "", False
    _fill(meta, "language", lang.split("-")[0])
    return segments, f"{kind} ролика, язык {lang}", is_auto


def _live(on_tick: Tick, label: str):
    """Колбэк для llm.generate: пишет в статус, сколько модель уже наговорила.

    Без этого длинный разбор выглядит зависшим: одна строка висит минутами.
    """
    state = {"chars": 0, "shown": 0.0, "start": time.monotonic()}

    def on_token(piece: str) -> None:
        state["chars"] += len(piece)
        now = time.monotonic()
        if now - state["shown"] < 0.7:   # чаще обновлять незачем
            return
        state["shown"] = now
        seconds = int(now - state["start"])
        on_tick(f"{label} · {seconds} с, {state['chars'] // 5} слов")

    return on_token


def analyze(opts: Options, meta: dict, timed: str, source_note: str,
            on_step: Step, on_tick: Tick = _noop) -> tuple[str, str]:
    """Разбор локальной моделью. Длинную расшифровку сначала сжимает по частям."""
    models = llm.find_models()
    model_path = llm.pick(models, opts.model_path)
    if not model_path:
        raise llm.LLMError(
            "Не нашёл ни одной модели .gguf. Положи её в ~/Models или укажи "
            "файл в настройках (⚙︎)."
        )
    name = os.path.basename(model_path)

    note = source_note
    if tr.needs_condensing(timed, opts.max_chars):
        parts = tr.split_lines(timed, opts.max_chars)
        notes: list[str] = []
        for index, part in enumerate(parts, 1):
            label = f"Ролик длинный: сжимаю часть {index} из {len(parts)}"
            on_step(label)
            notes.append(llm.generate(
                model_path, prompt_mod.CONDENSE_SYSTEM,
                prompt_mod.build_condense(part, index, len(parts)), ctx=opts.ctx,
                on_token=_live(on_tick, label)))
        timed = "\n\n".join(notes)
        note = f"{source_note}; длинный ролик сжат по частям"

    label = f"Разбираю на устройстве: {name}"
    on_step(label)
    task = prompt_mod.build(meta, timed, opts.audience, note)
    text = llm.generate(model_path, prompt_mod.SYSTEM, task, ctx=opts.ctx,
                        max_tokens=8192, on_token=_live(on_tick, label))
    return text, name


def run(opts: Options, on_step: Step = _noop, on_tick: Tick = _noop) -> Result:
    """Полный прогон. Бросает MediaError/RuntimeError, если материал не достался.

    Ошибка разбора прогон НЕ валит: расшифровка уже получена и стоила времени,
    поэтому она сохраняется, а причина кладётся в `analysis_error`.
    """
    opts = opts.filled()
    out_root = os.path.abspath(opts.out_root)
    workdir = os.path.join(out_root, ".work")
    os.makedirs(workdir, exist_ok=True)

    segments, meta, source_note, is_auto = collect(opts, workdir, on_step)
    if not segments:
        raise media.MediaError("В ролике не нашлось речи — разбирать нечего.")

    if is_auto:
        # Авто-субтитры идут «бегущей строкой» с повторами — без чистки текст
        # раздувается вдвое и сбивает разбор.
        segments = tr.dedupe_rolling(segments)
    blocks = tr.merge_blocks(segments)
    _fill(meta, "duration", tr.duration(segments))

    out_dir = os.path.join(out_root, folder_name(meta))
    os.makedirs(out_dir, exist_ok=True)

    clean = tr.clean_text(blocks)
    timed = tr.timed_text(blocks)
    task = prompt_mod.build(meta, timed, opts.audience, source_note)

    paths = {name: os.path.join(out_dir, filename) for name, filename in (
        ("transcript", "transcript.txt"), ("timed", "transcript.timed.txt"),
        ("prompt", "prompt.txt"), ("meta", "meta.json"))}
    _write(paths["transcript"], clean)
    _write(paths["timed"], timed)
    _write(paths["prompt"], task + "\n")
    _write(paths["meta"], json.dumps({**meta, "transcript_source": source_note},
                                     ensure_ascii=False, indent=2) + "\n")

    if not opts.keep_work:
        shutil.rmtree(workdir, ignore_errors=True)

    result = Result(out_dir=out_dir, transcript_path=paths["transcript"],
                    timed_path=paths["timed"], prompt_path=paths["prompt"],
                    meta_path=paths["meta"], meta=meta, source_note=source_note,
                    files={"clean": clean, "timed": timed})
    if not opts.analyze:
        return result

    try:
        analysis, model_note = analyze(opts, meta, timed, source_note, on_step, on_tick)
    except (llm.LLMError, RuntimeError) as exc:
        result.analysis_error = str(exc)
        return result

    result.model_note = model_note
    result.brief_path = os.path.join(out_dir, "brief.md")
    brief = header(meta, source_note, model_note) + analysis + "\n"
    _write(result.brief_path, brief)
    result.files["brief"] = brief
    # Текст ролика по-русски — это раздел «Сценарий целиком на русском».
    script_ru = extract_section(analysis, 5)
    result.files["script_ru"] = script_ru
    if script_ru:
        _write(os.path.join(out_dir, "script.ru.txt"), script_ru + "\n")
    return result


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
