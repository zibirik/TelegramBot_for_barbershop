# config.py – Production-ready конфигурация
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

# Bot Configuration
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8246992078:AAG30Zg-Qjx5QT6Xaqt9CVt_KAKWS5yc25c")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise RuntimeError("⚠️ BOT_TOKEN не указан!")

# Admin Configuration
_env_admins = os.getenv("ADMIN_IDS")
if _env_admins:
    ADMIN_IDS: List[int] = [int(x.strip()) for x in _env_admins.split(",") if x.strip()]
else:
    ADMIN_IDS: List[int] = [895245154]

if not ADMIN_IDS:
    raise RuntimeError("⚠️ Не указаны ID администраторов!")

# Timing Configuration
REMINDER_HOURS: List[int] = [24, 1]
BACKGROUND_CHECK_INTERVAL: int = int(os.getenv("BACKGROUND_CHECK_INTERVAL", "60"))
CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "14400"))
COMPLETION_CHECK_INTERVAL: int = int(os.getenv("COMPLETION_CHECK_INTERVAL", "60"))
CANCEL_LIMIT_HOURS: int = int(os.getenv("CANCEL_LIMIT_HOURS", "2"))
OLD_BOOKINGS_RETENTION_DAYS: int = int(os.getenv("OLD_BOOKINGS_RETENTION_DAYS", "90"))
BOOKING_GRACE_HOURS: int = int(os.getenv("BOOKING_GRACE_HOURS", "2"))

# Services Configuration
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

# Paths
BASE_DIR: Path = Path(__file__).parent
DB_PATH: str = str(BASE_DIR / os.getenv("DB_PATH", "barbershop.db"))
REPORTS_DIR: str = str(BASE_DIR / os.getenv("REPORTS_DIR", "reports"))
LOGS_DIR: str = str(BASE_DIR / os.getenv("LOGS_DIR", "logs"))

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Localization.
TIMEZONE: str = os.getenv("BOT_TIMEZONE", "Europe/Moscow")

# Feature Flags
ENABLE_ANALYTICS: bool = os.getenv("ENABLE_ANALYTICS", "true").lower() == "true"
ENABLE_AUTO_CLEANUP: bool = os.getenv("ENABLE_AUTO_CLEANUP", "true").lower() == "true"
ENABLE_DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"


# Validation
def validate_config() -> None:
    """Проверяет корректность конфигурации."""
    errors = []

    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не установлен")
    if not ADMIN_IDS:
        errors.append("ADMIN_IDS пуст")
    if BACKGROUND_CHECK_INTERVAL < 10:
        errors.append("BACKGROUND_CHECK_INTERVAL слишком мал (минимум 10 сек)")
    if CANCEL_LIMIT_HOURS < 0:
        errors.append("CANCEL_LIMIT_HOURS не может быть отрицательным")
    if not HAIRCUT_TYPES:
        errors.append("HAIRCUT_TYPES пуст")

    if errors:
        raise ValueError(f"❌ Ошибки конфигурации:\n" + "\n".join(f"  - {e}" for e in errors))


validate_config()
