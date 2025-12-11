# handlers.py – обработчики (полный, готовый к запуску)
# -------------------------------------------------
import csv
import os
import logging
from datetime import datetime, timezone

from aiogram import Router, F, exceptions
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile

from db import (
    add_user,
    get_user,
    add_booking,
    get_available_dates,
    get_available_times,
    get_available_masters,
    check_booking,
    get_user_bookings,
    cancel_booking,
    update_master_schedule,
    get_all_bookings_for_admin,
    get_booking_by_id,
    add_support_message,
    get_pending_supports,
    get_support_by_id,
    mark_support_handled,
    ensure_support_parent_column,
    get_all_master_slots,
    set_master_telegram,
    get_bookings_ending_before,
    mark_booking_completed,
    get_completed_bookings,
)
from keyboards import (
    main_menu_kb,
    admin_menu_kb,
    haircut_inline_kb,
    dates_inline_kb,
    times_inline_kb,
    masters_inline_kb,
    confirm_inline_kb,
    booking_row_kb,
    support_action_kb,
    admin_user_bookings_kb,
    completion_kb,
)

from config import (
    ADMIN_IDS,
    HAIRCUT_TYPES,
    CANCEL_LIMIT_HOURS,
    REPORTS_DIR,
)

# -------------------------------------------------
log = logging.getLogger(__name__)   # <-- единственный логгер в модуле
router = Router()


# --------------------------------------------------------------------------- #
#   FSM – состояния
# --------------------------------------------------------------------------- #
class UserState(StatesGroup):
    waiting_full_name = State()
    waiting_phone = State()
    choosing_haircut = State()
    choosing_date = State()
    choosing_time = State()
    choosing_master = State()
    confirming = State()
    admin_adding_master_name = State()
    admin_adding_master_dates = State()
    admin_adding_master_times = State()
    waiting_contact_message = State()
    admin_replying_support = State()
    master_enter_amount = State()


# --------------------------------------------------------------------------- #
#   Миграции (support parent_id)
# --------------------------------------------------------------------------- #
try:
    ensure_support_parent_column()
except Exception:
    log.debug("ensure_support_parent_column() failed – continue")


# --------------------------------------------------------------------------- #
#   /start – регистрируем как обычного пользователя, так и админа
# --------------------------------------------------------------------------- #
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)

    # Если это админ и его ещё нет в таблице users → создаём запись
    if message.from_user.id in ADMIN_IDS and not user:
        add_user(
            message.from_user.id,
            message.from_user.full_name or "—",
            message.from_user.username or "—",
        )
        user = get_user(message.from_user.id)

    if message.from_user.id in ADMIN_IDS:
        await state.clear()
        await message.answer(
            "🔧 Админ‑панель. Выберите действие:", reply_markup=admin_menu_kb()
        )
        return

    if not user:
        await message.answer(
            "👋 Привет! Добро пожаловать в нашу барбершоп‑систему!\n\n"
            "Для начала работы введите ваше ФИО (например: Иванов Иван Иванович):"
        )
        await state.set_state(UserState.waiting_full_name)
    else:
        await message.answer(
            f"🎉 Добро пожаловать обратно, {user[0]}!\n\n"
            "Выберите действие:",
            reply_markup=main_menu_kb(),
        )


