# handlers.py – Полный обработчик всех команд (fixed + production tweaks)
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone as dt_timezone

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS, HAIRCUT_DURATIONS, HAIRCUT_TYPES, CANCEL_LIMIT_HOURS
from db import (
    add_booking,
    add_support_message,
    add_user,
    cancel_booking,
    get_available_dates,
    get_available_masters,
    get_available_times,
    get_all_master_slots,
    get_booking_by_id,
    get_completed_bookings,
    get_database_stats,
    get_pending_supports,
    get_support_by_id,
    get_user,
    get_user_bookings,
    mark_booking_completed,
    mark_support_handled,
    set_master_telegram,
    update_master_schedule,
    remove_master_slots,              # удаляет 1 слот по id
    remove_master_slots_by_name,      # удаляет все слоты мастера по имени
    get_all_bookings_for_admin,
)

from keyboards import (
    admin_menu_kb,
    confirm_inline_kb,
    booking_row_kb,
    completion_kb,
    dates_inline_kb,
    haircut_inline_kb,
    main_menu_kb,
    masters_inline_kb,
    support_action_kb,
    times_inline_kb,
)

log = logging.getLogger(__name__)
router = Router()


# ============================================================================
# Helpers
# ============================================================================
def is_admin(user_id: int) -> bool:
    return user_id in set(ADMIN_IDS)


def user_home_kb(user_id: int):
    return admin_menu_kb() if is_admin(user_id) else main_menu_kb()


def _parse_int(s: str) -> int | None:
    try:
        return int(s.strip())
    except Exception:
        return None


def _parse_slot_ids(text: str) -> list[int]:
    """
    Поддерживает:
      - "5"
      - "5-10"
      - "5,6,7"
      - "5 6 7"
    """
    text = (text or "").strip()
    if not text:
        return []

    # range
    if "-" in text and "," not in text:
        parts = [p.strip() for p in text.split("-", 1)]
        if len(parts) != 2:
            return []
        a = _parse_int(parts[0])
        b = _parse_int(parts[1])
        if a is None or b is None:
            return []
        if b < a:
            a, b = b, a
        return list(range(a, b + 1))

    # multi
    sep_text = text.replace(",", " ")
    out: list[int] = []
    for p in sep_text.split():
        v = _parse_int(p)
        if v is not None:
            out.append(v)
    return out


# ============================================================================
# FSM States
# ============================================================================
class UserState(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()


class BookingState(StatesGroup):
    haircut_type = State()
    date = State()
    time = State()
    master = State()
    confirm = State()


class AddMasterState(StatesGroup):
    waiting_for_name = State()
    waiting_for_dates = State()
    waiting_for_times = State()
    waiting_for_telegram = State()


class DeleteSlotsState(StatesGroup):
    waiting_for_input = State()


class SupportState(StatesGroup):
    waiting_for_text = State()
    admin_reply = State()


class AdminReportState(StatesGroup):
    waiting_for_dates = State()


class CompletionState(StatesGroup):
    waiting_for_amount = State()


# ============================================================================
# /start + registration
# ============================================================================
@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()

    user_id = message.from_user.id
    existing_user = get_user(user_id)

    if existing_user:
        welcome_text = (
            f"👋 С возвращением, <b>{existing_user[0]}</b>!\n\n"
            f"✂️ Выберите действие:"
        )
        await message.answer(welcome_text, reply_markup=user_home_kb(user_id))
        return

    await state.set_state(UserState.waiting_for_name)
    await message.answer(
        "👋 <b>Добро пожаловать в барбершоп!</b>\n\n"
        "Введите ваше полное имя:"
    )


@router.message(UserState.waiting_for_name)
async def register_name(message: Message, state: FSMContext) -> None:
    full_name = (message.text or "").strip()

    if len(full_name) < 2:
        await message.answer("⚠️ Имя слишком короткое. Введите полное имя:")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(UserState.waiting_for_phone)
    await message.answer("📱 Введите ваш номер телефона:")


@router.message(UserState.waiting_for_phone)
async def register_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()

    if len(phone) < 10:
        await message.answer("⚠️ Номер телефона слишком короткий. Попробуйте снова:")
        return

    data = await state.get_data()
    full_name = data["full_name"]
    user_id = message.from_user.id

    try:
        add_user(user_id, full_name, phone)
        await state.clear()

        await message.answer(
            f"✅ <b>Вы успешно зарегистрированы!</b>\n\n"
            f"👤 Имя: {full_name}\n"
            f"📱 Телефон: {phone}\n\n"
            f"Выберите действие:",
            reply_markup=main_menu_kb(),
        )
    except Exception as e:
        log.exception("Ошибка регистрации")
        await message.answer(f"❌ Ошибка: {str(e)}")
        await state.clear()


# ============================================================================
# Profile
# ============================================================================
@router.message(F.text == "👤 Мой профиль")
async def user_profile(message: Message, state: FSMContext) -> None:
    await state.clear()

    user_id = message.from_user.id
    user = get_user(user_id)

    if not user:
        await message.answer("❌ Профиль не найден, напишите: '/start'", reply_markup=main_menu_kb())
        return

    full_name, phone = user

    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"📝 Имя: <b>{full_name}</b>\n"
        f"📱 Телефон: <b>{phone}</b>\n\n"
        f"Хотите изменить контактные данные?"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить имя", callback_data="edit_name")],
        [InlineKeyboardButton(text="📱 Изменить телефон", callback_data="edit_phone")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel")],
    ])

    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "edit_name")
