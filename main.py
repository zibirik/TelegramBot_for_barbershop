# main.py – точка входа в Barbershop Bot
# -------------------------------------------------
# Всё, что нужно, уже реализовано в отдельных модулях
# (config, db, handlers, keyboards). Здесь только
# инициализация, запуск фоновых задач и запуск polling.

import asyncio
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from aiogram import Bot, Dispatcher, exceptions
from aiogram.fsm.storage.memory import MemoryStorage

from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import (
    BOT_TOKEN,
    REMINDER_HOURS,
    BACKGROUND_CHECK_INTERVAL,
    CLEANUP_INTERVAL_SECONDS,
    COMPLETION_CHECK_INTERVAL,
    ADMIN_IDS,
)
from db import (
    init_db,
    get_all_bookings_due_between,
    mark_reminder_sent,
    remove_expired_master_slots,
    ensure_support_parent_column,
    get_bookings_ending_before,
    get_all_master_slots,
    mark_booking_completed,
)
from handlers import router

# --------------------------------------------------------------------------- #
#   Логирование
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#   Напоминания (24 ч и 1 ч)
# --------------------------------------------------------------------------- #
async def run_reminder_cycle(bot: Bot) -> None:
    """
    Проверяем записи, у которых осталось ровно 24 ч или 1 ч до начала,
    и отправляем пользователю текстовое напоминание.
    """
    now_utc = datetime.now(dt_timezone.utc)

    for hours in REMINDER_HOURS:                     # [24, 1]
        target = now_utc + timedelta(hours=hours)    # момент, когда должно быть напоминание
        window_start = target - timedelta(minutes=5)  # ±5 минутный «запас», чтобы не пропустить
        window_end = target + timedelta(minutes=5)

        log.debug(
            "Проверяем окна напоминаний: %s ч → %s … %s",
            hours,
            window_start.isoformat(),
            window_end.isoformat(),
        )

        bookings = get_all_bookings_due_between(window_start, window_end)
        if not bookings:
            continue

        for b in bookings:
            b_id = b["id"]
            user_id = b["user_id"]
            text = (
                f"🔔 Напоминание о записи через {hours} ч:\n\n"
                f"✂️ Услуга: {b['haircut']} — {b['price']}₽\n"
                f"📅 Дата и время: {b['date']} {b['time']}\n"
                f"👨‍🦰 Мастер: {b['master']}\n\n"
                f"Ждём вас! ❤️"
            )
            try:
                await bot.send_message(user_id, text)
                mark_reminder_sent(b_id, hours)   # обновляем флаг в БД
                log.info("Отправлено напоминание (%s ч) → запись #%s", hours, b_id)
            except exceptions.TelegramBadRequest as exc:
                # если пользователь удалил чат/заблокировал бота – просто логируем
                if "chat not found" in str(exc) or "user is deactivated" in str(exc):
                    log.warning("Пользователь %s недоступен – пропуск", user_id)
                else:
                    log.exception("Ошибка отправки напоминания пользователю %s", user_id)


async def reminder_loop(bot: Bot) -> None:
    """Бесконечный цикл‑пуллера для напоминаний."""
    log.info(
        "🔔 Запуск цикла напоминаний (часы=%s, интервал=%s сек)",
        REMINDER_HOURS,
        BACKGROUND_CHECK_INTERVAL,
    )
    while True:
        try:
            await run_reminder_cycle(bot)
        except Exception:
            log.exception("Ошибка в reminder_loop")
        await asyncio.sleep(BACKGROUND_CHECK_INTERVAL)


# --------------------------------------------------------------------------- #
#   Очистка просроченных слотов мастеров
# --------------------------------------------------------------------------- #
async def cleanup_loop() -> None:
    log.info(
        "🧹 Запуск цикла очистки просроченных слотов (интервал=%s сек)",
        CLEANUP_INTERVAL_SECONDS,
    )
    while True:
        try:
            removed = remove_expired_master_slots()
            if removed:
                log.info("🧹 Удалено %d просроченных слотов", removed)
        except Exception:
            log.exception("Ошибка в cleanup_loop")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


# --------------------------------------------------------------------------- #
#   Проверка завершения записей (мастер отмечает выполнено/не выполнено)
# --------------------------------------------------------------------------- #
async def completion_loop(bot: Bot) -> None:
    log.info(
        "✅ Запуск цикла проверки завершения записей (интервал=%s сек)",
        COMPLETION_CHECK_INTERVAL,
    )
    while True:
        try:
            now_utc = datetime.now(dt_timezone.utc)
            due = get_bookings_ending_before(now_utc)
            for b in due:
                bid = b["id"]
                master_name = b["master"]

                # ищем telegram_id мастера, если он привязан
                tg_id = None
                for slot in get_all_master_slots():
                    if slot["name"] == master_name and slot.get("telegram_id"):
                        tg_id = slot["telegram_id"]
                        break

                # Формируем клавиатуру для мастера
                kb = InlineKeyboardBuilder()
                kb.button(
                    text="✅ Была — ввести сумму",
                    callback_data=f"complete_enter|{bid}",
                )
                kb.button(
                    text="❌ Не состоялась",
                    callback_data=f"complete_no|{bid}",
                )
                markup = kb.as_markup()

                msg = (
                    f"⏰ Запись #{bid} завершилась.\n"
                    f"Мастер: {master_name}\n"
                    f"Услуга: {b['haircut']} — {b['price']}₽\n"
                    f"Клиент: {b['full_name']}\n\n"
                    f"Подтвердите выполнение:"
                )

                targets = [tg_id] if tg_id else ADMIN_IDS
                for target in targets:
                    if not target:
                        continue
                    try:
                        await bot.send_message(target, msg, reply_markup=markup)
                        log.info(
                            "📨 Запрос подтверждения записи #%s отправлен пользователю %s",
                            bid,
                            target,
                        )
                    except Exception:
                        log.exception("Не удалось отправить запрос подтверждения %s", target)
        except Exception:
            log.exception("Ошибка в completion_loop")
        await asyncio.sleep(COMPLETION_CHECK_INTERVAL)


# --------------------------------------------------------------------------- #
#   Основная функция запуска
# --------------------------------------------------------------------------- #
async def main() -> None:
    log.info("🚀 Запуск Barbershop Bot...")

    # ------------------- инициализация БД -------------------
    init_db()
    ensure_support_parent_column()

    # ------------------- стартовое «чисто» удаление просроченных слотов -------------------
    removed = remove_expired_master_slots()
    if removed:
        log.info("🧹 Удалено %d просроченных слотов при старте", removed)

    # ------------------- Bot & Dispatcher -------------------
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.include_router(router)

    # ------------------- фоновые задачи -------------------
    tasks = [
        asyncio.create_task(reminder_loop(bot)),
        asyncio.create_task(cleanup_loop()),
        asyncio.create_task(completion_loop(bot)),
    ]

    # ------------------- запуск polling -------------------
    try:
        await dp.start_polling(bot)
    except Exception as exc:
        log.error("❌ Ошибка в polling: %s", exc)
    finally:
        # Останавливаем фоновые задачи корректно
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()
        log.info("🔚 Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
