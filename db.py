# db.py – Production-ready SQLite DB layer for Barbershop Bot
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from config import DB_PATH, TIMEZONE, HAIRCUT_DURATIONS

# ============================================================================
# Logging & Timezone Setup
# ============================================================================
log = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo(TIMEZONE) if TIMEZONE else dt_timezone.utc
    log.info("db: Using stdlib.zoneinfo TZ='%s'", TIMEZONE or "UTC")
except Exception as exc:
    log.warning("db: Не удалось импортировать zoneinfo (%s). Используем UTC.", exc)
    LOCAL_TZ = dt_timezone.utc

# ============================================================================
# Connection Pool (простой thread-safe пул)
# ============================================================================
_connection_lock = Lock()


@contextmanager
def get_conn():
    """Context manager для безопасного получения соединения с БД."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with _connection_lock:
        conn = sqlite3.connect(
            DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        try:
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA foreign_keys=ON;")
            cur.execute("PRAGMA cache_size=-64000;")
            cur.execute("PRAGMA temp_store=MEMORY;")
            cur.close()
        except Exception:
            log.exception("db: Не удалось задать PRAGMA-настройки")

        try:
            yield conn
        finally:
            conn.close()


# ============================================================================
# Schema Initialization
# ============================================================================
def init_db() -> None:
    """Инициализация БД с улучшенной схемой и индексами."""
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS masters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                telegram_id INTEGER,
                available_date TEXT NOT NULL,
                available_time TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(name, available_date, available_time)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                haircut TEXT NOT NULL,
                price INTEGER NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                master TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 60,
                created_at TEXT NOT NULL,
                remind_24_sent INTEGER NOT NULL DEFAULT 0,
                remind_1_sent INTEGER NOT NULL DEFAULT 0,
                remind_30_sent INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                actual_paid INTEGER,
                completed_at TEXT,
                completed_by INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT NOT NULL,
                phone TEXT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                handled INTEGER NOT NULL DEFAULT 0,
                admin_id INTEGER,
                admin_reply TEXT,
                parent_id INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(parent_id) REFERENCES support_messages(id) ON DELETE SET NULL
            )
        """)

        # Индексы
        cur.execute("CREATE INDEX IF NOT EXISTS idx_masters_date_time ON masters(available_date, available_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_masters_name ON masters(name)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_masters_telegram ON masters(telegram_id) WHERE telegram_id IS NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_master_date_time ON bookings(master, date, time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id) WHERE user_id IS NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_completed ON bookings(completed)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date_time ON bookings(date, time)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_bookings_reminders ON bookings(remind_24_sent, remind_1_sent, remind_30_sent) WHERE completed = 0")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_support_handled ON support_messages(handled)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_support_user ON support_messages(user_id)")

        conn.commit()

    _ensure_columns()
    log.info("db: Инициализация завершена успешно")


def _ensure_columns() -> None:
    """Добавляет недостающие колонки для обратной совместимости."""
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(bookings)")
        cols = {row["name"] for row in cur.fetchall()}

        migrations = [
            ("duration_minutes", "ALTER TABLE bookings ADD COLUMN duration_minutes INTEGER DEFAULT 60"),
            ("completed", "ALTER TABLE bookings ADD COLUMN completed INTEGER DEFAULT 0"),
            ("actual_paid", "ALTER TABLE bookings ADD COLUMN actual_paid INTEGER"),
            ("completed_at", "ALTER TABLE bookings ADD COLUMN completed_at TEXT"),
            ("completed_by", "ALTER TABLE bookings ADD COLUMN completed_by INTEGER"),
            ("remind_30_sent", "ALTER TABLE bookings ADD COLUMN remind_30_sent INTEGER DEFAULT 0"),
        ]

        for col_name, sql in migrations:
            if col_name not in cols:
                cur.execute(sql)
                log.info(f"db: Добавлена колонка bookings.{col_name}")

        cur.execute("PRAGMA table_info(masters)")
        mcols = {row["name"] for row in cur.fetchall()}

        if "telegram_id" not in mcols:
            cur.execute("ALTER TABLE masters ADD COLUMN telegram_id INTEGER")
            log.info("db: Добавлена колонка masters.telegram_id")

        cur.execute("PRAGMA table_info(support_messages)")
        scols = {row["name"] for row in cur.fetchall()}

        if "parent_id" not in scols:
            cur.execute("ALTER TABLE support_messages ADD COLUMN parent_id INTEGER")
            log.info("db: Добавлена колонка support_messages.parent_id")

        conn.commit()