async def edit_name(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserState.waiting_for_name)
    await callback.answer()
    await callback.message.answer("📝 Введите новое имя:")


@router.callback_query(F.data == "edit_phone")
async def edit_phone(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserState.waiting_for_phone)
    await callback.answer()
    await callback.message.answer("📱 Введите новый номер телефона:")


# ============================================================================
# Booking flow
# ============================================================================
@router.message(F.text == "📅 Записаться")
async def start_booking(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BookingState.haircut_type)
    await message.answer("✂️ <b>Выберите услугу:</b>", reply_markup=haircut_inline_kb())


@router.callback_query(F.data.startswith("haircut|"), BookingState.haircut_type)
async def select_haircut(callback: CallbackQuery, state: FSMContext) -> None:
    haircut = callback.data.split("|", 1)[1]
    if haircut not in HAIRCUT_TYPES:
        await callback.answer("❌ Неизвестная услуга", show_alert=True)
        await state.clear()
        return

    await state.update_data(haircut=haircut, price=HAIRCUT_TYPES[haircut])
    await state.set_state(BookingState.date)

    dates = get_available_dates()
    if not dates:
        await callback.answer("❌ Нет доступных дат", show_alert=True)
        await callback.message.answer("К сожалению, сейчас нет свободных дат.")
        await state.clear()
        return

    await callback.answer(f"✅ Выбрана: {haircut}")
    await callback.message.edit_text(
        f"📅 <b>Выбрана услуга: {haircut} ({HAIRCUT_TYPES[haircut]}₽)</b>\n\n"
        f"Выберите дату:",
        reply_markup=dates_inline_kb(dates),
    )


@router.callback_query(F.data.startswith("date|"), BookingState.date)
async def select_date(callback: CallbackQuery, state: FSMContext) -> None:
    date = callback.data.split("|", 1)[1]
    await state.update_data(date=date)
    await state.set_state(BookingState.time)

    times = get_available_times(date)
    if not times:
        await callback.answer("❌ Нет свободного времени на эту дату", show_alert=True)
        return

    await callback.answer(f"✅ Дата: {date}")
    await callback.message.edit_text(
        f"📅 Дата: {date}\n\n"
        f"🕐 <b>Выберите время:</b>",
        reply_markup=times_inline_kb(times),
    )


