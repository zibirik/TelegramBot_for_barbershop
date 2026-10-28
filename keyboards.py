# keyboards.py – Красивые, удобные и расширяемые клавиатуры (v2-ready)
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import HAIRCUT_TYPES


# ============================================================================
# Safe optional config imports (чтобы не падать, если в config чего-то нет)
# ============================================================================
try:
    from config import ENABLE_MULTI_BRANCH, BRANCHES
except Exception:
    ENABLE_MULTI_BRANCH = False
    BRANCHES = {}

try:
    from config import ENABLE_PROMOCODES, PROMOCODE_DISCOUNTS
except Exception:
    ENABLE_PROMOCODES = False
    PROMOCODE_DISCOUNTS = {}

try:
    from config import ENABLE_ROLES, UserRole
except Exception:
    ENABLE_ROLES = False
    UserRole = None


# ============================================================================
# Reply Keyboards (главные меню)
# ============================================================================
def main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню для обычных пользователей."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📅 Записаться")
    builder.button(text="📋 Мои записи")
    builder.button(text="👤 Мой профиль")
    builder.button(text="💬 Связаться с администратором")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню для администраторов (расширяемое)."""
    builder = ReplyKeyboardBuilder()

    # Текущие пункты (совместимость с handlers.py)
    builder.button(text="➕ Добавить мастера/слоты")
    builder.button(text="📊 Показать слоты мастеров")
    builder.button(text="🗑 Удалить слоты")
    builder.button(text="📋 Просмотр всех записей")
    builder.button(text="💬 Обработать техподдержку")
    builder.button(text="📈 Создать отчет")
    builder.button(text="📊 Статистика БД")

    # Зарезервировано под будущие фичи (можно подключить в handlers.py позже)
    builder.button(text="🎟 Промокоды")
    builder.button(text="🏢 Филиалы")
    builder.button(text="👥 Роли и доступы")
    builder.button(text="📣 Рассылка")

    builder.button(text="👤 В пользовательское меню")

    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def manager_menu_kb() -> ReplyKeyboardMarkup:
    """Меню менеджера (если включишь роль manager в handlers.py)."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить мастера/слоты")
    builder.button(text="📊 Показать слоты мастеров")
    builder.button(text="🗑 Удалить слоты")
    builder.button(text="📋 Просмотр всех записей")
    builder.button(text="📈 Создать отчет")
    builder.button(text="📊 Статистика БД")
    builder.button(text="👤 В пользовательское меню")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def master_menu_kb() -> ReplyKeyboardMarkup:
    """Меню мастера (если включишь роль master в handlers.py)."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📋 Мои записи (мастер)")
    builder.button(text="📅 Моё расписание")
    builder.button(text="👤 В пользовательское меню")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)


# ============================================================================
# Inline Keyboards (запись клиента) — совместимые коллбеки
# ============================================================================
def haircut_inline_kb() -> InlineKeyboardMarkup:
    """Выбор услуги."""
    builder = InlineKeyboardBuilder()

    for i, (haircut, price) in enumerate(HAIRCUT_TYPES.items(), 1):
        builder.button(
            text=f"{i}️⃣ {haircut} • {price}₽",
            callback_data=f"haircut|{haircut}",
        )

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def dates_inline_kb(dates: List[str]) -> InlineKeyboardMarkup:
    """Выбор даты."""
    builder = InlineKeyboardBuilder()

    for date in dates:
        try:
            from datetime import datetime

            dt = datetime.strptime(date, "%Y-%m-%d")
            display_date = dt.strftime("%d %b").lower()
            weekday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][dt.weekday()]
            text = f"📅 {display_date} ({weekday})"
        except Exception:
            text = f"📅 {date}"

        builder.button(text=text, callback_data=f"date|{date}")

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


def times_inline_kb(times: List[str]) -> InlineKeyboardMarkup:
    """Выбор времени."""
    builder = InlineKeyboardBuilder()

    for time in times:
        builder.button(text=f"🕐 {time}", callback_data=f"time|{time}")

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(3)
    return builder.as_markup()


def masters_inline_kb(masters: List[str]) -> InlineKeyboardMarkup:
    """Выбор мастера."""
    builder = InlineKeyboardBuilder()

    builder.button(text="👤 Любой свободный мастер", callback_data="master|ANY")

    for master in masters:
        builder.button(text=f"💈 {master}", callback_data=f"master|{master}")

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def confirm_inline_kb() -> InlineKeyboardMarkup:
    """Подтверждение записи."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm|yes")
    builder.button(text="❌ Изменить", callback_data="confirm|no")
    builder.adjust(2)
    return builder.as_markup()


def booking_row_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Управление записью пользователя (отмена)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Отменить", callback_data=f"cancel_booking|{booking_id}")
    return builder.as_markup()