def ensure_support_parent_column() -> None:
    """Обратная совместимость."""
    _ensure_columns()


# ============================================================================
# User Management
# ============================================================================
def add_user(user_id: int, full_name: str, phone: str) -> None:
    """Добавляет или обновляет пользователя."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, full_name, phone, created_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                full_name = excluded.full_name,
                phone = excluded.phone,
                updated_at = datetime('now')
            """,
            (user_id, full_name, phone),
        )
        conn.commit()


def get_user(user_id: int) -> Optional[Tuple[str, str]]:
    """Получает данные пользователя (full_name, phone)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT full_name, phone FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return (row["full_name"], row["phone"]) if row else None


# ============================================================================
# Master Schedule Management
# ============================================================================
def update_master_schedule(
        name: str,
        start_date: str,
        end_date: str,
        start_time: str,
        end_time: str,
        step_minutes: int = 60,
        telegram_id: Optional[int] = None,
) -> None:
    """Создаёт расписание для мастера на указанный период."""
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        st = datetime.strptime(start_time, "%H:%M")
        et = datetime.strptime(end_time, "%H:%M")
    except Exception as exc:
        raise ValueError("Invalid date/time format for master schedule") from exc

    if ed < sd:
        raise ValueError("Конечная дата не может быть раньше начальной")
    if et <= st:
        raise ValueError("Конечное время не может быть раньше или равно начальному")
    if step_minutes <= 0:
        raise ValueError("Шаг должен быть положительным числом")

    slots = []
    cur_date = sd

    while cur_date <= ed:
        cur_time = st
        while cur_time < et:
            slots.append((
                name,
                telegram_id,
                cur_date.strftime("%Y-%m-%d"),
                cur_time.strftime("%H:%M"),
            ))
            cur_time = (datetime.combine(cur_date, cur_time.time()) + timedelta(minutes=step_minutes)).time()
            cur_time = datetime.combine(cur_date, cur_time)
        cur_date += timedelta(days=1)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT OR IGNORE INTO masters (name, telegram_id, available_date, available_time)
            VALUES (?, ?, ?, ?)
            """,
            slots,
        )
        conn.commit()
        log.info(f"db: Добавлено {len(slots)} слотов для мастера '{name}'")


def get_all_master_slots() -> List[Dict[str, Any]]:
    """Возвращает все слоты мастеров."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, telegram_id, available_date, available_time
            FROM masters
            ORDER BY available_date, available_time, name
        """)
        return [dict(row) for row in cur.fetchall()]