@router.callback_query(F.data.startswith("time|"), BookingState.time)
async def select_time(callback: CallbackQuery, state: FSMContext) -> None:
    time = callback.data.split("|", 1)[1]
    await state.update_data(time=time)
    await state.set_state(BookingState.master)

    data = await state.get_data()
    masters = get_available_masters(data["date"], time)

    if not masters:
        await callback.answer("❌ Нет свободных мастеров на это время", show_alert=True)
        return

    await callback.answer(f"✅ Время: {time}")
    await callback.message.edit_text(
        f"📅 {data['date']} 🕐 {time}\n\n"
        f"👨‍🦰 <b>Выберите мастера:</b>",
        reply_markup=masters_inline_kb(masters),
    )


@router.callback_query(F.data.startswith("master|"), BookingState.master)
async def select_master(callback: CallbackQuery, state: FSMContext) -> None:
    master = callback.data.split("|", 1)[1]

    data = await state.get_data()
    user = get_user(callback.from_user.id)
    if not user:
        await callback.answer("❌ Профиль не найден, напишите: '/start'", show_alert=True)
        return

    # поддержка "ANY" (если клавиатура её отдаёт)
    if master == "ANY":
        masters = get_available_masters(data["date"], data["time"])
        if not masters:
            await callback.answer("❌ Нет свободных мастеров", show_alert=True)
            await state.clear()
            return
        master = masters[0]

    full_name, phone = user

    await state.update_data(master=master)
    await state.set_state(BookingState.confirm)

    confirmation_text = (
        f"✅ <b>Подтверждение записи:</b>\n\n"
        f"✂️ Услуга: <b>{data['haircut']}</b> — {data['price']}₽\n"
        f"📅 Дата: <b>{data['date']}</b>\n"
        f"🕐 Время: <b>{data['time']}</b>\n"
        f"👨‍🦰 Мастер: <b>{master}</b>\n"
        f"👤 Имя: <b>{full_name}</b>\n"
        f"📱 Телефон: <b>{phone}</b>\n\n"
        f"Всё верно?"
    )

    await callback.answer()
    await callback.message.edit_text(confirmation_text, reply_markup=confirm_inline_kb())


