"""Напоминания клиенту: минуты кончаются, подписка истекает.

Зачем: по метрикам видно, что отказ `http_402` — это не поломка, а человек,
упёршийся в лимит. Но узнаёт он об этом в момент, когда уже монтирует ролик и
работа встала. Предупредить заранее дешевле и для него, и для нас: это и
удержание платящих, и главный момент апсейла demo → standard.

Канал — тот же Telegram-бот, что выдаёт ключи: у ключей, выданных им, в поле
email лежит "tg:<id>", то есть адресат уже известен и ничего спрашивать не надо.
Ключам, выданным вручную, писать некуда — они просто пропускаются.

Что защищает от спама: метка `notified` в самой лицензии. Она сбрасывается при
продлении, пополнении и смене тарифа — то есть любое изменение квоты снова
разрешает предупредить.

Только stdlib — модуль остаётся dep-free-тестируемым.

CLI:
    python -m app.notify list     # кому и что отправилось бы (ничего не шлёт)
    python -m app.notify send     # отправить
"""
from __future__ import annotations

import time

from . import licenses
from .config import settings
from .licenses import License, LicenseStatus, LicenseType

# Доля остатка, ниже которой предупреждаем. Нужна из-за demo на 3 минуты:
# абсолютный порог в 5 минут сработал бы на нём сразу при выдаче.
LOW_FRACTION = 0.25


def _low_threshold(total: float) -> float:
    return min(settings.notify_min_minutes, total * LOW_FRACTION)


def reminder_for(lic: License, now: float | None = None) -> tuple[str, str] | None:
    """Нужно ли предупредить владельца лицензии. Возвращает (метка, текст) или None.

    Метка — то, что кладётся в `notified`: одинаковая метка второй раз не шлётся.
    """
    now = time.time() if now is None else now
    if lic.status != LicenseStatus.ACTIVE or lic.type == LicenseType.DEVELOPER:
        return None

    # Срок: предупреждаем за N дней. Уже истёкшие не трогаем — там сработает
    # обычный отказ при следующем прогоне, и это честнее любого напоминания.
    if lic.expires_at:
        days_left = (lic.expires_at - now) / 86400
        if 0 < days_left <= settings.notify_days_before:
            kk = "бүгін" if days_left < 1 else f"{int(days_left) + 1} күн ішінде"
            ru = "сегодня" if days_left < 1 else f"через {int(days_left) + 1} дн."
            return ("expiring", (
                f"NP SUB: жазылым мерзімі аяқталуға жақын ({kk}).\n"
                "Жалғастыру үшін — /buy.\n\n"
                f"NP SUB: подписка заканчивается {ru}\n"
                "Продлить — команда /buy."
            ))

    # Минуты: только когда ими уже пользовались. Предупреждение при нулевом
    # расходе означало бы «у вас маленький тариф» — это не напоминание, а упрёк.
    total = lic.total_minutes
    remaining = lic.remaining_minutes()
    if total and remaining is not None and lic.used_minutes > 0:
        if remaining <= _low_threshold(total):
            left = f"{remaining:.1f}".rstrip("0").rstrip(".")
            demo = lic.type == LicenseType.TRIAL
            tail = ("Толық нұсқа — /buy.\n\nПолная версия — команда /buy."
                    if demo else
                    "Толықтыру — /buy.\n\nПополнить — команда /buy.")
            return ("low_minutes", (
                f"NP SUB: қалған уақыт {left} мин.\n{tail}"
            ))
    return None


def pending(now: float | None = None) -> list[tuple[License, str, str]]:
    """Кому и что стоит отправить прямо сейчас (без отправки)."""
    out = []
    for lic in licenses.list_licenses():
        hit = reminder_for(lic, now)
        if hit is None:
            continue
        tag, text = hit
        if licenses.get_notified(lic.api_key) == tag:
            continue                       # об этом уже предупреждали
        out.append((lic, tag, text))
    return out


def chat_id_of(lic: License) -> str:
    """Telegram-чат владельца: ключи бота хранят "tg:<id>" в поле email."""
    return lic.email[3:] if lic.email.startswith("tg:") else ""


def send_reminders(now: float | None = None) -> int:
    """Разослать напоминания. Возвращает число отправленных.

    Метку ставим только после успешной отправки: иначе сбой Telegram навсегда
    съел бы предупреждение, и клиент упёрся бы в лимит без предупреждения.
    """
    if not settings.notify_enabled or not settings.telegram_bot_token:
        return 0
    from . import telegram_bot          # лениво: тянет настройки бота

    sent = 0
    for lic, tag, text in pending(now):
        chat = chat_id_of(lic)
        if not chat:
            continue                     # ключ выдан вручную — писать некуда
        try:
            telegram_bot.send_message(chat, text)
        except Exception:  # noqa: BLE001 — один недоступный чат не рвёт рассылку
            continue
        licenses.set_notified(lic.api_key, tag)
        sent += 1
    return sent


def _main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Напоминания клиентам NP SUB")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="кому и что отправилось бы (ничего не шлёт)")
    sub.add_parser("send", help="отправить напоминания")
    args = p.parse_args()

    if args.cmd == "send":
        print(f"Отправлено: {send_reminders()}")
        return

    rows = pending()
    if not rows:
        print("Некому напоминать.")
        return
    for lic, tag, text in rows:
        where = chat_id_of(lic) or "нет канала (ключ выдан вручную)"
        print(f"[{tag}] {lic.type} {lic.api_key[:12]}… → {where}")
        print("    " + text.replace("\n", "\n    "))


if __name__ == "__main__":
    _main()