def set_master_telegram(master_name: str, telegram_id: int) -> int:
    """Привязывает telegram_id к мастеру."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE masters SET telegram_id = ? WHERE name = ?",
            (telegram_id, master_name),
        )
        conn.commit()
        return cur.rowcount


# ============================================================================
# Availability Queries
# ============================================================================
def get_available_dates(master_name: Optional[str] = None) -> List[str]:
    """Получает доступные даты."""
    with get_conn() as conn:
        cur = conn.cursor()

        if master_name:
            cur.execute("""
                SELECT DISTINCT m.available_date
                FROM masters m
                WHERE m.name = ?
                AND NOT EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.master = m.name
                    AND b.date = m.available_date
                    AND b.time = m.available_time
                    AND b.completed = 0
                )
                ORDER BY m.available_date
            """, (master_name,))
        else:
            cur.execute("""
                SELECT DISTINCT m.available_date
                FROM masters m
                WHERE NOT EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.master = m.name
                    AND b.date = m.available_date
                    AND b.time = m.available_time
                    AND b.completed = 0
                )
                ORDER BY m.available_date
            """)

        return [row["available_date"] for row in cur.fetchall()]


def get_available_times(date: str, master_name: Optional[str] = None) -> List[str]:
    """Получает доступные времена на указанную дату."""
    with get_conn() as conn:
        cur = conn.cursor()

        if master_name:
            cur.execute("""
                SELECT m.available_time
                FROM masters m
                WHERE m.available_date = ?
                AND m.name = ?
                AND NOT EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.master = m.name
                    AND b.date = m.available_date
                    AND b.time = m.available_time
                    AND b.completed = 0
                )
                ORDER BY m.available_time
            """, (date, master_name))
        else:
            cur.execute("""
                SELECT DISTINCT m.available_time
                FROM masters m
                WHERE m.available_date = ?
                AND NOT EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.master = m.name
                    AND b.date = m.available_date
                    AND b.time = m.available_time
                    AND b.completed = 0
                )
                ORDER BY m.available_time
            """, (date,))

        return [row["available_time"] for row in cur.fetchall()]


def get_available_masters(date: str, time: str) -> List[str]:
    """Получает доступных мастеров на указанные дату и время."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT m.name
            FROM masters m
            WHERE m.available_date = ?
            AND m.available_time = ?
            AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.master = m.name
                AND b.date = m.available_date
                AND b.time = m.available_time
                AND b.completed = 0
            )
            ORDER BY m.name
        """, (date, time))

        return [row["name"] for row in cur.fetchall()]


# ============================================================================
# Booking Management
# ============================================================================
def add_booking(
        user_id: int,
        username: str,
        full_name: str,
        phone: str,
        haircut: str,
        price: int,
        date: str,
        time: str,
        master: str,
        duration_minutes: Optional[int] = None,
) -> int:
    """Создаёт новую запись."""
    if duration_minutes is None:
        duration_minutes = HAIRCUT_DURATIONS.get(haircut, 60)

    # Проверка прошедшего времени
    try:
        booking_naive = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        booking_local = booking_naive.replace(tzinfo=LOCAL_TZ)
        booking_utc = booking_local.astimezone(dt_timezone.utc)
        now_utc = datetime.now(dt_timezone.utc)

        if booking_utc < now_utc:
            raise ValueError("❌ Нельзя создать запись на прошедшее время")
    except ValueError as e:
        if "Нельзя создать" in str(e):
            raise
        raise ValueError("❌ Неверный формат даты или времени")

    created_at = datetime.now(dt_timezone.utc).isoformat()

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT id FROM masters
            WHERE name = ? AND available_date = ? AND available_time = ?
            LIMIT 1
        """, (master, date, time))
        slot = cur.fetchone()

        if not slot:
            raise ValueError("❌ Выбранный слот не существует или уже удалён")

        cur.execute("""
            SELECT id FROM bookings
            WHERE master = ? AND date = ? AND time = ? AND completed = 0
            LIMIT 1
        """, (master, date, time))

        if cur.fetchone():
            raise ValueError("❌ Слот уже занят другим клиентом")

        cur.execute("""
            INSERT INTO bookings
            (user_id, username, full_name, phone, haircut, price,
             date, time, master, duration_minutes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, username, full_name, phone, haircut, price,
            date, time, master, duration_minutes, created_at,
        ))
        booking_id = cur.lastrowid

        cur.execute("DELETE FROM masters WHERE id = ?", (slot["id"],))

        conn.commit()
        log.info(f"db: Создана запись #{booking_id} для {full_name} на {date} {time}")
        return booking_id


def check_booking(master: str, date: str, time: str) -> bool:
    """Проверяет, занят ли слот."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM bookings
            WHERE master = ? AND date = ? AND time = ? AND completed = 0
            LIMIT 1
            """,
            (master, date, time),
        )
        return cur.fetchone() is not None


def get_user_bookings(user_id: int) -> List[Tuple]:
    """Получает активные записи пользователя."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, haircut, price, date, time, master
            FROM bookings
            WHERE user_id = ? AND completed = 0
            ORDER BY date, time
        """, (user_id,))
        return [tuple(row) for row in cur.fetchall()]


def get_booking_by_id(booking_id: int) -> Optional[Tuple]:
    """Получает детали записи по ID."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, full_name, phone, haircut, price,
                   date, time, master, duration_minutes,
                   remind_24_sent, remind_1_sent, remind_30_sent, completed,
                   actual_paid, completed_at, completed_by
            FROM bookings
            WHERE id = ?
        """, (booking_id,))
        row = cur.fetchone()
        return tuple(row) if row else None


def cancel_booking(booking_id: int, force: bool = False) -> bool:
    """Отменяет запись и возвращает слот в доступные."""
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, user_id, username, full_name, phone,
                   haircut, price, date, time, master
            FROM bookings
            WHERE id = ?
            LIMIT 1
        """, (booking_id,))
        b = cur.fetchone()

        if not b:
            return False

        # Получаем telegram_id мастера
        cur.execute("SELECT telegram_id FROM masters WHERE name = ? LIMIT 1", (b["master"],))
        master_row = cur.fetchone()
        tg_id = master_row["telegram_id"] if master_row else None

        # Удаляем запись
        cur.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))

        # Возвращаем слот если не прошёл
        try:
            slot_dt = datetime.strptime(f"{b['date']} {b['time']}", "%Y-%m-%d %H:%M")
            slot_local = slot_dt.replace(tzinfo=LOCAL_TZ)
            now_local = datetime.now(LOCAL_TZ)

            if slot_local >= now_local:
                cur.execute("""
                    INSERT OR IGNORE INTO masters (name, telegram_id, available_date, available_time)
                    VALUES (?, ?, ?, ?)
                """, (b["master"], tg_id, b["date"], b["time"]))
        except Exception:
            log.exception("db: Ошибка возврата слота #%s", booking_id)

        conn.commit()
        log.info(f"db: Отменена запись #{booking_id}")
        return True


