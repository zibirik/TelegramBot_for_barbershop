# keyboards.py – Красивые и удобные клавиатуры
from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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
    builder.button(text="👤 Мой профиль")
    builder.button(text="💬 Связаться с администратором")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню для администраторов."""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить мастера/слоты")
    builder.button(text="📊 Показать слоты мастеров")
    builder.button(text="🗑 Удалить слоты")
    builder.button(text="📋 Просмотр всех записей")
    builder.button(text="💬 Обработать техподдержку")
    builder.button(text="📈 Создать отчет")
    builder.button(text="📊 Статистика БД")
    builder.button(text="👤 В пользовательское меню")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


# ============================================================================
# Inline Keyboards
# ============================================================================

def haircut_inline_kb() -> InlineKeyboardMarkup:
    """Выбор типа стрижки с красивым форматированием."""
    builder = InlineKeyboardBuilder()

    for i, (haircut, price) in enumerate(HAIRCUT_TYPES.items(), 1):
        builder.button(
            text=f"{i}️⃣ {haircut} • {price}₽",
            callback_data=f"haircut|{haircut}"
        )

    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()


def dates_inline_kb(dates: List[str]) -> InlineKeyboardMarkup:
    """Выбор даты с красивым форматированием."""
    builder = InlineKeyboardBuilder()

    for date in dates:
        try:
            from datetime import datetime
            dt = datetime.strptime(date, "%Y-%m-%d")
            display_date = dt.strftime("%d %b").lower()
            weekday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][dt.weekday()]
            text = f"📅 {display_date} ({weekday})"
        except:
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
    """Управление записью."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Отменить", callback_data=f"cancel_booking|{booking_id}")
    return builder.as_markup()


def completion_kb(booking_id: int) -> InlineKeyboardMarkup:
    """Подтверждение выполнения записи."""
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


def admin_user_bookings_kb(bookings: List[tuple]) -> InlineKeyboardMarkup:
    """Отмена записей пользователя админом."""
    builder = InlineKeyboardBuilder()

    for booking in bookings:
        bid, haircut, price, date, time, master = booking
        text = f"🗑 #{bid}: {date} {time} ({haircut})"
        builder.button(text=text, callback_data=f"admin_cancel_booking|{bid}")

    builder.adjust(1)
    return builder.as_markup()