@router.callback_query(F.data.startswith("confirm|"), BookingState.confirm)
async def confirm_booking(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split("|", 1)[1]

    if action == "no":
        await callback.answer("❌ Отменено")
        try:
            await callback.message.delete()
        except Exception:
            pass
        await state.clear()
        await callback.message.answer("Ок, начните заново:", reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    user = get_user(user_id)

    if not user:
        await callback.answer("❌ Профиль не найден, напишите: '/start'", show_alert=True)
        await state.clear()
        return

    full_name, phone = user

    try:
        booking_id = add_booking(
            user_id=user_id,
            username=username,
            full_name=full_name,
            phone=phone,
            haircut=data["haircut"],
            price=data["price"],
            date=data["date"],
            time=data["time"],
            master=data["master"],
            duration_minutes=HAIRCUT_DURATIONS.get(data["haircut"], 60),
        )

        await callback.answer("✅ Запись создана!")
        await callback.message.edit_text(
            f"✅ <b>Запись успешно создана!</b>\n\n"
            f"🎟 Номер записи: <b>#{booking_id}</b>\n"
            f"✂️ Услуга: {data['haircut']}\n"
            f"📅 Дата: {data['date']}\n"
            f"🕐 Время: {data['time']}\n"
            f"👨‍🦰 Мастер: {data['master']}\n\n"
            f"Спасибо за вашу запись!"
        )

        await state.clear()
        await callback.message.answer("Выберите действие:", reply_markup=main_menu_kb())

    except ValueError as e:
        await callback.answer(f"❌ {str(e)}", show_alert=True)
        await state.clear()
    except Exception as e:
        log.exception("Ошибка при создании записи")
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
        await state.clear()


# ============================================================================
# My bookings
# ============================================================================
@router.message(F.text == "📋 Мои записи")
async def my_bookings(message: Message, state: FSMContext) -> None:
    await state.clear()

    user_id = message.from_user.id
    bookings = get_user_bookings(user_id)

    if not bookings:
        await message.answer("📭 У вас пока нет записей.", reply_markup=main_menu_kb())
        return

    text = "📋 <b>Ваши записи:</b>\n\n"
    for bid, haircut, price, date, time, master in bookings:
        text += (
            f"🎟 Запись #{bid}\n"
            f"✂️ {haircut} • {price}₽\n"
            f"📅 {date} 🕐 {time}\n"
            f"👨‍🦰 Мастер: {master}\n\n"
        )

    await message.answer(text)

    for bid, haircut, price, date, time, master in bookings:
        await message.answer(
            f"🎟 #{bid} | {date} {time}\n✂️ {haircut} ({master})",
            reply_markup=booking_row_kb(bid),
        )


@router.callback_query(F.data.startswith("cancel_booking|"))
async def cancel_user_booking(callback: CallbackQuery) -> None:
    booking_id = int(callback.data.split("|", 1)[1])
    booking = get_booking_by_id(booking_id)

    if not booking:
        await callback.answer("❌ Запись не найдена", show_alert=True)
        return

    # booking[6]=date, booking[7]=time (сделано совместимо с db.py)
    try:
        from zoneinfo import ZoneInfo
        from config import TIMEZONE

        tz = ZoneInfo(TIMEZONE)
        booking_dt = datetime.strptime(f"{booking[6]} {booking[7]}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        now = datetime.now(tz)
        hours_until = (booking_dt - now).total_seconds() / 3600

        if hours_until < CANCEL_LIMIT_HOURS:
            await callback.answer(
                f"❌ Отменить можно не позже, чем за {CANCEL_LIMIT_HOURS} ч до записи",
                show_alert=True,
            )
            return
    except Exception:
        # если TZ не сработал — не блокируем отмену (мягко)
        pass

    if cancel_booking(booking_id):
        await callback.answer("✅ Запись отменена")
        await callback.message.edit_text(
            f"✅ Запись #{booking_id} успешно отменена.\n\n"
            f"Слот освобождён для других клиентов."
        )
    else:
        await callback.answer("❌ Не удалось отменить запись", show_alert=True)


# ============================================================================
# Support (user)
# ============================================================================
@router.message(F.text == "💬 Связаться с администратором")
async def start_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SupportState.waiting_for_text)
    await message.answer("💬 <b>Техподдержка</b>\n\nОпишите вашу проблему или вопрос:")


@router.message(SupportState.waiting_for_text)
async def support_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()

    if len(text) < 5:
        await message.answer("⚠️ Сообщение слишком короткое. Опишите подробнее:")
        return

    user_id = message.from_user.id
    username = message.from_user.username or "—"
    user = get_user(user_id)

    if not user:
        await state.clear()
        await message.answer("❌ Ошибка профиля", reply_markup=main_menu_kb())
        return

    full_name, phone = user

    try:
        support_id = add_support_message(
            user_id=user_id,
            username=username,
            full_name=full_name,
            phone=phone,
            text=text,
        )

        await state.clear()
        await message.answer(
            f"✅ Ваше обращение <b>#{support_id}</b> отправлено администратору.\n\n"
            f"Мы ответим в ближайшее время.",
            reply_markup=main_menu_kb(),
        )

        # уведомляем админов через текущий bot (не создаём новый Bot())
        for admin_id in ADMIN_IDS:
            try:
                admin_msg = (
                    f"💬 <b>Новое обращение #{support_id}</b>\n\n"
                    f"👤 От: <b>{full_name}</b> (@{username})\n"
                    f"📱 Телефон: {phone}\n"
                    f"⏰ Время: {datetime.now(dt_timezone.utc).strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"📝 Текст:\n{text}"
                )
                await message.bot.send_message(admin_id, admin_msg, reply_markup=support_action_kb(support_id))
            except Exception:
                pass

    except Exception as e:
        log.exception("Ошибка при создании обращения")
        await state.clear()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=main_menu_kb())


# ============================================================================
# Admin: Add master / slots
# ============================================================================
@router.message(F.text == "➕ Добавить мастера/слоты", lambda m: is_admin(m.from_user.id))
async def admin_add_master_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddMasterState.waiting_for_name)
    await message.answer("👨‍🦰 <b>Добавление мастера</b>\n\nВведите имя мастера:")