def get_all_bookings_for_admin() -> List[Tuple]:
    """Получает все записи для админ-панели."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, username, full_name, phone, haircut, price,
                   date, time, master, duration_minutes,
                   completed, actual_paid
            FROM bookings
            ORDER BY date DESC, time DESC
        """)
        return [tuple(row) for row in cur.fetchall()]


# ============================================================================
# Reminder System
# ============================================================================
def get_all_bookings_due_between(
        start_dt: datetime, end_dt: datetime
) -> List[Dict[str, Any]]:
    """Получает записи в указанном временном окне."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, full_name, phone,
                   haircut, price, date, time, master,
                   duration_minutes, remind_24_sent, remind_1_sent, remind_30_sent
            FROM bookings
            WHERE completed = 0
        """)
        rows = cur.fetchall()

    result: List[Dict[str, Any]] = []

    for r in rows:
        try:
            local_naive = datetime.strptime(f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M")
            local_dt = local_naive.replace(tzinfo=LOCAL_TZ)
            utc_dt = local_dt.astimezone(dt_timezone.utc)
        except Exception:
            log.warning("db: malformed datetime for booking id=%s – skip", r["id"])
            continue

        if start_dt <= utc_dt <= end_dt:
            dur = int(r["duration_minutes"] or 60)
            result.append({
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "full_name": r["full_name"],
                "phone": r["phone"],
                "haircut": r["haircut"],
                "price": r["price"],
                "datetime": utc_dt,
                "date": r["date"],
                "time": r["time"],
                "duration_minutes": dur,
                "master": r["master"],
                "remind_24_sent": bool(r["remind_24_sent"]),
                "remind_1_sent": bool(r["remind_1_sent"]),
                "remind_30_sent": bool(r["remind_30_sent"]),
            })

    return result


def mark_reminder_sent(booking_id: int, hours: float) -> None:
    """Отмечает отправленное напоминание."""
    with get_conn() as conn:
        cur = conn.cursor()

        if hours == 24:
            cur.execute("UPDATE bookings SET remind_24_sent = 1 WHERE id = ?", (booking_id,))
        elif hours == 1:
            cur.execute("UPDATE bookings SET remind_1_sent = 1 WHERE id = ?", (booking_id,))
        elif hours == 0.5:
            cur.execute("UPDATE bookings SET remind_30_sent = 1 WHERE id = ?", (booking_id,))

        conn.commit()


# ============================================================================
# Completion System
# ============================================================================
def get_bookings_ending_before(cutoff_utc: datetime) -> List[Dict[str, Any]]:
    """Получает записи, которые должны были завершиться."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, full_name, phone,
                   haircut, price, date, time, master, duration_minutes
            FROM bookings
            WHERE completed = 0
        """)
        rows = cur.fetchall()

    out: List[Dict[str, Any]] = []

    for r in rows:
        try:
            start_naive = datetime.strptime(f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M")
            start_local = start_naive.replace(tzinfo=LOCAL_TZ)
            start_utc = start_local.astimezone(dt_timezone.utc)
        except Exception:
            continue

        dur = int(r["duration_minutes"] or 60)
        end_utc = start_utc + timedelta(minutes=dur)

        if end_utc <= cutoff_utc:
            out.append({
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "full_name": r["full_name"],
                "phone": r["phone"],
                "haircut": r["haircut"],
                "price": r["price"],
                "start_utc": start_utc,
                "end_utc": end_utc,
                "duration_minutes": dur,
                "master": r["master"],
            })

    return out


def mark_booking_completed(
        booking_id: int,
        actual_paid: Optional[int],
        completed_by: Optional[int] = None,
        succeeded: bool = True,
) -> bool:
    """Отмечает запись как завершённую."""
    completed_at = datetime.now(dt_timezone.utc).isoformat()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE bookings
            SET completed = 1,
                actual_paid = ?,
                completed_at = ?,
                completed_by = ?
            WHERE id = ?
        """, (actual_paid, completed_at, completed_by, booking_id))
        conn.commit()

        if cur.rowcount > 0:
            log.info(f"db: Запись #{booking_id} отмечена как завершённая")
            return True
        return False


def get_completed_bookings(
        start_dt: Optional[datetime] = None,
        end_dt: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Получает завершённые записи."""
    with get_conn() as conn:
        cur = conn.cursor()

        sql = """
            SELECT id, user_id, username, full_name, phone,
                   haircut, price, date, time, master,
                   duration_minutes, actual_paid, completed_at
            FROM bookings
            WHERE completed = 1
        """
        params: List[Any] = []

        if start_dt and end_dt:
            sql += " AND datetime(completed_at) BETWEEN datetime(?) AND datetime(?)"
            params.extend([start_dt.isoformat(), end_dt.isoformat()])

        sql += " ORDER BY completed_at DESC"

        cur.execute(sql, params)
        rows = cur.fetchall()

        return [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "full_name": r["full_name"],
                "phone": r["phone"],
                "haircut": r["haircut"],
                "price": r["price"],
                "date": r["date"],
                "time": r["time"],
                "master": r["master"],
                "duration_minutes": r["duration_minutes"],
                "actual_paid": r["actual_paid"],
                "completed_at": r["completed_at"],
            }
            for r in rows
        ]


