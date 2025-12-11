# keyboards.py – Клавиатуры для Barbershop Bot (оптимизированные)
from __future__ import annotations

from typing import List, Tuple

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from config import HAIRCUT_TYPES


# ============================================================================
# Reply Keyboards (основное меню)
# ============================================================================

def main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню для обычных пользователей."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📅 Записаться")
    builder.button(text="📋 Мои записи")
    builder.button(text="💬 Связаться с админом")
    builder.adjust(2, 1)  # 2 кнопки в первом ряду, 1 во втором
    return builder.as_markup(resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню для администраторов."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить мастера/слоты")
    builder.button(text="📊 Показать слоты мастеров")
    builder.button(text="📋 Просмотр записей")
    builder.button(text="💬 Обработать ТП")
    builder.button(text="📈 Создать отчет")
    builder.button(text="📊 Статистика БД")
    builder.button(text="👤 В пользовательское меню")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


# ============================================================================
# Inline Keyboards (выбор услуг, дат, времени)
# ============================================================================

def haircut_inline_kb() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа стрижки."""
    builder = InlineKeyboardBuilder()

    for haircut, price in HAIRCUT_TYPES.items():
        builder.button(
            text=f"{haircut} — {price}₽",
            callback_data=f"haircut|{haircut}"
        )

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)  # По 1 кнопке в ряд
    return builder.as_markup()


def dates_inline_kb(dates: List[str]) -> InlineKeyboardMarkup:
    """Клавиатура выбора даты."""
    builder = InlineKeyboardBuilder()

    for date in dates:
        # Форматируем дату для красоты (например: 2025-12-15 → 15 дек)
        try:
            from datetime import datetime
            dt = datetime.strptime(date, "%Y-%m-%d")
            display_date = dt.strftime("%d %b")
        except:
            display_date = date

        builder.button(
            text=f"📅 {display_date}",
            callback_data=f"date|{date}"
        )

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)  # По 2 даты в ряд
    return builder.as_markup()


def times_inline_kb(times: List[str]) -> InlineKeyboardMarkup:
    """Клавиатура выбора времени."""
    builder = InlineKeyboardBuilder()

    for time in times:
        builder.button(
            text=f"🕐 {time}",
            callback_data=f"time|{time}"
        )

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(3)  # По 3 времени в ряд
    return builder.as_markup()


def masters_inline_kb(masters: List[str]) -> InlineKeyboardMarkup:
    """Клавиатура выбора мастера."""
    builder = InlineKeyboardBuilder()

    # Добавляем опцию "Любой свободный"
    builder.button(
        text="👤 Любой свободный мастер",
        callback_data="master|ANY"
    )

    for master in masters:
        builder.button(
            text=f"👨‍🦰 {master}",
            callback_data=f"master|{master}"
        )

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def confirm_inline_kb() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения записи."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm|yes")
    builder.button(text="❌ Отменить", callback_data="confirm|no")
    builder.adjust(2)
    return builder.as_markup()


# ============================================================================
# Booking Management Keyboards
# ============================================================================

def booking_row_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для управления записью."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Отменить запись",
        callback_data=f"cancel_booking|{booking_id}"
    )
    return builder.as_markup()


def completion_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения выполнения записи (для мастеров)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Была — ввести сумму",
        callback_data=f"complete_enter|{booking_id}"
    )
    builder.button(
        text="❌ Не состоялась",
        callback_data=f"complete_no|{booking_id}"
    )
    builder.adjust(1)
    return builder.as_markup()


# ============================================================================
# Support Keyboards
# ============================================================================

def support_action_kb(support_id: int) -> InlineKeyboardMarkup:
    """Клавиатура действий с обращением в поддержку."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Пометить обработанным",
        callback_data=f"support_mark|{support_id}"
    )
    builder.button(
        text="💬 Ответить пользователю",
        callback_data=f"support_reply|{support_id}"
    )
    builder.button(
        text="🗑 Отменить запись пользователя",
        callback_data=f"support_cancel|{support_id}"
    )
    builder.adjust(1)
    return builder.as_markup()


def admin_user_bookings_kb(bookings: List[Tuple]) -> InlineKeyboardMarkup:
    """Клавиатура для отмены записей пользователя админом."""
    builder = InlineKeyboardBuilder()

    for booking in bookings:
        bid, haircut, price, date, time, master = booking
        builder.button(
            text=f"🗑 #{bid}: {date} {time} ({haircut})",
            callback_data=f"admin_cancel_booking|{bid}"
        )

    builder.adjust(1)
    return builder.as_markup()


# ============================================================================
# Utility Functions
# ============================================================================

def paginated_keyboard(
        items: List[str],
        prefix: str,
        page: int = 0,
        items_per_page: int = 8
) -> InlineKeyboardMarkup:
    """
    Создаёт пагинированную клавиатуру.

    Args:
        items: Список элементов для отображения
        prefix: Префикс для callback_data
        page: Текущая страница
        items_per_page: Количество элементов на странице
    """
    builder = InlineKeyboardBuilder()

    start = page * items_per_page
    end = start + items_per_page
    page_items = items[start:end]

    for item in page_items:
        builder.button(
            text=item,
            callback_data=f"{prefix}|{item}"
        )

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"{prefix}_page|{page - 1}"
        ))

    if end < len(items):
        nav_buttons.append(InlineKeyboardButton(
            text="Вперёд ▶️",
            callback_data=f"{prefix}_page|{page + 1}"
        ))

    builder.adjust(1)

    if nav_buttons:
        for btn in nav_buttons:
            builder.row(btn)

    builder.button(text="❌ Отмена", callback_data="cancel")

    return builder.as_markup()


# ============================================================================
# Export 
# ============================================================================
__all__ = [
    "main_menu_kb",
    "admin_menu_kb",
    "haircut_inline_kb",
    "dates_inline_kb",
    "times_inline_kb",
    "masters_inline_kb",
    "confirm_inline_kb",
    "booking_row_kb",
    "completion_kb",
    "support_action_kb",
    "admin_user_bookings_kb",
    "paginated_keyboard",
]
