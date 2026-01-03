"""
config.py – Production-ready конфигурация расширенного Barbershop Bot v2.0
Поддержка: промокоды, роли (админ/менеджер/мастер), мульти-филиалы, сегментация клиентов, отчёты.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Dict, List


# =============================================================================
# 1) Загрузка .env / bot.env (python-dotenv опционально)
# =============================================================================
BASE_DIR: Path = Path(__file__).parent

ENV_FILE_NAME = os.getenv("ENV_FILE", "bot.env")  # можешь поставить ".env"
ENV_FILE_PATH = (BASE_DIR / ENV_FILE_NAME).resolve()

try:
    from dotenv import load_dotenv  # pip install python-dotenv
    load_dotenv(ENV_FILE_PATH)
except Exception:
    # Если python-dotenv не установлен — переменные должны быть выставлены системой/IDE
    pass


# =============================================================================
# 2) Утилиты парсинга
# =============================================================================
def _to_bool(v: str, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return int(v)


def _int_list_env(name: str, default: List[int] | None = None) -> List[int]:
    raw = os.getenv(name, "")
    raw = raw.strip()
    if not raw:
        return list(default or [])
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


# =============================================================================
# 3) Базовая конфигурация бота
# =============================================================================
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise RuntimeError("❌ BOT_TOKEN обязателен! Установите через переменную окружения или bot.env")

ADMIN_IDS: List[int] = _int_list_env("ADMIN_IDS", default=[])
if not ADMIN_IDS:
    raise RuntimeError("❌ ADMIN_IDS обязателен! Укажите хотя бы один ID администратора")


# =============================================================================
# 4) Тайминги/ограничения
# =============================================================================
REMINDER_HOURS: List[int] = [24, 1]  # можно сделать из env, но пока достаточно так
BACKGROUND_CHECK_INTERVAL: int = _int_env("BACKGROUND_CHECK_INTERVAL", 60)
CLEANUP_INTERVAL_SECONDS: int = _int_env("CLEANUP_INTERVAL_SECONDS", 14400)
COMPLETION_CHECK_INTERVAL: int = _int_env("COMPLETION_CHECK_INTERVAL", 60)

CANCEL_LIMIT_HOURS: int = _int_env("CANCEL_LIMIT_HOURS", 2)
OLD_BOOKINGS_RETENTION_DAYS: int = _int_env("OLD_BOOKINGS_RETENTION_DAYS", 90)
BOOKING_GRACE_HOURS: int = _int_env("BOOKING_GRACE_HOURS", 2)

ENABLE_AUTO_CLEANUP: bool = _to_bool(os.getenv("ENABLE_AUTO_CLEANUP", "true"), default=True)


# =============================================================================
# 5) Филиалы (мульти-салон)
# =============================================================================
ENABLE_MULTI_BRANCH: bool = _to_bool(os.getenv("ENABLE_MULTI_BRANCH", "true"), default=True)

# Базовый словарь можно держать в коде, а позже перейти на BRANCHES_JSON или отдельные env-ключи
BRANCHES: Dict[str, Dict[str, str]] = {
    "main": {"name": "Главный салон", "address": "ул. Ленина, 10", "phone": "+7(999)123-45-67"},
    "branch2": {"name": "Филиал №2", "address": "ул. Пушкина, 25", "phone": "+7(999)765-43-21"},
}


# =============================================================================
# 6) Роли
# =============================================================================
class UserRole(Enum):
    CLIENT = "client"
    MANAGER = "manager"
    MASTER = "master"
    ADMIN = "admin"


ENABLE_ROLES: bool = _to_bool(os.getenv("ENABLE_ROLES", "true"), default=True)

MANAGER_IDS: List[int] = _int_list_env("MANAGER_IDS", default=[])
MASTER_IDS: List[int] = _int_list_env("MASTER_IDS", default=[])


# =============================================================================
# 7) Услуги/цены/длительности
# =============================================================================
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


# =============================================================================
# 8) Промокоды/скидки
# =============================================================================
ENABLE_PROMOCODES: bool = _to_bool(os.getenv("ENABLE_PROMOCODES", "true"), default=True)
MAX_PROMOCODE_USES: int = _int_env("MAX_PROMOCODE_USES", 100)

PROMOCODE_DISCOUNTS: Dict[str, int] = {
    "FIRST": 10,
    "VIP": 15,
    "FAMILY": 20,
}


# =============================================================================
# 9) Сегменты клиентов
# =============================================================================
ENABLE_CLIENT_SEGMENTS: bool = _to_bool(os.getenv("ENABLE_CLIENT_SEGMENTS", "true"), default=True)

CLIENT_SEGMENTS: Dict[str, Dict] = {
    "new": {"name": "Новый", "discount": 10, "reminders": [1]},
    "regular": {"name": "Постоянный", "discount": 5, "reminders": [24, 1]},
    "vip": {"name": "VIP", "discount": 20, "reminders": [24, 1, 0.5]},
}


# =============================================================================
# 10) Пути/локализация/режимы
# =============================================================================
DB_PATH: str = str(BASE_DIR / os.getenv("DB_PATH", "barbershop_v2.db"))
REPORTS_DIR: str = str(BASE_DIR / os.getenv("REPORTS_DIR", "reports"))
LOGS_DIR: str = str(BASE_DIR / os.getenv("LOGS_DIR", "logs"))
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

TIMEZONE: str = os.getenv("BOT_TIMEZONE", "Europe/Moscow")
ENABLE_DEBUG_MODE: bool = _to_bool(os.getenv("DEBUG_MODE", "false"), default=False)


# =============================================================================
# 11) Валидация
# =============================================================================
def validate_config() -> None:
    errors: List[str] = []

    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не установлен")
    if not ADMIN_IDS:
        errors.append("ADMIN_IDS пуст")
    if BACKGROUND_CHECK_INTERVAL < 10:
        errors.append("BACKGROUND_CHECK_INTERVAL слишком мал (минимум 10 секунд)")
    if CANCEL_LIMIT_HOURS < 0:
        errors.append("CANCEL_LIMIT_HOURS не может быть отрицательным")
    if not HAIRCUT_TYPES:
        errors.append("HAIRCUT_TYPES пуст")

    if errors:
        raise ValueError("❌ Ошибки конфигурации:\n" + "\n".join(f" - {e}" for e in errors))


validate_config()
