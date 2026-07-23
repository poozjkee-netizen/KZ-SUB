"""Интеграционный тест эндпоинта /transcribe.

Проверяет HTTP-контракт, который использует панель: multipart-загрузка ->
проверка лицензии/минут -> .srt (или JSON). Сама модель Whisper замокана,
чтобы тест был быстрым и не требовал GPU/весов.

Требует установленных fastapi/httpx (см. requirements.txt). Без них — пропуск.
Запуск: pytest backend/tests/test_api.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app import licenses, main  # noqa: E402
from app.asr_types import RawSegment, Word  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app import devices
    # Свежая БД лицензий на временном файле + валидный ключ "dev-key"
    # (developer-лицензия: без лимитов, чтобы тесты контракта не упирались в квоты).
    licenses.configure(str(tmp_path / "lic.db"))
    licenses.init_db()
    licenses.create_license("dev@test", licenses.LicenseType.DEVELOPER, api_key="dev-key")
    devices._bindings.clear()
    devices._loaded = True  # не читать состояние с диска в тестах

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


def _headers(key="dev-key", device="test-device-1"):
    return {"X-API-Key": key, "X-Device-Id": device}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["language"] == "kk"


def test_requires_api_key(client):
    r = client.post("/transcribe", files=_audio_file())
    assert r.status_code == 401


def test_transcribe_returns_srt(client):
    r = client.post("/transcribe", files=_audio_file(), headers=_headers())
    assert r.status_code == 200
    body = r.text
    assert "00:00:00,000 --> 00:00:01,200" in body
    assert "Сәлеметсіз бе" in body


def test_transcribe_json_format(client):
    r = client.post(
        "/transcribe?fmt=json", files=_audio_file(), headers=_headers()
    )
    assert r.status_code == 200
    data = r.json()
    assert data["language"] == "kk"
    assert len(data["segments"]) == 2
    assert data["segments"][0]["text"] == "Сәлеметсіз бе"
    assert data["segments"][1]["text"] == "Қалыңыз қалай"


def test_invalid_key_rejected(client):
    r = client.post("/transcribe", files=_audio_file(), headers=_headers(key="bogus"))
    assert r.status_code == 401  # неизвестный ключ -> InvalidKey -> 401


def test_exhausted_key_is_402(client):
    """Лицензия без остатка минут -> 402."""
    licenses.create_license("x@test", licenses.LicenseType.MINUTE_PACK,
                            total_minutes=0.0, api_key="empty-key")
    r = client.post("/transcribe", files=_audio_file(), headers=_headers(key="empty-key"))
    assert r.status_code == 402


def test_minutes_remaining_header(client):
    """Ответ несёт остаток минут (для баланса в панели/кабинете)."""
    licenses.create_license("y@test", licenses.LicenseType.SUBSCRIPTION,
                            total_minutes=100, api_key="lim-key")
    r = client.post("/transcribe", files=_audio_file(), headers=_headers(key="lim-key"))
    assert r.status_code == 200
    assert "X-Minutes-Remaining" in r.headers


def test_device_limit_enforced(client, monkeypatch):
    """Третье устройство на одном ключе получает 403."""
    from app.config import settings as cfg
    monkeypatch.setattr(cfg, "max_devices_per_key", 2)

    for dev in ("dev-1", "dev-2"):
        r = client.post("/transcribe", files=_audio_file(), headers=_headers(device=dev))
        assert r.status_code == 200
    # повторно с известного устройства — ок
    r = client.post("/transcribe", files=_audio_file(), headers=_headers(device="dev-1"))
    assert r.status_code == 200
    # новое третье устройство — отказ
    r = client.post("/transcribe", files=_audio_file(), headers=_headers(device="dev-3"))
    assert r.status_code == 403


def test_missing_device_header_rejected(client):
    r = client.post("/transcribe", files=_audio_file(), headers={"X-API-Key": "dev-key"})
    assert r.status_code == 403


def test_proxy_mode_returns_srt(client, monkeypatch):
    """Прокси-режим: сегменты приходят готовыми от Runpod-воркера."""
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "runpod_endpoint_id", "ep123")
    monkeypatch.setattr(cfg, "runpod_api_key", "rp_secret")

    def fake_runpod(audio_bytes, fmt="json"):
        assert isinstance(audio_bytes, bytes) and len(audio_bytes) > 0
        return {
            "language": "kk",
            "duration": 2.0,
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "СӘЛЕМ"},
                {"start": 1.0, "end": 2.0, "text": "ӘЛЕМ!"},
            ],
        }

    monkeypatch.setattr(main, "transcribe_via_runpod", fake_runpod)

    r = client.post("/transcribe", files=_audio_file(), headers=_headers())
    assert r.status_code == 200
    assert "СӘЛЕМ" in r.text
    assert "ӘЛЕМ!" in r.text
    assert "00:00:01,000 --> 00:00:02,000" in r.text


def test_proxy_mode_runpod_error_is_502(client, monkeypatch):
    from app.config import settings as cfg
    from app.runpod_client import RunpodError

    monkeypatch.setattr(cfg, "runpod_endpoint_id", "ep123")
    monkeypatch.setattr(cfg, "runpod_api_key", "rp_secret")

    def broken(audio_bytes, fmt="json"):
        raise RunpodError("boom")

    monkeypatch.setattr(main, "transcribe_via_runpod", broken)

    r = client.post("/transcribe", files=_audio_file(), headers=_headers())
    assert r.status_code == 502
