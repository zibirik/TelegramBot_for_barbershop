# main.py – Production-ready точка входа Barbershop Bot
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone as dt_timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import (
    ADMIN_IDS,
    BACKGROUND_CHECK_INTERVAL,
    BOT_TOKEN,
    CLEANUP_INTERVAL_SECONDS,
    COMPLETION_CHECK_INTERVAL,
    ENABLE_AUTO_CLEANUP,
    LOGS_DIR,
)
from db import (
    cleanup_all_expired_data,
    ensure_support_parent_column,
    get_all_bookings_due_between,
    get_all_master_slots,
    get_bookings_ending_before,
    get_database_stats,
    init_db,
    mark_reminder_sent,
    remove_expired_master_slots,
    vacuum_database,
)
from handlers import router
from keyboards import completion_kb


# ============================================================================
# Logging Setup
# ============================================================================
def setup_logging() -> logging.Logger:
    """Настраивает систему логирования."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Консольный хэндлер
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Файловый хэндлер с ротацией
    log_file = Path(LOGS_DIR) / "barbershop_bot.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))

    # Хэндлер для ошибок
    error_file = Path(LOGS_DIR) / "errors.log"
    error_handler = RotatingFileHandler(
        error_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(log_format, date_format))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)

    # Отключаем verbose логи aiogram
    logging.getLogger("aiogram").setLevel(logging.WARNING)

    return logging.getLogger(__name__)


log = setup_logging()


# ============================================================================
# Reminder System
# ============================================================================
async def run_reminder_cycle(bot: Bot) -> None:
    """Отправляет напоминания за 24ч, 1ч и 30 минут."""
    from config import REMINDER_HOURS

    now_utc = datetime.now(dt_timezone.utc)

    # Напоминания за 24ч и 1ч
    for hours in REMINDER_HOURS:
        target = now_utc + timedelta(hours=hours)
        window_start = target - timedelta(minutes=5)
        window_end = target + timedelta(minutes=5)

        bookings = get_all_bookings_due_between(window_start, window_end)

        for b in bookings:
            if hours == 24 and b.get("remind_24_sent"):
                continue
            if hours == 1 and b.get("remind_1_sent"):
                continue

            b_id = b["id"]
            user_id = b["user_id"]

            dt_obj = b["datetime"]
            date_str = dt_obj.strftime("%d.%m.%Y")
            time_str = dt_obj.strftime("%H:%M")

            text = (
                f"🔔 <b>Напоминание о записи через {hours} ч</b>\n\n"
                f"✂️ Услуга: <b>{b['haircut']}</b> — {b['price']}₽\n"
                f"📅 Дата: <b>{date_str}</b>\n"
                f"🕐 Время: <b>{time_str}</b>\n"
                f"👨‍🦰 Мастер: <b>{b['master']}</b>\n\n"
                f"Ждём вас! ❤️"
            )

            try:
                await bot.send_message(user_id, text)
                mark_reminder_sent(b_id, hours)
                log.info(f"✅ Напоминание ({hours}ч) отправлено для записи #{b_id}")
            except Exception as exc:
                if "chat not found" in str(exc).lower() or "user is deactivated" in str(exc).lower():
                    log.warning(f"⚠️ Пользователь {user_id} недоступен")
                else:
                    log.exception(f"❌ Ошибка отправки напоминания пользователю {user_id}")

    # Напоминание за 30 минут
    target_30 = now_utc + timedelta(minutes=30)
    window_start_30 = target_30 - timedelta(minutes=2)
    window_end_30 = target_30 + timedelta(minutes=2)

    bookings_30 = get_all_bookings_due_between(window_start_30, window_end_30)

    for b in bookings_30:
        if b.get("remind_30_sent"):
            continue

        b_id = b["id"]
        user_id = b["user_id"]

        dt_obj = b["datetime"]
        date_str = dt_obj.strftime("%d.%m.%Y")
        time_str = dt_obj.strftime("%H:%M")

        text = (
            f"🔔 <b>Напоминание! Через 30 минут</b>\n\n"
            f"✂️ Услуга: <b>{b['haircut']}</b> — {b['price']}₽\n"
            f"📅 Дата: <b>{date_str}</b>\n"
            f"🕐 Время: <b>{time_str}</b>\n"
            f"👨‍🦰 Мастер: <b>{b['master']}</b>\n\n"
            f"⏰ Не опаздывайте!"
        )

        try:
            await bot.send_message(user_id, text)
            mark_reminder_sent(b_id, 0.5)
            log.info(f"✅ Напоминание (30мин) отправлено для записи #{b_id}")
        except Exception:
            log.exception(f"❌ Ошибка отправки напоминания за 30 мин")


async def reminder_loop(bot: Bot) -> None:
    """Бесконечный цикл проверки напоминаний."""
    log.info(f"🔔 Запуск цикла напоминаний (интервал {BACKGROUND_CHECK_INTERVAL}с)")

    while True:
        try:
            await run_reminder_cycle(bot)
        except Exception:
            log.exception("❌ Критическая ошибка в reminder_loop")

        await asyncio.sleep(BACKGROUND_CHECK_INTERVAL)


# ============================================================================
# Cleanup System
# ============================================================================
async def cleanup_loop(bot: Bot) -> None:
    """Комплексная очистка просроченных данных."""
    log.info(f"🧹 Запуск цикла очистки (интервал {CLEANUP_INTERVAL_SECONDS}с)")

    await asyncio.sleep(60)  # Первый запуск через минуту

    while True:
        try:
            if ENABLE_AUTO_CLEANUP:
                stats = cleanup_all_expired_data()

                total_cleaned = sum(stats.values())
                if total_cleaned > 0:
                    log.info(
                        f"🧹 Очистка: слоты={stats['expired_slots']}, "
                        f"неявки={stats['expired_bookings']}, "
                        f"старые={stats['old_completed']}"
                    )

                    # Уведомляем админов о неявках
                    if stats['expired_bookings'] > 0:
                        msg = (
                            f"⚠️ <b>Обнаружены неявки</b>\n\n"
                            f"Удалено <b>{stats['expired_bookings']}</b> просроченных записей\n"
                            f"(клиенты не пришли на запись)"
                        )

                        for admin_id in ADMIN_IDS:
                            try:
                                await bot.send_message(admin_id, msg)
                            except Exception:
                                log.exception(f"❌ Не удалось уведомить админа {admin_id}")

                # VACUUM раз в неделю (понедельник в 3:00)
                now = datetime.now()
                if now.weekday() == 0 and 3 <= now.hour < 4:
                    try:
                        vacuum_database()
                        log.info("🧹 VACUUM выполнен успешно")

                        for admin_id in ADMIN_IDS:
                            try:
                                await bot.send_message(
                                    admin_id,
                                    "🧹 <b>База данных оптимизирована</b>\n(выполнена процедура VACUUM)"
                                )
                            except:
                                pass
                    except Exception:
                        log.exception("❌ Ошибка VACUUM")
        except Exception:
            log.exception("❌ Ошибка в cleanup_loop")

        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


# ============================================================================
# Completion Check System
# ============================================================================
async def completion_loop(bot: Bot) -> None:
    """Проверка завершения записей."""
    log.info(f"✅ Запуск цикла проверки завершения (интервал {COMPLETION_CHECK_INTERVAL}с)")

    sent_confirmations = set()

    while True:
        try:
            now_utc = datetime.now(dt_timezone.utc)
            due = get_bookings_ending_before(now_utc)

            for b in due:
                bid = b["id"]

                if bid in sent_confirmations:
                    continue

                master_name = b["master"]

                # Ищем telegram_id мастера
                tg_id = None
                for slot in get_all_master_slots():
                    if slot["name"] == master_name and slot.get("telegram_id"):
                        tg_id = slot["telegram_id"]
                        break

                msg = (
                    f"⏰ <b>Запись #{bid} завершилась</b>\n\n"
                    f"👨‍🦰 Мастер: <b>{master_name}</b>\n"
                    f"✂️ Услуга: <b>{b['haircut']}</b> — {b['price']}₽\n"
                    f"👤 Клиент: <b>{b['full_name']}</b>\n"
                    f"📱 Телефон: {b['phone']}\n\n"
                    f"Подтвердите выполнение:"
                )

                targets = [tg_id] if tg_id else ADMIN_IDS

                for target in targets:
                    if not target:
                        continue

                    try:
                        await bot.send_message(
                            target,
                            msg,
                            reply_markup=completion_kb(bid)
                        )
                        sent_confirmations.add(bid)
                        log.info(f"📨 Запрос подтверждения записи #{bid} → {target}")
                    except Exception:
                        log.exception(f"❌ Не удалось отправить подтверждение → {target}")
        except Exception:
            log.exception("❌ Ошибка в completion_loop")

        await asyncio.sleep(COMPLETION_CHECK_INTERVAL)


# ============================================================================
# Statistics Reporter
# ============================================================================
async def stats_reporter_loop(bot: Bot) -> None:
    """Отправляет статистику админам раз в день."""
    log.info("📊 Запуск цикла отправки статистики")

    last_send_hour = -1

    while True:
        try:
            now = datetime.now()

            # Отправляем в 9:00 каждый день
            if now.hour == 9 and last_send_hour != 9:
                last_send_hour = 9

                stats = get_database_stats()

                msg = (
                    f"📊 <b>Ежедневная статистика</b>\n"
                    f"Дата: {now.strftime('%d.%m.%Y')}\n\n"
                    f"👥 Пользователей: <b>{stats['users']}</b>\n"
                    f"📅 Свободных слотов: <b>{stats['masters_slots']}</b>\n"
                    f"⏳ Активных записей: <b>{stats['active_bookings']}</b>\n"
                    f"✅ Завершённых записей: <b>{stats['completed_bookings']}</b>\n"
                    f"💬 Необработанных обращений: <b>{stats['pending_support']}</b>"
                )

                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(admin_id, msg)
                    except Exception:
                        log.exception(f"❌ Не удалось отправить статистику → {admin_id}")

                log.info("📊 Статистика отправлена админам")

            # Сбрасываем флаг в полночь
            if now.hour != 9:
                last_send_hour = -1

        except Exception:
            log.exception("❌ Ошибка в stats_reporter_loop")

        await asyncio.sleep(60)


# ============================================================================
# Main Function
# ============================================================================
async def main() -> None:
    """Главная функция запуска бота."""
    log.info("=" * 70)
    log.info("🚀 Запуск Barbershop Bot...")
    log.info("=" * 70)

    tasks = []

    try:
        # Инициализация БД
        log.info("💾 Инициализация базы данных...")
        init_db()
        ensure_support_parent_column()

        # Стартовая очистка
        log.info("🧹 Стартовая очистка просроченных слотов...")
        removed = remove_expired_master_slots()
        if removed:
            log.info(f"🧹 Удалено {removed} просроченных слотов")

        # Статистика БД
        stats = get_database_stats()
        log.info(
            f"📊 Статистика БД: "
            f"пользователей={stats['users']}, "
            f"слотов={stats['masters_slots']}, "
            f"активных={stats['active_bookings']}, "
            f"завершённых={stats['completed_bookings']}"
        )

        # Создание бота
        log.info("🤖 Создание экземпляра бота...")
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

        # Проверка бота
        bot_info = await bot.get_me()
        log.info(f"✅ Бот запущен: @{bot_info.username} (ID: {bot_info.id})")

        # Dispatcher
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        dp.include_router(router)

        # Фоновые задачи
        log.info("⚙️ Запуск фоновых задач...")
        tasks = [
            asyncio.create_task(reminder_loop(bot), name="reminder_loop"),
            asyncio.create_task(cleanup_loop(bot), name="cleanup_loop"),
            asyncio.create_task(completion_loop(bot), name="completion_loop"),
            asyncio.create_task(stats_reporter_loop(bot), name="stats_reporter"),
        ]

        log.info("=" * 70)
        log.info("✅ Все системы запущены. Бот работает!")
        log.info("=" * 70)

        # Уведомляем админов о запуске
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"✅ <b>Бот успешно запущен!</b>\n\n"
                    f"🤖 @{bot_info.username}\n"
                    f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                    f"📊 <b>Статистика:</b>\n"
                    f"  👥 Пользователей: {stats['users']}\n"
                    f"  📅 Свободных слотов: {stats['masters_slots']}\n"
                    f"  ⏳ Активных записей: {stats['active_bookings']}\n"
                    f"  ✅ Завершённых записей: {stats['completed_bookings']}"
                )
            except Exception:
                log.exception(f"❌ Не удалось уведомить админа {admin_id}")

        # Запуск polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    except KeyboardInterrupt:
        log.info("⚠️ Получен сигнал остановки (Ctrl+C)")
    except Exception as exc:
        log.exception(f"❌ Критическая ошибка при запуске: {exc}")
        raise
    finally:
        log.info("🛑 Остановка бота...")

        # Останавливаем фоновые задачи
        for task in tasks:
            if not task.done():
                task.cancel()
                log.info(f"🛑 Остановка задачи: {task.get_name()}")

        # Ждём завершения всех задач
        await asyncio.gather(*tasks, return_exceptions=True)

        # Закрываем сессию бота
        try:
            await bot.session.close()
        except:
            pass

        log.info("=" * 70)
        log.info("👋 Бот успешно остановлен. До встречи!")
        log.info("=" * 70)


# ============================================================================
# Entry Point
# ============================================================================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception:
        log.exception("❌ Необработанная ошибка")
        sys.exit(1)