@router.message(AddMasterState.waiting_for_name, lambda m: is_admin(m.from_user.id))
async def admin_master_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("⚠️ Имя слишком короткое. Введите корректное имя:")
        return

    await state.update_data(master_name=name)
    await state.set_state(AddMasterState.waiting_for_dates)
    await message.answer(
        f"✅ Мастер: <b>{name}</b>\n\n"
        f"📅 Введите период дат:\n"
        f"<code>ГГГГ-ММ-ДД ГГГГ-ММ-ДД</code>\n"
        f"Пример: <code>2025-12-11 2025-12-31</code>"
    )


@router.message(AddMasterState.waiting_for_dates, lambda m: is_admin(m.from_user.id))
async def admin_master_dates(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").strip().split()
    if len(parts) != 2:
        await message.answer("⚠️ Неверный формат. Пример: <code>2025-12-11 2025-12-31</code>")
        return

    try:
        start_date = datetime.strptime(parts[0], "%Y-%m-%d")
        end_date = datetime.strptime(parts[1], "%Y-%m-%d")
        if end_date < start_date:
            await message.answer("⚠️ Конечная дата раньше начальной.")
            return

        await state.update_data(start_date=parts[0], end_date=parts[1])
        await state.set_state(AddMasterState.waiting_for_times)

        await message.answer(
            f"📅 Период: {parts[0]} — {parts[1]}\n\n"
            f"🕐 Введите время работы и шаг:\n"
            f"<code>ЧЧ:ММ ЧЧ:ММ шаг_минут</code>\n"
            f"Пример: <code>09:00 18:00 60</code>"
        )
    except Exception:
        await message.answer("⚠️ Ошибка формата даты. Пример: <code>2025-12-11 2025-12-31</code>")


@router.message(AddMasterState.waiting_for_times, lambda m: is_admin(m.from_user.id))
async def admin_master_times(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").strip().split()
    if len(parts) != 3:
        await message.answer("⚠️ Неверный формат. Пример: <code>09:00 18:00 60</code>")
        return

    try:
        start_time_str, end_time_str, step_str = parts
        datetime.strptime(start_time_str, "%H:%M")
        datetime.strptime(end_time_str, "%H:%M")
        step = int(step_str)
        if step <= 0:
            raise ValueError("Шаг должен быть положительным")

        data = await state.get_data()
        update_master_schedule(
            name=data["master_name"],
            start_date=data["start_date"],
            end_date=data["end_date"],
            start_time=start_time_str,
            end_time=end_time_str,
            step_minutes=step,
            telegram_id=None,
        )

        await state.set_state(AddMasterState.waiting_for_telegram)
        await message.answer("✅ Слоты созданы!\n\nВведите telegram ID мастера (или напишите: <code>пусто</code>)")
    except Exception as e:
        log.exception("Ошибка при создании слотов")
        await state.clear()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=admin_menu_kb())


@router.message(AddMasterState.waiting_for_telegram, lambda m: is_admin(m.from_user.id))
async def admin_master_telegram(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()

    if text and text.lower() != "пусто":
        try:
            tg_id = int(text)
            set_master_telegram(data["master_name"], tg_id)
        except ValueError:
            await message.answer("⚠️ Неверный telegram ID. Попробуйте снова или напишите: <code>пусто</code>")
            return

    await state.clear()
    await message.answer(
        f"✅ <b>Мастер успешно добавлен!</b>\n\n"
        f"👨‍🦰 Мастер: {data['master_name']}\n"
        f"📅 Период: {data['start_date']} — {data['end_date']}",
        reply_markup=admin_menu_kb(),
    )


# ============================================================================
# Admin: Show slots
# ============================================================================
@router.message(F.text == "📊 Показать слоты мастеров", lambda m: is_admin(m.from_user.id))
async def admin_show_slots(message: Message) -> None:
    slots = get_all_master_slots()
    if not slots:
        await message.answer("📭 Нет добавленных слотов.", reply_markup=admin_menu_kb())
        return

    lines = ["📊 <b>Слоты мастеров:</b>\n"]
    for slot in slots[:200]:
        tg = str(slot.get("telegram_id") or "—")
        lines.append(
            f"🆔 {slot['id']}: <b>{slot['name']}</b> | 📅 {slot['available_date']} 🕐 {slot['available_time']} | tg: {tg}"
        )
    if len(slots) > 200:
        lines.append(f"\n…и ещё {len(slots) - 200} слотов.")

    await message.answer("\n".join(lines), reply_markup=admin_menu_kb())


# ============================================================================
# Admin: Delete slots
# ============================================================================
@router.message(F.text == "🗑 Удалить слоты", lambda m: is_admin(m.from_user.id))
async def admin_delete_slots_start(message: Message, state: FSMContext) -> None:
    await state.set_state(DeleteSlotsState.waiting_for_input)
    await message.answer(
        "🗑 <b>Удаление слотов</b>\n\n"
        "Введите:\n"
        "• ID слота (например: <code>5</code>)\n"
        "• Диапазон (например: <code>5-10</code>)\n"
        "• Несколько ID (например: <code>5,6,7</code>)\n"
        "• Или <b>имя мастера</b> для удаления всех его слотов"
    )


@router.message(DeleteSlotsState.waiting_for_input, lambda m: is_admin(m.from_user.id))
async def admin_delete_slots(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    await state.clear()

    removed = 0
    try:
        ids = _parse_slot_ids(text)
        if ids:
            for slot_id in ids:
                removed += int(remove_master_slots(int(slot_id)))
        else:
            # treat as master name
            removed = int(remove_master_slots_by_name(text))

        if removed > 0:
            await message.answer(f"✅ Удалено <b>{removed}</b> слотов", reply_markup=admin_menu_kb())
        else:
            await message.answer("❌ Не найдено слотов для удаления", reply_markup=admin_menu_kb())
    except Exception as e:
        log.exception("Ошибка при удалении слотов")
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=admin_menu_kb())


# ============================================================================
# Admin: View bookings + cancel
# ============================================================================
@router.message(F.text == "📋 Просмотр всех записей", lambda m: is_admin(m.from_user.id))
async def admin_all_bookings(message: Message) -> None:
    bookings = get_all_bookings_for_admin()
    if not bookings:
        await message.answer("📭 Нет записей.", reply_markup=admin_menu_kb())
        return

    text_lines = ["📋 <b>Все активные записи:</b>\n"]
    shown = 0
    for b in bookings:
        bid, username, full_name, phone, haircut, price, date, time, master, duration, completed, actual = b
        if completed:
            continue
        shown += 1
        text_lines.append(
            f"#{bid} | <b>{full_name}</b> (@{username})\n"
            f"   ✂️ {haircut} ({price}₽) | 📅 {date} 🕐 {time}\n"
            f"   👨‍🦰 {master} | 📱 {phone}\n"
        )
        if shown >= 30:
            break

    await message.answer("\n".join(text_lines), reply_markup=admin_menu_kb())

    # кнопки отмены
    for b in bookings:
        bid, username, full_name, phone, haircut, price, date, time, master, duration, completed, actual = b
        if completed:
            continue
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🗑 Отменить запись #{bid}", callback_data=f"admin_cancel_booking|{bid}")]
        ])
        await message.answer(f"🎟 #{bid} | {full_name} | {date} {time}", reply_markup=kb)


