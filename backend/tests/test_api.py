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
from app.srt import Segment  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    quota._usage.clear()

    def fake_transcribe(path):
        return (
            [Segment(0.0, 1.2, "Сәлеметсіз бе"), Segment(1.2, 2.5, "Қалыңыз қалай")],
            2.5,
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


def test_invalid_key_rejected(client):
    r = client.post("/transcribe", files=_audio_file(), headers={"X-API-Key": "bogus"})
    assert r.status_code == 402  # QuotaError -> 402
