# config.py – конфигурация Barbershop Telegram Bot

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Dict

# Токен бота — обязательно заменить на свой!
BOT_TOKEN: str = "8246992078:AAG30Zg-Qjx5QT6Xaqt9CVt_KAKWS5yc25c"
if not BOT_TOKEN:
    raise RuntimeError("⚠️ Токен бота не указан!")

_env_admins = os.getenv("ADMIN_IDS")
if _env_admins:
    ADMIN_IDS: List[int] = [int(x) for x in _env_admins.split(",") if x.strip()]
else:
    ADMIN_IDS = [895245154]

REMINDER_HOURS: List[int] = [24, 1]
BACKGROUND_CHECK_INTERVAL: int = int(os.getenv("BACKGROUND_CHECK_INTERVAL", "60"))
CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "14400"))
COMPLETION_CHECK_INTERVAL: int = int(os.getenv("COMPLETION_CHECK_INTERVAL", "60"))

HAIRCUT_TYPES: Dict[str, int] = {
    "Мужская стрижка": 800,
    "Женская стрижка": 1200,
    "Детская стрижка": 600,
    "Стрижка + борода": 1000,
    "Окрашивание": 2000,
    "Укладка": 500,
}

HAIRCUT_DURATIONS: Dict[str, int] = {
    "Мужская стрижка": 60,
    "Женская стрижка": 90,
    "Детская стрижка": 45,
    "Стрижка + борода": 75,
    "Окрашивание": 120,
    "Укладка": 45,
}

CANCEL_LIMIT_HOURS: int = int(os.getenv("CANCEL_LIMIT_HOURS", "2"))
DB_PATH: str = str(Path(__file__).parent / "barbershop.db")
REPORTS_DIR: str = str(Path(__file__).parent / "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)
TIMEZONE: str = os.getenv("BOT_TIMEZONE", "Europe/Moscow")