# ============================================================================
# Support Messages
# ============================================================================
def add_support_message(
        user_id: int,
        username: str,
        full_name: str,
        phone: str,
        text: str,
        parent_id: Optional[int] = None,
) -> int:
    """Добавляет сообщение в техподдержку."""
    created_at = datetime.now(dt_timezone.utc).isoformat()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO support_messages
            (user_id, username, full_name, phone, text, created_at, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, full_name, phone, text, created_at, parent_id))
        conn.commit()
        return cur.lastrowid


def get_pending_supports() -> List[Tuple]:
    """Получает необработанные обращения."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, full_name, phone, text, created_at
            FROM support_messages
            WHERE handled = 0
            ORDER BY created_at
        """)
        return [tuple(row) for row in cur.fetchall()]


def get_support_by_id(support_id: int) -> Optional[Tuple]:
    """Получает обращение по ID."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, username, full_name, phone, text,
                   created_at, handled, admin_id, admin_reply, parent_id
            FROM support_messages
            WHERE id = ?
        """, (support_id,))
        row = cur.fetchone()
        return tuple(row) if row else None


def mark_support_handled(
        support_id: int,
        admin_id: Optional[int] = None,
        admin_reply: Optional[str] = None,
) -> None:
    """Отмечает обращение как обработанное."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE support_messages
            SET handled = 1,
                admin_id = ?,
                admin_reply = ?
            WHERE id = ?
        """, (admin_id, admin_reply, support_id))
        conn.commit()


