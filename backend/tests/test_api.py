"""Интеграционный тест эндпоинта /transcribe.

Проверяет HTTP-контракт, который использует панель: multipart-загрузка ->
проверка ключа/квоты -> .srt (или JSON). Сама модель Whisper замокана, чтобы
тест был быстрым и не требовал GPU/весов.

Требует установленных fastapi/httpx (см. requirements.txt). Без них — пропуск.
Запуск: pytest backend/tests/test_api.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app import main, quota  # noqa: E402
from app.asr_types import RawSegment, Word  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    quota._usage.clear()

    def fake_transcribe(path):
        # Пословные тайм-коды; большой разрыв (2.5 - 1.2 = 1.3с) между репликами
        # заставит нарезку оставить их отдельными субтитрами.
        return (
            [
                RawSegment(0.0, 1.2, "Сәлеметсіз бе", [
                    Word(0.0, 0.6, "Сәлеметсіз"), Word(0.6, 1.2, "бе"),
                ]),
                RawSegment(2.5, 3.5, "Қалыңыз қалай", [
                    Word(2.5, 3.0, "Қалыңыз"), Word(3.0, 3.5, "қалай"),
                ]),
            ],
            3.5,
        )

    # Подменяем тяжёлую транскрибацию заглушкой.
    monkeypatch.setattr(main, "transcribe_file", fake_transcribe)
    return TestClient(main.app)


def _audio_file():
    return {"file": ("clip.wav", b"\x00" * 1024, "audio/wav")}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["language"] == "kk"


def test_requires_api_key(client):
    r = client.post("/transcribe", files=_audio_file())
    assert r.status_code == 401


def test_transcribe_returns_srt(client):
    r = client.post("/transcribe", files=_audio_file(), headers={"X-API-Key": "dev-key"})
    assert r.status_code == 200
    body = r.text
    assert "00:00:00,000 --> 00:00:01,200" in body
    assert "Сәлеметсіз бе" in body


def test_transcribe_json_format(client):
    r = client.post(
        "/transcribe?fmt=json", files=_audio_file(), headers={"X-API-Key": "dev-key"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["language"] == "kk"
    assert len(data["segments"]) == 2
    assert data["segments"][0]["text"] == "Сәлеметсіз бе"
    assert data["segments"][1]["text"] == "Қалыңыз қалай"


def test_invalid_key_rejected(client):
    r = client.post("/transcribe", files=_audio_file(), headers={"X-API-Key": "bogus"})
    assert r.status_code == 402  # QuotaError -> 402