# ============================================================================
# Inline Keyboards (завершение записи / поддержка) — совместимые коллбеки
# ============================================================================
def completion_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Подтверждение выполнения записи (для админа/мастера)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Была — ввести сумму", callback_data=f"complete_enter|{booking_id}")
    builder.button(text="❌ Не состоялась", callback_data=f"complete_no|{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def support_action_kb(support_id: int) -> InlineKeyboardMarkup:
    """Действия с обращением в поддержку."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Помечено обработанным", callback_data=f"support_mark|{support_id}")
    builder.button(text="💬 Ответить пользователю", callback_data=f"support_reply|{support_id}")
    builder.adjust(1)
    return builder.as_markup()


def support_reply_kb(support_id: int) -> InlineKeyboardMarkup:
    """
    Совместимость (если захочешь делать промежуточное подтверждение отправки ответа).
    Сейчас в handlers.py не используется, но оставлено.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить", callback_data=f"support_send|{support_id}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def admin_user_bookings_kb(bookings: List[tuple]) -> InlineKeyboardMarkup:
    """Отмена записей пользователя админом (если используешь этот сценарий)."""
    builder = InlineKeyboardBuilder()
    for booking in bookings:
        bid, haircut, price, date, time, master = booking
        text = f"🗑 #{bid}: {date} {time} ({haircut})"
        builder.button(text=text, callback_data=f"admin_cancel_booking|{bid}")
    builder.adjust(1)
    return builder.as_markup()


# ============================================================================
# Новые клавиатуры под задачи v2 (филиалы / промокоды / роли)
# Они не ломают текущий код: просто подключишь в handlers позже.
# ============================================================================
def branches_inline_kb(
    branches: Optional[Dict[str, Dict[str, str]]] = None,
    *,
    include_any: bool = False,
    cancel_cb: str = "cancel",
) -> InlineKeyboardMarkup:
    """
    Выбор филиала.
    callback: branch|<code>
    """
    builder = InlineKeyboardBuilder()

    branches = branches if branches is not None else (BRANCHES or {})
    if include_any:
        builder.button(text="🏢 Любой филиал", callback_data="branch|ANY")

    # Сортируем по name, если есть
    items: List[Tuple[str, Dict[str, str]]] = list(branches.items())
    items.sort(key=lambda x: (x[1].get("name") or x[0]).lower())

    for code, data in items:
        name = data.get("name") or code
        addr = data.get("address")
        text = f"🏢 {name}" if not addr else f"🏢 {name}"
        builder.button(text=text, callback_data=f"branch|{code}")

    builder.button(text="❌ Отмена", callback_data=cancel_cb)
    builder.adjust(1)
    return builder.as_markup()


def promocode_choice_kb(
    *,
    allow_skip: bool = True,
    cancel_cb: str = "cancel",
) -> InlineKeyboardMarkup:
    """
    Стартовое меню промокода (когда спрашиваешь "есть промокод?").
    callback:
      promo|enter
      promo|skip
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="🎟 Ввести промокод", callback_data="promo|enter")
    if allow_skip:
        builder.button(text="➡️ Без промокода", callback_data="promo|skip")
    builder.button(text="❌ Отмена", callback_data=cancel_cb)
    builder.adjust(1)
    return builder.as_markup()


def promocodes_inline_kb(
    promocodes: Optional[Dict[str, int]] = None,
    *,
    cancel_cb: str = "cancel",
) -> InlineKeyboardMarkup:
    """
    Быстрый выбор промокода из списка (если хочешь показывать популярные).
    callback: promo_apply|CODE
    """
    builder = InlineKeyboardBuilder()
    promocodes = promocodes if promocodes is not None else (PROMOCODE_DISCOUNTS or {})

    for code, disc in sorted(promocodes.items(), key=lambda x: x[0]):
        builder.button(text=f"🎟 {code} (-{disc}%)", callback_data=f"promo_apply|{code}")

    builder.button(text="❌ Отмена", callback_data=cancel_cb)
    builder.adjust(1)
    return builder.as_markup()


def role_select_inline_kb(
    *,
    cancel_cb: str = "cancel",
) -> InlineKeyboardMarkup:
    """
    Выбор роли (для админа при назначении).
    callback: role|client / role|manager / role|master / role|admin
    """
    builder = InlineKeyboardBuilder()

    # Даже если UserRole нет, коллбеки всё равно можно обрабатывать строками
    builder.button(text="👤 Клиент", callback_data="role|client")
    builder.button(text="🧰 Менеджер", callback_data="role|manager")
    builder.button(text="💈 Мастер", callback_data="role|master")
    builder.button(text="👑 Админ", callback_data="role|admin")

    builder.button(text="❌ Отмена", callback_data=cancel_cb)
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def yes_no_inline_kb(
    yes_cb: str,
    no_cb: str,
    *,
    yes_text: str = "✅ Да",
    no_text: str = "❌ Нет",
) -> InlineKeyboardMarkup:
    """Универсальная да/нет."""
    builder = InlineKeyboardBuilder()
    builder.button(text=yes_text, callback_data=yes_cb)
    builder.button(text=no_text, callback_data=no_cb)
    builder.adjust(2)
    return builder.as_markup()
