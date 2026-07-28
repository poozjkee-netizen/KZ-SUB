"""Тесты сбора датасета (dep-free: только stdlib).

Запуск: python tests/test_dataset.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import dataset  # noqa: E402
from app.config import settings  # noqa: E402
from app.srt import Segment  # noqa: E402


def _fresh(**over):
    """Чистая папка датасета и настройки сбора под конкретный тест."""
    settings.state_dir = tempfile.mkdtemp()
    settings.collect_dataset = over.get("collect", True)
    settings.collect_keys = over.get("keys", "my-key")
    settings.dataset_max_mb = over.get("max_mb", 300)


def _segs():
    return [Segment(0.0, 1.0, "сәлем"), Segment(1.0, 2.0, "әлем")]


def test_collect_only_from_listed_keys():
    _fresh(keys="my-key, second-key")
    assert dataset.should_collect("my-key")
    assert dataset.should_collect("second-key")
    assert not dataset.should_collect("chужой-ключ")
    assert not dataset.should_collect("")


def test_disabled_by_default_and_without_keys():
    """Включённый сбор без списка ключей не собирает ничего.

    Это защита от молчаливого сбора чужой речи: «включил и забыл» не должно
    приводить к тому, что на томе оказались записи пользователей.
    """
    _fresh(collect=False)
    assert not dataset.should_collect("my-key")
    _fresh(keys="   ")
    assert not dataset.should_collect("my-key")


def test_store_writes_audio_and_draft_markup():
    _fresh()
    path = dataset.store("my-key", b"RIFF" + b"\0" * 100, _segs(), duration=2.0)
    assert path and os.path.exists(path)

    with open(path[:-4] + ".json", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["duration"] == 2.0
    assert [s["text"] for s in meta["segments"]] == ["сәлем", "әлем"]

    s = dataset.stats()
    assert (s.files, s.days) == (1, 1)
    assert abs(s.minutes - 2.0 / 60) < 1e-9


def test_manifest_records_hash_not_the_key():
    _fresh()
    dataset.store("my-key", b"x" * 50, _segs(), duration=1.0)
    with open(os.path.join(dataset.root_dir(), dataset.MANIFEST), encoding="utf-8") as f:
        row = json.loads(f.readline())
    assert "my-key" not in json.dumps(row, ensure_ascii=False)
    assert row["key_hash"] and row["segments"] == 2


def test_empty_audio_is_not_stored():
    _fresh()
    assert dataset.store("my-key", b"", _segs(), duration=1.0) == ""
    assert dataset.stats().files == 0


def test_oldest_records_are_evicted_by_size_cap():
    """Том общий с БД лицензий: датасет не имеет права переполнить диск."""
    _fresh(max_mb=1)
    chunk = b"\0" * (400 * 1024)          # 0.4 МБ за запись
    for _ in range(4):                     # 1.6 МБ при потолке 1 МБ
        dataset.store("my-key", chunk, _segs(), duration=1.0)
    s = dataset.stats()
    assert s.files < 4                     # старые вытеснены
    assert s.megabytes <= 1.0


def test_store_never_raises_on_broken_path():
    """Сбор датасета не может сорвать выдачу субтитров пользователю."""
    _fresh()
    settings.state_dir = "/proc/nonexistent-\0/dataset"
    assert dataset.store("my-key", b"x" * 10, _segs(), duration=1.0) == ""


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok: {name}")
    print("Все тесты датасета пройдены.")