# --------------------------------------------------------------------------- #
#   Регистрация обычного пользователя
# --------------------------------------------------------------------------- #
@router.message(UserState.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text or len(text.split()) < 2:
        await message.answer("⚠️ Пожалуйста, укажите ФИО полностью (минимум имя и фамилия).")
        return
    await state.update_data(full_name=text)
    await message.answer("📱 Теперь введите номер телефона (пример: +79161234567):")
    await state.set_state(UserState.waiting_phone)


@router.message(UserState.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = (message.text or "").strip()
    if len(phone) < 10:
        await message.answer("⚠️ Пожалуйста, введите корректный номер телефона.")
        return
    data = await state.get_data()
    full_name = data.get("full_name")
    add_user(message.from_user.id, full_name, phone)
    await message.answer(
        "✅ Регистрация завершена!\n\n"
        "Теперь вы можете записаться на стрижку 💈",
        reply_markup=main_menu_kb(),
    )
    await state.clear()


# --------------------------------------------------------------------------- #
#   Запись – начало процесса
# --------------------------------------------------------------------------- #
@router.message(F.text == "📅 Записаться")
async def cmd_book(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(UserState.choosing_haircut)
    await message.answer("✂️ Выберите тип услуги:", reply_markup=haircut_inline_kb())


# --------------------------------------------------------------------------- #
#   Выбор услуги → даты → время → мастер → подтверждение
# --------------------------------------------------------------------------- #
@router.callback_query(lambda c: c.data and c.data.startswith("haircut|"))
async def choose_haircut(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, haircut = cb.data.split("|", 1)
    price = HAIRCUT_TYPES.get(haircut, 0)
    await state.update_data(haircut=haircut, price=price)

    dates = get_available_dates()
    if not dates:
        await cb.message.edit_text(
            "😔 К сожалению, пока нет доступных слотов.\n"
            "Администратор должен добавить расписание."
        )
        return

    await state.set_state(UserState.choosing_date)
    await cb.message.edit_text(
        f"✅ Вы выбрали: {haircut} — {price}₽\n\n📅 Выберите дату:",
        reply_markup=dates_inline_kb(dates),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("date|"))
async def choose_date(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, date = cb.data.split("|", 1)
    await state.update_data(date=date)
    await state.set_state(UserState.choosing_time)

    times = get_available_times(date)
    if not times:
        await cb.message.edit_text("😔 На эту дату нет свободных времен. Выберите другую дату.")
        return

    await cb.message.edit_text(
        f"📅 Выбрана дата: {date}\n\n🕐 Выберите время:",
        reply_markup=times_inline_kb(times),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("time|"))
async def choose_time(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, time = cb.data.split("|", 1)
    await state.update_data(time=time)
    await state.set_state(UserState.choosing_master)

    data = await state.get_data()
    date = data.get("date")
    masters = get_available_masters(date, time)

    if not masters:
        await cb.message.edit_text("😔 Нет свободных мастеров на выбранное время.")
        await state.clear()
        return

    await cb.message.edit_text(
        f"🕐 Выбрано время: {time}\n\n👨‍🦰 Выберите мастера:",
        reply_markup=masters_inline_kb(masters),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("master|"))
async def choose_master(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, master = cb.data.split("|", 1)

    if master == "ANY":
        data = await state.get_data()
        date = data.get("date")
        time = data.get("time")
        masters = get_available_masters(date, time)
        if not masters:
            await cb.message.edit_text("😔 Нет доступных мастеров.")
            await state.clear()
            return
        master = masters[0]

    await state.update_data(master=master)
    await state.set_state(UserState.confirming)

    data = await state.get_data()
    msg = (
        "📋 Подтвердите запись:\n\n"
        f"✂️ Услуга: {data.get('haircut')} — {data.get('price')}₽\n"
        f"📅 Дата: {data.get('date')}\n"
        f"🕐 Время: {data.get('time')}\n"
        f"👨‍🦰 Мастер: {data.get('master')}\n"
    )
    await cb.message.edit_text(msg, reply_markup=confirm_inline_kb())


@router.callback_query(lambda c: c.data and c.data.startswith("confirm|"))
async def process_confirm(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, choice = cb.data.split("|", 1)

    if choice == "no":
        await cb.message.edit_text("❌ Запись отменена.", reply_markup=None)
        await cb.bot.send_message(cb.from_user.id, "Главное меню:", reply_markup=main_menu_kb())
        await state.clear()
        return

    data = await state.get_data()
    u = get_user(cb.from_user.id)
    if not u:
        await cb.message.edit_text(
            "⚠️ Пожалуйста, зарегистрируйтесь заново через /start.",
            reply_markup=None,
        )
        await state.clear()
        return

    full_name, phone = u
    if check_booking(data["master"], data["date"], data["time"]):
        await cb.message.edit_text(
            "😔 Выбранный слот уже занят. Попробуйте другой.", reply_markup=None
        )
        await state.clear()
        return

    try:
        booking_id = add_booking(
            cb.from_user.id,
            cb.from_user.username or "",
            full_name,
            phone,
            data["haircut"],
            data["price"],
            data["date"],
            data["time"],
            data["master"],
        )
    except ValueError as e:
        await cb.message.edit_text(f"❌ Не удалось создать запись: {e}", reply_markup=None)
        await state.clear()
        return

    await cb.message.edit_text(
        "✅ Готово — запись подтверждена!\n\n"
        "🔔 Мы отправим напоминание за 24 ч и 1 ч до визита.\n"
        "❤️ Спасибо, что выбрали нас!",
        reply_markup=None,
    )
    await cb.bot.send_message(cb.from_user.id, "Главное меню:", reply_markup=main_menu_kb())

    admin_msg = (
        f"🆕 Новая запись:\n"
        f"👤 {full_name} (@{cb.from_user.username or '—'})\n"
        f"✂️ Услуга: {data['haircut']} — {data['price']}₽\n"
        f"📅 Дата: {data['date']} {data['time']}\n"
        f"👨‍🦰 Мастер: {data['master']}"
    )
    for aid in ADMIN_IDS:
        try:
            await cb.bot.send_message(aid, admin_msg)
        except Exception:
            log.exception("Не удалось уведомить админа %s", aid)

    await state.clear()


# --------------------------------------------------------------------------- #
#   Мои записи
# --------------------------------------------------------------------------- #
@router.message(F.text == "📋 Мои записи")
async def my_bookings(message: Message):
    bookings = get_user_bookings(message.from_user.id)
    if not bookings:
        await message.answer("📭 У вас нет активных записей.", reply_markup=main_menu_kb())
        return
    await message.answer("📋 Ваши записи:")
    for b in bookings:
        bid, haircut, price, date, time, master = b
        txt = (
            f"🎫 Запись #{bid}\n"
            f"✂️ Услуга: {haircut} — {price}₽\n"
            f"📅 Дата: {date}\n"
            f"🕐 Время: {time}\n"
            f"👨‍🦰 Мастер: {master}"
        )
        await message.answer(txt, reply_markup=booking_row_kb(bid))


# --------------------------------------------------------------------------- #
#   Отмена записи (пользователь)
# --------------------------------------------------------------------------- #
@router.callback_query(lambda c: c.data and c.data.startswith("cancel_booking|"))
async def cb_cancel_booking(cb: CallbackQuery):
    await cb.answer()
    _, bid_str = cb.data.split("|", 1)
    booking_id = int(bid_str)

    booking = get_booking_by_id(booking_id)
    if not booking:
        await cb.message.edit_text("❌ Запись не найдена или уже отменена.", reply_markup=None)
        return

    (
        _,
        user_id,
        username,
        full_name,
        phone,
        haircut,
        price,
        date_str,
        time_str,
        master,
        duration_minutes,
        *_,
    ) = booking

    if cb.from_user.id != user_id and cb.from_user.id not in ADMIN_IDS:
        await cb.message.edit_text("❌ Вы не можете отменить чужую запись.", reply_markup=None)
        return

    appt_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc
    )
    now_dt = datetime.now(timezone.utc)

    if cb.from_user.id not in ADMIN_IDS:
        delta_sec = (appt_dt - now_dt).total_seconds()
        if delta_sec < CANCEL_LIMIT_HOURS * 3600:
            await cb.message.edit_text(
                f"⚠️ Отмена запрещена менее, чем за {CANCEL_LIMIT_HOURS} часа(ов) до записи.",
                reply_markup=None,
            )
            return

    ok = cancel_booking(booking_id)
    if ok:
        await cb.message.edit_text("✅ Запись отменена.", reply_markup=None)
        await cb.bot.send_message(cb.from_user.id, "Главное меню:", reply_markup=main_menu_kb())
        admin_msg = (
            f"❌ Отмена записи #{booking_id}:\n"
            f"👤 {full_name} (@{username or '—'})\n"
            f"📅 {date_str} {time_str}\n"
            f"👨‍🦰 Мастер: {master}"
        )
        for aid in ADMIN_IDS:
            try:
                await cb.bot.send_message(aid, admin_msg)
            except Exception:
                log.exception("Не удалось уведомить админа %s", aid)
    else:
        await cb.message.edit_text(
            "❌ Не удалось отменить запись. Попробуйте позже.", reply_markup=None
        )


# --------------------------------------------------------------------------- #
#   Админ: добавление мастера/слотов
# --------------------------------------------------------------------------- #
@router.message(lambda m: m.text == "➕ Добавить мастера/слоты" and m.from_user.id in ADMIN_IDS)
async def admin_add_master(message: Message, state: FSMContext):
    await state.set_state(UserState.admin_adding_master_name)
    await message.answer("👨‍🦰 Введите имя мастера:")


@router.message(UserState.admin_adding_master_name)
async def admin_master_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("⚠️ Имя мастера не может быть пустым.")
        return
    await state.update_data(master_name=name)
    await state.set_state(UserState.admin_adding_master_dates)
    await message.answer(
        "📅 Введите период дат в формате:\n"
        "ГГГГ‑ММ‑ДД ГГГГ‑ММ‑ДД\n\n"
        "Пример: 2025-11-01 2025-11-07"
    )


@router.message(UserState.admin_adding_master_dates)
async def admin_master_dates(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) != 2:
        await message.answer("⚠️ Неверный формат. Введите две даты через пробел.")
        return

    start_date, end_date = parts
    # ---- проверка, что конец ≥ начало ----
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d")
        if ed < sd:
            raise ValueError
    except Exception:
        await message.answer("⚠️ Даты указаны неверно или конец < начало. Попробуйте ещё раз.")
        return

    await state.update_data(start_date=start_date, end_date=end_date)
    await state.set_state(UserState.admin_adding_master_times)
    await message.answer(
        "🕐 Введите время работы и шаг в формате:\n"
        "ЧЧ:ММ ЧЧ:ММ шаг_минут\n\n"
        "Пример: 09:00 18:00 60"
    )


@router.message(UserState.admin_adding_master_times)
async def admin_master_times(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) != 3:
        await message.answer("⚠️ Неверный формат. Введите время начала, конца и шаг.")
        return

    start_time, end_time, step = parts
    # ---- проверка времени ----
    try:
        st = datetime.strptime(start_time, "%H:%M")
        et = datetime.strptime(end_time, "%H:%M")
        if et <= st:
            raise ValueError
        step_int = int(step)
        if step_int <= 0:
            raise ValueError
    except Exception:
        await message.answer("⚠️ Время указано неверно или шаг не положителен.")
        return

    data = await state.get_data()
    master_name = data.get("master_name")
    start_date = data.get("start_date")
    end_date = data.get("end_date")

    try:
        update_master_schedule(
            master_name, start_date, end_date, start_time, end_time, step_int
        )
        await message.answer(
            f"✅ Расписание для мастера «{master_name}» добавлено!\n\n"
            f"📅 Период: {start_date} – {end_date}\n"
            f"🕐 Время: {start_time} – {end_time}\n"
            f"⏱ Шаг: {step_int} минут",
            reply_markup=admin_menu_kb(),
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении расписания: {e}")

    await state.clear()


# --------------------------------------------------------------------------- #
# Статистика БД (админ).
# --------------------------------------------------------------------------- #
@router.message(lambda m: m.text == "📊 Статистика БД" and m.from_user.id in ADMIN_IDS)
async def admin_show_stats(message: Message):
    """Показывает статистику базы данных."""
    from db import get_database_stats

    stats = get_database_stats()

    text = (
        "📊 <b>Статистика базы данных</b>\n\n"
        f"👥 Пользователей: {stats['users']}\n"
        f"📅 Свободных слотов мастеров: {stats['masters_slots']}\n"
        f"⏳ Активных записей: {stats['active_bookings']}\n"
        f"✅ Завершённых записей: {stats['completed_bookings']}\n"
        f"💬 Необработанных обращений: {stats['pending_support']}\n"
    )

    await message.answer(text, reply_markup=admin_menu_kb())


# --------------------------------------------------------------------------- #
#   Показ слотов мастеров
# --------------------------------------------------------------------------- #
@router.message(lambda m: m.text == "📊 Показать слоты мастеров" and m.from_user.id in ADMIN_IDS)
async def admin_show_master_slots(message: Message):
    slots = get_all_master_slots()
    if not slots:
        await message.answer("📭 Слотов мастеров не найдено.", reply_markup=admin_menu_kb())
        return

    lines = ["📊 Слоты мастеров:\n"]
    for s in slots:
        tid = s.get("telegram_id") or "—"
        lines.append(
            f"🆔 {s['id']}: {s['name']} | 📅 {s['available_date']} 🕐 {s['available_time']} | tg: {tid}"
        )
    text = "\n".join(lines)

    if len(text) > 3500:
        fn = os.path.join(
            REPORTS_DIR,
            f"master_slots_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        with open(fn, "w", encoding="utf-8") as f:
            f.write(text)
        await message.answer_document(FSInputFile(fn))
        os.remove(fn)
    else:
        await message.answer(text, reply_markup=admin_menu_kb())


# --------------------------------------------------------------------------- #
#   Привязка telegram_id к мастеру
# --------------------------------------------------------------------------- #
@router.message(lambda m: m.text.startswith("🔗 Привязать мастера") and m.from_user.id in ADMIN_IDS)
async def admin_bind_master(message: Message):
    parts = message.text.strip().split()
    if len(parts) < 4:
        await message.answer(
            "📝 Формат: 🔗 Привязать мастера <Имя> <telegram_id>\n\n"
            "Пример: 🔗 Привязать мастера Анна 123456789"
        )
        return
    name = parts[2]
    tid_str = parts[3]
    try:
        tid = int(tid_str)
    except Exception:
        await message.answer("⚠️ telegram_id должен быть числом.")
        return
    updated = set_master_telegram(name, tid)
    await message.answer(
        f"✅ Обновлено строк: {updated}\n"
        f"Мастер «{name}» теперь привязан к telegram_id {tid}"
    )


# --------------------------------------------------------------------------- #
#   Создание отчёта (CSV)
# --------------------------------------------------------------------------- #
@router.message(lambda m: m.text == "📈 Создать отчет" and m.from_user.id in ADMIN_IDS)
async def admin_create_report(message: Message):
    rows = get_completed_bookings()
    if not rows:
        await message.answer(
            "📭 Нет завершённых стрижек, отчёт не сформирован.",
            reply_markup=admin_menu_kb(),
        )
        return

    fn = os.path.join(
        REPORTS_DIR,
        f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv",
    )
    with open(fn, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ID",
                "Завершено (UTC)",
                "Дата",
                "Время",
                "Мастер",
                "Услуга",
                "Цена",
                "Фактически",
                "User ID",
                "ФИО",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r["id"],
                    r.get("completed_at"),
                    r.get("date"),
                    r.get("time"),
                    r.get("master"),
                    r.get("haircut"),
                    r.get("price"),
                    r.get("actual_paid"),
                    r.get("user_id"),
                    r.get("full_name"),
                ]
            )
    await message.answer("📈 Отчёт готов:", reply_markup=admin_menu_kb())
    await message.answer_document(FSInputFile(fn))
    os.remove(fn)


# --------------------------------------------------------------------------- #
#   Просмотр всех записей (админ)
# --------------------------------------------------------------------------- #
@router.message(lambda m: m.text == "📋 Просмотр записей" and m.from_user.id in ADMIN_IDS)
async def admin_view_bookings(message: Message):
    data = get_all_bookings_for_admin()
    if not data:
        await message.answer("📭 Записей нет.", reply_markup=admin_menu_kb())
        return

    lines = ["📋 Все записи:\n"]
    for row in data:
        (
            bid,
            username,
            full_name,
            phone,
            haircut,
            price,
            date,
            time,
            master,
            duration,
            completed,
            actual_paid,
        ) = row
        status = "✅" if completed else "⏳"
        lines.append(
            f"{status} #{bid} | 📅 {date} 🕐 {time} | 👨‍🦰 {master}\n"
            f"   ✂️ {haircut} {price}₽ | 👤 {full_name} | ⏱ {duration} мин"
        )
    text = "\n".join(lines)

    if len(text) > 3500:
        fn = os.path.join(
            REPORTS_DIR,
            f"bookings_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        with open(fn, "w", encoding="utf-8") as f:
            f.write(text)
        await message.answer_document(FSInputFile(fn))
        os.remove(fn)
    else:
        await message.answer(text, reply_markup=admin_menu_kb())


# --------------------------------------------------------------------------- #
#   Техподдержка – пользователи
# --------------------------------------------------------------------------- #
@router.message(F.text == "💬 Связаться с админом")
async def contact_admin(message: Message, state: FSMContext):
    await message.answer(
        "✍️ Напишите ваше сообщение для администраторов.\n"
        "Оно будет сохранено и появится в админ‑панели.\n\n"
        "(Напишите /cancel, чтобы отменить.)"
    )
    await state.set_state(UserState.waiting_contact_message)


@router.message(UserState.waiting_contact_message)
async def save_contact_and_notify(message: Message, state: FSMContext):
    data = await state.get_data()
    parent_id = data.get("parent_support_id")
    text = message.text or ""
    uid = message.from_user.id
    u = get_user(uid)
    full_name = u[0] if u else (message.from_user.full_name or "—")
    phone = u[1] if u and len(u) > 1 else "—"
    username = message.from_user.username or ""

    sid = add_support_message(uid, username, full_name, phone, text, parent_id=parent_id)
    admin_msg = (
        f"💬 Новое обращение #{sid}\n"
        f"👤 Пользователь: {full_name} (@{username or '—'})\n"
        f"🆔 ID: {uid}\n\n"
        f"📝 Текст:\n{text}"
    )
    for aid in ADMIN_IDS:
        try:
            await message.bot.send_message(
                aid, admin_msg, reply_markup=support_action_kb(sid)
            )
        except Exception:
            log.exception("Не удалось послать обращение админу %s", aid)

    await message.answer(
        "✅ Ваше обращение отправлено в поддержку. Спасибо!",
        reply_markup=main_menu_kb(),
    )
    await state.clear()


# --------------------------------------------------------------------------- #
#   Обработка обращений администратором
# --------------------------------------------------------------------------- #
@router.message(lambda m: m.text == "💬 Обработать ТП" and m.from_user.id in ADMIN_IDS)
async def admin_process_support(message: Message):
    supports = get_pending_supports()
    if not supports:
        await message.answer(
            "📭 Нет необработанных обращений.", reply_markup=admin_menu_kb()
        )
        return

    for s in supports:
        sid, user_id, username, full_name, phone, text, created_at = s
        msg = (
            f"💬 Обращение #{sid}\n"
            f"👤 Пользователь: {full_name} (@{username or '—'})\n"
            f"🆔 ID: {user_id}\n"
            f"📅 Дата: {created_at}\n\n"
            f"📝 Текст:\n{text}"
        )
        await message.answer(msg, reply_markup=support_action_kb(sid))


@router.callback_query(lambda c: c.data and c.data.startswith("support_mark|"))
async def support_mark_handled(cb: CallbackQuery):
    await cb.answer()
    _, sid_str = cb.data.split("|", 1)
    sid = int(sid_str)
    mark_support_handled(sid, admin_id=cb.from_user.id)
    await cb.message.edit_text(
        f"✅ Обращение #{sid} помечено как обработанное.",
        reply_markup=None,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("support_reply|"))
async def support_reply(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, sid_str = cb.data.split("|", 1)
    sid = int(sid_str)
    s = get_support_by_id(sid)
    if not s:
        await cb.message.answer("❌ Обращение не найдено.")
        return

    (
        _,
        user_id,
        username,
        full_name,
        phone,
        text,
        created_at,
        handled,
        admin_id,
        admin_reply,
        parent_id,
    ) = s

    await state.update_data(reply_to_support=sid, reply_to_user=user_id)
    await state.set_state(UserState.admin_replying_support)
    await cb.message.answer(
        f"✍️ Введите ответ для пользователя {full_name} (ID: {user_id}):"
    )


@router.message(UserState.admin_replying_support)
async def admin_send_reply(message: Message, state: FSMContext):
    d = await state.get_data()
    sid = d.get("reply_to_support")
    uid = d.get("reply_to_user")
    reply_text = (message.text or "").strip()
    if not reply_text:
        await message.answer("⚠️ Ответ не может быть пустым.")
        return

    mark_support_handled(sid, admin_id=message.from_user.id, admin_reply=reply_text)

    try:
        await message.bot.send_message(
            uid,
            f"💬 Ответ от администратора:\n\n{reply_text}",
        )
        await message.answer(
            "✅ Ответ отправлен пользователю.", reply_markup=admin_menu_kb()
        )
    except Exception as exc:
        await message.answer(f"❌ Не удалось отправить ответ: {exc}")

    await state.clear()


@router.callback_query(lambda c: c.data and c.data.startswith("support_cancel|"))
async def support_cancel_user_booking(cb: CallbackQuery):
    await cb.answer()
    _, sid_str = cb.data.split("|", 1)
    sid = int(sid_str)
    s = get_support_by_id(sid)
    if not s:
        await cb.message.answer("❌ Обращение не найдено.")
        return

    (
        _,
        user_id,
        username,
        full_name,
        phone,
        text,
        created_at,
        handled,
        admin_id,
        admin_reply,
        parent_id,
    ) = s

    bookings = get_user_bookings(user_id)
    if not bookings:
        await cb.message.answer("📭 У пользователя нет активных записей.")
        return

    await cb.message.answer(
        f"📋 Записи пользователя {full_name}:\nВыберите запись для отмены:",
        reply_markup=admin_user_bookings_kb(bookings),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("admin_cancel_booking|"))
async def admin_cancel_user_booking(cb: CallbackQuery):
    await cb.answer()
    _, bid_str = cb.data.split("|", 1)
    bid = int(bid_str)

    ok = cancel_booking(bid, force=True)
    if ok:
        await cb.message.edit_text(
            f"✅ Запись #{bid} отменена администратором.", reply_markup=None
        )
        booking = get_booking_by_id(bid)
        if booking and len(booking) > 2:
            user_id = booking[1]
            try:
                await cb.bot.send_message(
                    user_id,
                    "⚠️ Ваша запись была отменена администратором.\n"
                    "Для уточнения причин свяжитесь с администрацией.",
                )
            except Exception:
                log.exception("Не удалось уведомить пользователя %s об отмене", user_id)
    else:
        await cb.message.edit_text("❌ Не удалось отменить запись.", reply_markup=None)


# --------------------------------------------------------------------------- #
#   Возврат из админ‑панели в пользовательскую
# --------------------------------------------------------------------------- #
@router.message(
    lambda m: m.text == "👤 В пользовательское меню" and m.from_user.id in ADMIN_IDS
)
async def admin_to_user_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👤 Пользовательское меню:", reply_markup=main_menu_kb())


@router.message(
    lambda m: m.text == "◀️ Назад" and m.from_user.id in ADMIN_IDS
)
async def admin_back(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🔧 Админ‑панель:", reply_markup=admin_menu_kb())


# --------------------------------------------------------------------------- #
#   Завершение записи (модуль Completion)
# --------------------------------------------------------------------------- #
@router.callback_query(lambda c: c.data and c.data.startswith("complete_no|"))
async def complete_no_cb(cb: CallbackQuery):
    await cb.answer()
    _, bid_str = cb.data.split("|", 1)
    bid = int(bid_str)
    ok = mark_booking_completed(bid, actual_paid=0, completed_by=cb.from_user.id, succeeded=False)
    if ok:
        await cb.message.edit_text("✅ Отмечено: запись НЕ состоялась.", reply_markup=None)
        await cb.answer("Отмечено")
    else:
        await cb.answer("❌ Не удалось отметить — попробуйте позже.")


@router.callback_query(lambda c: c.data and c.data.startswith("complete_enter|"))
async def complete_enter_cb(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, bid_str = cb.data.split("|", 1)
    bid = int(bid_str)
    await state.update_data(master_confirm_booking=bid)
    await state.set_state(UserState.master_enter_amount)
    await cb.message.answer("💰 Введите сумму, которую заплатил клиент (рубли):")


@router.message(UserState.master_enter_amount)
async def master_enter_amount(message: Message, state: FSMContext):
    d = await state.get_data()
    bid = d.get("master_confirm_booking")
    if not bid:
        await message.answer("❌ Ошибка: не найден ID записи.")
        await state.clear()
        return

    txt = (message.text or "").strip()
    try:
        amount = int(float(txt))
    except Exception:
        await message.answer("⚠️ Введите сумму цифрами, например: 1200")
        return

    ok = mark_booking_completed(
        bid, actual_paid=amount, completed_by=message.from_user.id, succeeded=True
    )
    if ok:
        await message.answer("✅ Запись отмечена как выполненная.")
        for aid in ADMIN_IDS:
            try:
                await message.bot.send_message(
                    aid,
                    f"✅ Запись #{bid} подтверждена мастером.\n💰 Фактическая оплата: {amount}₽",
                )
            except Exception:
                log.exception("Не удалось уведомить админа %s", aid)
    else:
        await message.answer("❌ Не удалось сохранить данные, попробуйте позже.")
    await state.clear()


# --------------------------------------------------------------------------- #
#   Универсальная отмена (/cancel)
# --------------------------------------------------------------------------- #
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in ADMIN_IDS:
        await message.answer("❌ Действие отменено.", reply_markup=admin_menu_kb())
    else:
        await message.answer("❌ Действие отменено.", reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    try:
        await cb.message.edit_text("❌ Действие отменено.", reply_markup=None)
    except Exception:
        pass
    if cb.from_user.id in ADMIN_IDS:
        await cb.bot.send_message(cb.from_user.id, "🔧 Админ‑панель:", reply_markup=admin_menu_kb())
    else:
        await cb.bot.send_message(cb.from_user.id, "Главное меню:", reply_markup=main_menu_kb())
    await state.clear()


# --------------------------------------------------------------------------- #
#   Экспорт роутера
# --------------------------------------------------------------------------- #
__all__ = ["router"]