@router.callback_query(F.data.startswith("admin_cancel_booking|"))
async def admin_cancel_booking_cb(callback: CallbackQuery) -> None:
    booking_id = int(callback.data.split("|", 1)[1])
    if cancel_booking(booking_id, force=True):
        await callback.answer("✅ Отменено")
        await callback.message.edit_text(f"✅ Запись #{booking_id} отменена админом")
    else:
        await callback.answer("❌ Ошибка при отмене", show_alert=True)


# ============================================================================
# Admin: Support
# ============================================================================
@router.message(F.text == "💬 Обработать техподдержку", lambda m: is_admin(m.from_user.id))
async def admin_support(message: Message) -> None:
    supports = get_pending_supports()
    if not supports:
        await message.answer("📭 Нет необработанных обращений.", reply_markup=admin_menu_kb())
        return

    for s in supports[:10]:
        sid, uid, username, full_name, phone, text, created_at = s
        support_text_msg = (
            f"💬 <b>Новое обращение #{sid}</b>\n"
            f"👤 Пользователь: <b>{full_name}</b> (@{username})\n"
            f"🆔 ID: {uid}\n"
            f"📱 Телефон: {phone}\n"
            f"⏰ Время: {created_at}\n\n"
            f"📝 Текст:\n{text}"
        )
        await message.answer(support_text_msg, reply_markup=support_action_kb(sid))