# ============================================================================
# Cleanup Functions
# ============================================================================
def remove_expired_master_slots(cutoff_dt: Optional[datetime] = None) -> int:
    """Удаляет просроченные слоты мастеров."""
    now_local = (
        datetime.now(LOCAL_TZ) if cutoff_dt is None else cutoff_dt.astimezone(LOCAL_TZ)
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, available_date, available_time FROM masters")
        rows = cur.fetchall()

        to_del = []
        for r in rows:
            try:
                slot_naive = datetime.strptime(
                    f"{r['available_date']} {r['available_time']}",
                    "%Y-%m-%d %H:%M",
                )
                slot_local = slot_naive.replace(tzinfo=LOCAL_TZ)
            except Exception:
                to_del.append(r["id"])
                continue

            if slot_local < now_local:
                to_del.append(r["id"])

        if to_del:
            placeholders = ",".join("?" for _ in to_del)
            cur.execute(f"DELETE FROM masters WHERE id IN ({placeholders})", to_del)
            conn.commit()
            log.info("db: Удалено %d просроченных слотов", len(to_del))
            return len(to_del)

        return 0


def remove_old_completed_bookings(days: int = 30) -> int:
    """Удаляет старые завершённые записи."""
    cutoff_dt = datetime.now(dt_timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff_dt.isoformat()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM bookings
            WHERE completed = 1
            AND datetime(completed_at) < datetime(?)
        """, (cutoff_str,))
        conn.commit()
        deleted = cur.rowcount

        if deleted > 0:
            log.info(f"db: Удалено {deleted} старых завершённых записей (старше {days} дней)")

        return deleted


def remove_expired_bookings(grace_hours: int = 2) -> int:
    """Удаляет просроченные неявки."""
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, date, time, duration_minutes, master
            FROM bookings
            WHERE completed = 0
        """)
        rows = cur.fetchall()

        now_local = datetime.now(LOCAL_TZ)
        to_delete = []

        for r in rows:
            try:
                booking_naive = datetime.strptime(
                    f"{r['date']} {r['time']}",
                    "%Y-%m-%d %H:%M"
                )
                booking_local = booking_naive.replace(tzinfo=LOCAL_TZ)

                duration = int(r['duration_minutes'] or 60)
                end_time = booking_local + timedelta(minutes=duration, hours=grace_hours)

                if end_time < now_local:
                    to_delete.append(r['id'])
                    log.info(
                        f"db: Запись #{r['id']} просрочена и будет удалена "
                        f"(дата: {r['date']} {r['time']})"
                    )
            except Exception:
                log.exception(f"db: Ошибка обработки записи #{r['id']}")
                continue

        if to_delete:
            placeholders = ",".join("?" for _ in to_delete)
            cur.execute(
                f"DELETE FROM bookings WHERE id IN ({placeholders})",
                to_delete
            )
            conn.commit()
            log.info(f"db: Удалено {len(to_delete)} просроченных записей (неявки)")
            return len(to_delete)

        return 0


def cleanup_all_expired_data() -> Dict[str, int]:
    """Комплексная очистка всех просроченных данных."""
    stats = {
        'expired_slots': 0,
        'expired_bookings': 0,
        'old_completed': 0,
    }

    stats['expired_slots'] = remove_expired_master_slots()
    stats['expired_bookings'] = remove_expired_bookings(grace_hours=2)

    # Импортируем здесь, чтобы избежать циклических импортов
    try:
        from config import OLD_BOOKINGS_RETENTION_DAYS
        stats['old_completed'] = remove_old_completed_bookings(days=OLD_BOOKINGS_RETENTION_DAYS)
    except ImportError:
        stats['old_completed'] = remove_old_completed_bookings(days=90)

    total = sum(stats.values())
    if total > 0:
        log.info(
            f"db: Очистка завершена. Удалено: "
            f"слотов={stats['expired_slots']}, "
            f"неявок={stats['expired_bookings']}, "
            f"старых записей={stats['old_completed']}"
        )

    return stats


# ============================================================================
# Database Analytics
# ============================================================================
def get_database_stats() -> Dict[str, int]:
    """Получает статистику БД."""
    with get_conn() as conn:
        cur = conn.cursor()

        stats = {}
        stats["users"] = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        stats["masters_slots"] = cur.execute("SELECT COUNT(*) FROM masters").fetchone()[0]
        stats["active_bookings"] = cur.execute(
            "SELECT COUNT(*) FROM bookings WHERE completed = 0"
        ).fetchone()[0]
        stats["completed_bookings"] = cur.execute(
            "SELECT COUNT(*) FROM bookings WHERE completed = 1"
        ).fetchone()[0]
        stats["pending_support"] = cur.execute(
            "SELECT COUNT(*) FROM support_messages WHERE handled = 0"
        ).fetchone()[0]

        return stats


def vacuum_database() -> None:
    """Оптимизирует БД."""
    with get_conn() as conn:
        conn.execute("VACUUM")
        conn.commit()
        log.info("db: VACUUM выполнен успешно")


# ============================================================================
# Export.
# ============================================================================
__all__ = [
    "init_db",
    "ensure_support_parent_column",
    "add_user",
    "get_user",
    "update_master_schedule",
    "get_all_master_slots",
    "set_master_telegram",
    "get_available_dates",
    "get_available_times",
    "get_available_masters",
    "add_booking",
    "check_booking",
    "get_user_bookings",
    "get_booking_by_id",
    "cancel_booking",
    "get_all_bookings_for_admin",
    "get_all_bookings_due_between",
    "mark_reminder_sent",
    "get_bookings_ending_before",
    "mark_booking_completed",
    "get_completed_bookings",
    "add_support_message",
    "get_pending_supports",
    "get_support_by_id",
    "mark_support_handled",
    "remove_expired_master_slots",
    "remove_old_completed_bookings",
    "remove_expired_bookings",
    "cleanup_all_expired_data",
    "get_database_stats",
    "vacuum_database",
]
