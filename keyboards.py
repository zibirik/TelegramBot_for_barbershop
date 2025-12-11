# keyboards.py – клавиатуры с emoji (полностью готовые)

from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import HAIRCUT_TYPES

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записаться")],
            [KeyboardButton(text="📋 Мои записи")],
            [KeyboardButton(text="💬 Связаться с админом")],
        ],
        resize_keyboard=True,
    )

def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить мастера/слоты")],
            [KeyboardButton(text="📋 Просмотр записей")],
            [KeyboardButton(text="📊 Показать слоты мастеров")],
            [KeyboardButton(text="🔗 Привязать мастера (имя id)")],
            [KeyboardButton(text="📈 Создать отчет")],
            [KeyboardButton(text="💬 Обработать ТП")],
            [KeyboardButton(text="👤 В пользовательское меню")],
            [KeyboardButton(text="◀️ Назад")],
        ],
        resize_keyboard=True,
    )

def haircut_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    emoji_map = {
        "Мужская стрижка": "👨",
        "Женская стрижка": "👩",
        "Детская стрижка": "👶",
        "Стрижка + борода": "🧔",
        "Окрашивание": "🎨",
        "Укладка": "💇",
    }
    for name, price in HAIRCUT_TYPES.items():
        emoji = emoji_map.get(name, "✂️")
        builder.button(
            text=f"{emoji} {name} — {price}₽",
            callback_data=f"haircut|{name}",
        )
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()

def dates_inline_kb(dates: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            weekday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][dt.weekday()]
            formatted = f"📅 {weekday} {dt.strftime('%d.%m')}"
        except Exception:
            formatted = f"📅 {d}"
        builder.button(text=formatted, callback_data=f"date|{d}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(3)
    return builder.as_markup()

def times_inline_kb(times: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in times:
        builder.button(text=f"🕐 {t}", callback_data=f"time|{t}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(4)
    return builder.as_markup()

def masters_inline_kb(masters: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for m in sorted(set(masters)):
        builder.button(text=f"👨🦰 {m}", callback_data=f"master|{m}")
    builder.button(text="🎲 Любой мастер", callback_data="master|ANY")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()

def confirm_inline_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm|yes")
    builder.button(text="❌ Отменить", callback_data="confirm|no")
    builder.adjust(2)
    return builder.as_markup()

def booking_row_kb(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🗑 Отменить запись",
        callback_data=f"cancel_booking|{booking_id}",
    )
    return builder.as_markup()

def support_action_kb(support_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Ответить", callback_data=f"support_reply|{support_id}")
    builder.button(
        text="✅ Пометить обработанным",
        callback_data=f"support_mark|{support_id}",
    )
    builder.button(
        text="🗑 Отменить запись юзера",
        callback_data=f"support_cancel|{support_id}",
    )
    builder.adjust(2)
    return builder.as_markup()

def admin_user_bookings_kb(bookings: List[Tuple]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        bid = b[0]
        txt = f"🎫 {b[3]} {b[4]} | {b[1]} | {b[2]}₽"
        builder.button(text=txt, callback_data=f"admin_cancel_booking|{bid}")
    builder.button(text="❌ Отмена", callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()

def completion_kb(booking_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Была — ввести сумму",
        callback_data=f"complete_enter|{booking_id}",
    )
    builder.button(
        text="❌ Не состоялась",
        callback_data=f"complete_no|{booking_id}",
    )
    builder.adjust(1)
    return builder.as_markup()

__all__ = [
    "main_menu_kb",
    "admin_menu_kb",
    "haircut_inline_kb",
    "dates_inline_kb",
    "times_inline_kb",
    "masters_inline_kb",
    "confirm_inline_kb",
    "booking_row_kb",
    "support_action_kb",
    "admin_user_bookings_kb",
    "completion_kb",
]