@router.callback_query(F.data.startswith("support_mark|"))
async def support_mark(callback: CallbackQuery) -> None:
    support_id = int(callback.data.split("|", 1)[1])
    mark_support_handled(support_id, admin_id=callback.from_user.id)
    await callback.answer("✅ Отмечено")
    await callback.message.edit_text("✅ Обращение обработано.")


@router.callback_query(F.data.startswith("support_reply|"))
async def support_reply(callback: CallbackQuery, state: FSMContext) -> None:
    support_id = int(callback.data.split("|", 1)[1])
    support = get_support_by_id(support_id)
    if not support:
        await callback.answer("❌ Обращение не найдено", show_alert=True)
        return

    await state.update_data(support_id=support_id, user_id=support[1])
    await state.set_state(SupportState.admin_reply)
    await callback.answer()
    await callback.message.answer("Введите ответ пользователю:")


@router.message(SupportState.admin_reply, lambda m: is_admin(m.from_user.id))
async def send_support_reply(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    support_id = data["support_id"]
    user_id = data["user_id"]

    reply_text = (message.text or "").strip()
    if len(reply_text) < 2:
        await message.answer("⚠️ Ответ слишком короткий. Напишите подробнее:")
        return

    mark_support_handled(support_id, admin_id=message.from_user.id, admin_reply=reply_text)
    await state.clear()

    try:
        await message.bot.send_message(
            user_id,
            f"💬 <b>Ответ от администратора</b>\n\n"
            f"Обращение #{support_id}\n\n"
            f"{reply_text}"
        )
    except Exception:
        pass

    await message.answer("✅ Ответ отправлен пользователю", reply_markup=admin_menu_kb())


# ============================================================================
# Admin: DB stats
# ============================================================================
@router.message(F.text == "📊 Статистика БД", lambda m: is_admin(m.from_user.id))
async def admin_stats(message: Message) -> None:
    stats = get_database_stats()
    text = (
        f"📊 <b>Статистика базы данных</b>\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"📅 Свободных слотов: <b>{stats['masters_slots']}</b>\n"
        f"⏳ Активных записей: <b>{stats['active_bookings']}</b>\n"
        f"✅ Завершённых записей: <b>{stats['completed_bookings']}</b>\n"
        f"💬 Необработанных обращений: <b>{stats['pending_support']}</b>"
    )
    await message.answer(text, reply_markup=admin_menu_kb())


# ============================================================================
# Admin: Report CSV
# ============================================================================
@router.message(F.text == "📈 Создать отчет", lambda m: is_admin(m.from_user.id))
async def admin_report(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminReportState.waiting_for_dates)
    await message.answer(
        "📅 Введите период для отчёта:\n"
        "<code>ГГГГ-ММ-ДД ГГГГ-ММ-ДД</code>\n\n"
        "Пример: <code>2025-12-01 2025-12-31</code>"
    )


@router.message(AdminReportState.waiting_for_dates, lambda m: is_admin(m.from_user.id))
async def generate_report(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").strip().split()
    if len(parts) != 2:
        await message.answer("⚠️ Неверный формат. Пример: <code>2025-12-01 2025-12-31</code>")
        return

    try:
        start_dt = datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=dt_timezone.utc)
        end_dt = datetime.strptime(parts[1], "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=dt_timezone.utc)
        if end_dt < start_dt:
            await message.answer("⚠️ Конечная дата раньше начальной.")
            return

        bookings = get_completed_bookings(start_dt, end_dt)
        if not bookings:
            await state.clear()
            await message.answer("📭 Нет завершённых записей за указанный период.", reply_markup=admin_menu_kb())
            return

        csv_content = "ID,Клиент,Телефон,Услуга,Цена,Дата,Время,Мастер,Оплачено\n"
        total_revenue = 0

        for b in bookings:
            actual_paid = b.get("actual_paid") if b.get("actual_paid") is not None else b.get("price", 0)
            total_revenue += int(actual_paid or 0)

            csv_content += (
                f"{b['id']},\"{b['full_name']}\",{b['phone']},"
                f"\"{b['haircut']}\",{b['price']},{b['date']},{b['time']},"
                f"{b['master']},{actual_paid}\n"
            )

        csv_content += (
            f"\n\nИтоги\n"
            f"Всего записей,{len(bookings)}\n"
            f"Общая выручка,{total_revenue}\n"
            f"Средний чек,{int(total_revenue / len(bookings)) if bookings else 0}\n"
        )

        file = FSInputFile(
            io.BytesIO(csv_content.encode("utf-8")),
            filename=f"report_{parts[0]}_to_{parts[1]}.csv",
        )

        await message.answer_document(
            file,
            caption=(
                f"📈 <b>Отчёт</b>\n\n"
                f"Период: {parts[0]} — {parts[1]}\n"
                f"Завершённых записей: {len(bookings)}\n"
                f"Общая выручка: {total_revenue}₽"
            ),
        )

        await state.clear()
        await message.answer("✅ Отчет создан", reply_markup=admin_menu_kb())

    except Exception as e:
        log.exception("Ошибка при создании отчёта")
        await state.clear()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=admin_menu_kb())


# ============================================================================
# Completion callbacks (from main.py completion loop)
# ============================================================================
@router.callback_query(F.data.startswith("complete_enter|"))
async def complete_booking_enter_sum(callback: CallbackQuery, state: FSMContext) -> None:
    booking_id = int(callback.data.split("|", 1)[1])
    await state.update_data(booking_id=booking_id)
    await state.set_state(CompletionState.waiting_for_amount)
    await callback.answer()
    await callback.message.answer(f"💰 Введите сумму оплаты для записи #{booking_id}:")


@router.message(StateFilter(CompletionState.waiting_for_amount), lambda m: is_admin(m.from_user.id))
async def save_completion_sum(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    booking_id = int(data.get("booking_id", 0))

    try:
        amount = int((message.text or "").strip())
        mark_booking_completed(booking_id, actual_paid=amount, completed_by=message.from_user.id)
        await state.clear()
        await message.answer(
            f"✅ Запись #{booking_id} завершена\nОплачено: {amount}₽",
            reply_markup=admin_menu_kb(),
        )
    except ValueError:
        await message.answer("⚠️ Введите число (сумму оплаты), например: 1200")
    except Exception as e:
        log.exception("Ошибка при сохранении суммы")
        await state.clear()
        await message.answer(f"❌ Ошибка: {str(e)}", reply_markup=admin_menu_kb())


@router.callback_query(F.data.startswith("complete_no|"))
async def complete_booking_no(callback: CallbackQuery) -> None:
    booking_id = int(callback.data.split("|", 1)[1])
    mark_booking_completed(booking_id, actual_paid=0, completed_by=callback.from_user.id)
    await callback.answer("✅ Отмечено")
    await callback.message.edit_text(f"❌ Запись #{booking_id} не состоялась")


# ============================================================================
# Admin -> User menu
# ============================================================================
@router.message(F.text == "👤 В пользовательское меню", lambda m: is_admin(m.from_user.id))
async def admin_back_to_user(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("👤 <b>Пользовательское меню:</b>", reply_markup=main_menu_kb())


# ============================================================================
# Global cancel
# ============================================================================
@router.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("❌ Отменено")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("Выберите действие:", reply_markup=user_home_kb(callback.from_user.id))
