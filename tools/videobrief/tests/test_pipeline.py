"""Тесты выбора дорожки субтитров, промпта и оформления отчёта.

Запуск: python tools/videobrief/tests/test_pipeline.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import shutil  # noqa: E402
import tempfile  # noqa: E402

# Настройки программы не должны утекать из системы в тест и наоборот.
os.environ["VIDEOBRIEF_STATE_DIR"] = tempfile.mkdtemp(prefix="npbrief-cfg-")

from videobrief import asr, media, pipeline, prompt as prompt_mod  # noqa: E402
from videobrief.transcript import Segment  # noqa: E402
from videobrief.media import meta_from_info, pick_subtitle_track  # noqa: E402
from videobrief.pipeline import (extract_section, folder_name,  # noqa: E402
                                 header, slugify)

PRIORITY = ["ru", "en", "kk"]


def test_pick_prefers_manual_over_auto():
    info = {"subtitles": {"en": [{}]}, "automatic_captions": {"ru": [{}]}}
    assert pick_subtitle_track(info, PRIORITY, allow_auto=True) == ("en", False)


def test_pick_prefers_video_language():
    info = {"subtitles": {"en": [{}], "es": [{}]}, "language": "es"}
    assert pick_subtitle_track(info, PRIORITY, allow_auto=False) == ("es", False)


def test_pick_falls_back_to_any_manual():
    info = {"subtitles": {"pt": [{}]}}
    assert pick_subtitle_track(info, PRIORITY, allow_auto=False) == ("pt", False)


def test_pick_auto_only_when_allowed():
    info = {"automatic_captions": {"en": [{}]}}
    assert pick_subtitle_track(info, PRIORITY, allow_auto=False) is None
    assert pick_subtitle_track(info, PRIORITY, allow_auto=True) == ("en", True)


def test_pick_ignores_regional_suffix():
    info = {"subtitles": {"en-US": [{}], "en": [{}]}}
    assert pick_subtitle_track(info, PRIORITY, allow_auto=False) == ("en", False)


def test_pick_nothing_at_all():
    assert pick_subtitle_track({}, PRIORITY, allow_auto=True) is None


def test_meta_from_info_keeps_only_useful():
    meta = meta_from_info({"title": " Хук ", "channel": "Канал", "duration": 61,
                           "webpage_url": "https://x/y", "extractor_key": "Youtube"})
    assert meta["title"] == "Хук"
    assert meta["uploader"] == "Канал"
    assert meta["duration"] == 61.0
    assert meta["url"] == "https://x/y"


def test_prompt_contains_transcript_and_rules():
    meta = {"title": "Как залетают ролики", "url": "https://x/y", "duration": 42,
            "description": "описание"}
    task = prompt_mod.build(meta, "[00:00] hello", "предприниматели", "субтитры автора")
    assert "[00:00] hello" in task
    assert "Как залетают ролики" in task
    assert "предприниматели" in task
    assert "субтитры автора" in task
    assert "описание" in task
    # Пустые поля в промпт не попадают — иначе модель принимает их за факты.
    assert "Просмотры" not in task
    assert "русском" in prompt_mod.SYSTEM


def test_prompt_trims_long_description():
    meta = {"title": "t", "description": "д" * 3000}
    task = prompt_mod.build(meta, "[00:00] x", "все", "файл на диске")
    assert "д" * 1500 in task and "д" * 1600 not in task


def test_slugify():
    assert slugify("Как залетают Ролики!") == "kak-zaletayut-roliki"
    assert slugify("Қазақша видео") == "qazaqsha-video"
    assert slugify("") == "video"
    assert slugify("!!!") == "video"
    assert len(slugify("а" * 200)) <= 60


def test_folder_name_adds_video_id():
    assert folder_name({"title": "Хук", "id": "dQw4w9WgXcQ"}) == "huk-dQw4w9WgXcQ"
    assert folder_name({"title": "Хук"}) == "huk"
    # Идентификатор чистится: он попадает в путь на диске.
    assert folder_name({"title": "x", "id": "../../etc"}) == "x-etc"


def test_header_lists_source():
    out = header({"title": "Ролик", "url": "https://x", "duration": 95},
                 "субтитры автора, язык en", "claude-opus-5")
    assert "# Разбор: Ролик" in out
    assert "**Длительность:** 01:35" in out
    assert "claude-opus-5" in out
    assert "Автор" not in out  # пустое поле не печатаем


def test_subtitle_failure_falls_back_to_speech():
    """Площадка ответила 429 на субтитры — прогон идёт дальше через звук.

    Это поведение появилось после живого случая: YouTube ограничил выдачу
    субтитров, и разбор падал целиком, хотя аудио скачать было можно.
    """
    work = tempfile.mkdtemp(prefix="npbrief-429-")
    original = (media.probe, media.fetch_subtitles, media.fetch_audio, asr.transcribe)
    try:
        media.probe = lambda url: {"title": "Ролик", "id": "abc",
                                   "automatic_captions": {"en": [{}]}}
        def refuse(*args, **kwargs):
            raise media.MediaError(
                "yt-dlp не смог обработать ссылку: HTTP Error 429: Too Many Requests")
        media.fetch_subtitles = refuse
        media.fetch_audio = lambda url, workdir: os.path.join(workdir, "audio.mp3")
        asr.transcribe = lambda *a, **k: ([Segment(0.0, 2.0, "распознанный текст")], "en")

        steps = []
        opts = pipeline.Options(source="https://youtu.be/abc", out_root=work,
                                analyze=False)
        result = pipeline.run(opts, steps.append)

        assert "Whisper" in result.source_note
        assert any("ограничила запросы" in s for s in steps), steps
        with open(result.transcript_path, encoding="utf-8") as fh:
            assert "распознанный текст" in fh.read()
    finally:
        media.probe, media.fetch_subtitles, media.fetch_audio, asr.transcribe = original
        shutil.rmtree(work, ignore_errors=True)


def test_subs_only_mode_still_fails_loudly():
    """В режиме «только субтитры» отказ площадки — именно отказ, без подмены."""
    work = tempfile.mkdtemp(prefix="npbrief-429-")
    original = (media.probe, media.fetch_subtitles)
    try:
        media.probe = lambda url: {"title": "Ролик", "subtitles": {"en": [{}]}}
        def refuse(*args, **kwargs):
            raise media.MediaError("HTTP Error 429: Too Many Requests")
        media.fetch_subtitles = refuse
        opts = pipeline.Options(source="https://youtu.be/abc", out_root=work,
                                mode="subs", analyze=False)
        try:
            pipeline.run(opts)
        except media.MediaError as exc:
            assert "429" in str(exc)
        else:
            raise AssertionError("режим «только субтитры» промолчал об отказе")
    finally:
        media.probe, media.fetch_subtitles = original
        shutil.rmtree(work, ignore_errors=True)


BRIEF = """# Разбор: ролик

## 4. Структура по блокам

| Тайм-код | Блок |
|---|---|
| 00:00 | Хук |

## 5. Сценарий целиком на русском

[00:00] Привет, это гайд по SP-404.

[00:12] Сначала про питание.

## 6. Каркас для повторного использования

хук → история → вывод
"""


def test_extract_section_takes_one_section():
    """Русский текст ролика достаётся из разбора, без повторного вызова модели."""
    out = extract_section(BRIEF, 5)
    assert out.startswith("[00:00] Привет")
    assert "Сначала про питание" in out
    # Соседние разделы не прилипают.
    assert "Каркас" not in out and "Хук" not in out


def test_extract_section_is_robust():
    assert extract_section(BRIEF, 9) == ""          # нет такого раздела
    assert extract_section("", 5) == ""             # пустой разбор
    # Номер сверяется целиком: раздел 1 не должен ловиться запросом 15.
    assert extract_section("## 1. Первый\nтекст", 15) == ""


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok {name}")
    print("test_pipeline: всё зелёное")


if __name__ == "__main__":
    run()
