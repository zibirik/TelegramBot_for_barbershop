# db.py – robust SQLite DB layer for Barbershop bot

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Tuple

from config import (
    DB_PATH,
    TIMEZONE,
    HAIRCUT_DURATIONS,
    HAIRCUT_TYPES,
)

log = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo(TIMEZONE) if TIMEZONE else dt_timezone.utc
    log.info("db: Using stdlib.zoneinfo TZ='%s'", TIMEZONE or "UTC")
except Exception as exc:
    log.warning("db: Не удалось импортировать zoneinfo (%s). Будет использован UTC.", exc)
    LOCAL_TZ = dt_timezone.utc

def get_conn() -> sqlite3.Connection:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.close()
    except Exception:
        log.exception("db: Не удалось задать PRAGMA-настройки")
    return conn

def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        phone TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS masters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        telegram_id INTEGER,
        available_date TEXT NOT NULL,
        available_time TEXT NOT NULL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        phone TEXT,
        haircut TEXT,
        price INTEGER,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        master TEXT NOT NULL,
        duration_minutes INTEGER DEFAULT 60,
        created_at TEXT NOT NULL,
        remind_24_sent INTEGER DEFAULT 0,
        remind_1_sent INTEGER DEFAULT 0,
        completed INTEGER DEFAULT 0,
        actual_paid INTEGER,
        completed_at TEXT,
        completed_by INTEGER,
        FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE SET NULL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        phone TEXT,
        text TEXT,
        created_at TEXT,
        handled INTEGER DEFAULT 0,
        admin_id INTEGER,
        admin_reply TEXT,
        parent_id INTEGER
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_masters_date_time ON masters(available_date, available_time);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_master_date_time ON bookings(master, date, time);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_support_handled ON support_messages(handled);")
    conn.commit()
    cur.close()
    conn.close()
    _ensure_columns()

def _ensure_columns() -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(bookings)")
        cols = {row["name"] for row in cur.fetchall()}
        with conn:
            if "duration_minutes" not in cols:
                cur.execute("ALTER TABLE bookings ADD COLUMN duration_minutes INTEGER DEFAULT 60")
            if "completed" not in cols:
                cur.execute("ALTER TABLE bookings ADD COLUMN completed INTEGER DEFAULT 0")
            if "actual_paid" not in cols:
                cur.execute("ALTER TABLE bookings ADD COLUMN actual_paid INTEGER")
            if "completed_at" not in cols:
                cur.execute("ALTER TABLE bookings ADD COLUMN completed_at TEXT")
            if "completed_by" not in cols:
                cur.execute("ALTER TABLE bookings ADD COLUMN completed_by INTEGER")
        cur.execute("PRAGMA table_info(masters)")
        mcols = {row["name"] for row in cur.fetchall()}
        with conn:
            if "telegram_id" not in mcols:
                cur.execute("ALTER TABLE masters ADD COLUMN telegram_id INTEGER")
    finally:
        cur.close()
        conn.close()

def ensure_support_parent_column() -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(support_messages)")
        cols = {row["name"] for row in cur.fetchall()}
        if "parent_id" not in cols:
            with conn:
                cur.execute("ALTER TABLE support_messages ADD COLUMN parent_id INTEGER")
            log.info("db: added parent_id column to support_messages")
    finally:
        cur.close()
        conn.close()

def add_user(user_id: int, full_name: str, phone: str) -> None:
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, full_name, phone) VALUES (?, ?, ?)",
                (user_id, full_name, phone),
            )
    finally:
        conn.close()

def get_user(user_id: int) -> Optional[Tuple[str, str]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT full_name, phone FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return (row["full_name"], row["phone"]) if row else None
    finally:
        cur.close()
        conn.close()

def update_master_schedule(
    name: str,
    start_date: str,
    end_date: str,
    start_time: str,
    end_time: str,
    step_minutes: int = 60,
    telegram_id: Optional[int] = None,
) -> None:
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
        st = datetime.strptime(start_time, "%H:%M")
        et = datetime.strptime(end_time, "%H:%M")
    except Exception as exc:
        raise ValueError("Invalid date/time format for master schedule") from exc
    conn = get_conn()
    cur = conn.cursor()
    try:
        with conn:
            cur_date = sd
            while cur_date <= ed:
                cur_time = st
                while cur_time < et:
                    cur.execute(
                        """
                        INSERT INTO masters (name, telegram_id, available_date, available_time)
                        VALUES (?, ?, ?, ?)
                        """,
                        (name, telegram_id, cur_date.strftime("%Y-%m-%d"), cur_time.strftime("%H:%M")),
                    )
                    cur_time = cur_time + timedelta(minutes=step_minutes)
                cur_date = cur_date + timedelta(days=1)
    finally:
        cur.close()
        conn.close()

def get_all_master_slots() -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, name, telegram_id, available_date, available_time
            FROM masters
            ORDER BY available_date, available_time
        """)
        return [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def set_master_telegram(master_name: str, telegram_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    try:
        with conn:
            cur.execute(
                "UPDATE masters SET telegram_id = ? WHERE name = ?",
                (telegram_id, master_name),
            )
            return cur.rowcount
    finally:
        cur.close()
        conn.close()

def get_available_dates(master_name: Optional[str] = None) -> List[str]:
    conn = get_conn()
    cur = conn.cursor()
    try:
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
                )
                ORDER BY m.available_date
            """)
        return [row["available_date"] for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def get_available_times(date: str, master_name: Optional[str] = None) -> List[str]:
    conn = get_conn()
    cur = conn.cursor()
    try:
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
                )
                ORDER BY m.available_time
            """, (date,))
        return [row["available_time"] for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def get_available_masters(date: str, time: str) -> List[str]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT m.name
            FROM masters m
            WHERE m.available_date = ?
            AND m.available_time = ?
            AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.master = m.name
                AND b.date = m.available_date
                AND b.time = m.available_time
            )
            ORDER BY m.name
        """, (date, time))
        return [row["name"] for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def remove_master_slot(name: str, date: str, time: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        with conn:
            cur.execute("""
                DELETE FROM masters
                WHERE id = (
                    SELECT id FROM masters
                    WHERE name = ? AND available_date = ? AND available_time = ?
                    LIMIT 1
                )
            """, (name, date, time))
    finally:
        cur.close()
        conn.close()

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
    if duration_minutes is None:
        duration_minutes = HAIRCUT_DURATIONS.get(haircut, 60)
    conn = get_conn()
    cur = conn.cursor()
    created_at = datetime.now(dt_timezone.utc).isoformat()
    try:
        with conn:
            cur.execute("""
                SELECT id FROM masters
                WHERE name = ? AND available_date = ? AND available_time = ? LIMIT 1
            """, (master, date, time))
            slot = cur.fetchone()
            if not slot:
                raise ValueError("Выбранный слот не существует")
            cur.execute("""
                SELECT id FROM bookings
                WHERE master = ? AND date = ? AND time = ? LIMIT 1
            """, (master, date, time))
            if cur.fetchone():
                raise ValueError("Слот уже занят")
            cur.execute("""
                INSERT INTO bookings
                (user_id, username, full_name, phone, haircut, price,
                date, time, master, duration_minutes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                username,
                full_name,
                phone,
                haircut,
                price,
                date,
                time,
                master,
                duration_minutes,
                created_at,
            ))
            booking_id = cur.lastrowid
            cur.execute("DELETE FROM masters WHERE id = ?", (slot["id"],))
            return booking_id
    finally:
        cur.close()
        conn.close()

def check_booking(master: str, date: str, time: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM bookings WHERE master=? AND date=? AND time=? LIMIT 1",
            (master, date, time),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()
        conn.close()

def get_user_bookings(user_id: int) -> List[Tuple]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, haircut, price, date, time, master
            FROM bookings
            WHERE user_id = ? AND completed = 0
            ORDER BY date, time
        """, (user_id,))
        return [tuple(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def get_booking_by_id(booking_id: int) -> Optional[Tuple]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, user_id, username, full_name, phone, haircut, price,
            date, time, master, duration_minutes,
            remind_24_sent, remind_1_sent, completed,
            actual_paid, completed_at, completed_by
            FROM bookings
            WHERE id = ?
        """, (booking_id,))
        row = cur.fetchone()
        return tuple(row) if row else None
    finally:
        cur.close()
        conn.close()

def cancel_booking(booking_id: int, force: bool = False) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        with conn:
            cur.execute("""
                SELECT id, user_id, username, full_name, phone,
                haircut, price, date, time, master
                FROM bookings
                WHERE id = ? LIMIT 1
            """, (booking_id,))
            b = cur.fetchone()
            if not b:
                return False
            cur.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
            cur.execute("""
                INSERT INTO masters (name, available_date, available_time)
                VALUES (?, ?, ?)
            """, (b["master"], b["date"], b["time"]))
            return True
    finally:
        cur.close()
        conn.close()

def get_all_bookings_for_admin() -> List[Tuple]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, username, full_name, phone, haircut, price,
            date, time, master, duration_minutes,
            completed, actual_paid
            FROM bookings
            ORDER BY date, time
        """)
        return [tuple(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def get_all_bookings_due_between(
    start_dt: datetime, end_dt: datetime
) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, user_id, username, full_name, phone,
            haircut, price, date, time, master,
            duration_minutes, remind_24_sent, remind_1_sent
            FROM bookings
            WHERE completed = 0
        """)
        rows = cur.fetchall()
        result: List[Dict[str, Any]] = []
        for r in rows:
            try:
                local_naive = datetime.strptime(
                    f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M"
                )
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
                    "duration_minutes": dur,
                    "master": r["master"],
                    "remind_24_sent": bool(r["remind_24_sent"]),
                    "remind_1_sent": bool(r["remind_1_sent"]),
                })
        return result
    finally:
        cur.close()
        conn.close()

def get_bookings_ending_before(cutoff_utc: datetime) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
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
                start_naive = datetime.strptime(
                    f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M"
                )
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
    finally:
        cur.close()
        conn.close()

def mark_booking_completed(
    booking_id: int,
    actual_paid: Optional[int],
    completed_by: Optional[int] = None,
    succeeded: bool = True,
) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        completed_at = datetime.now(dt_timezone.utc).isoformat()
        with conn:
            cur.execute("""
                UPDATE bookings
                SET completed = 1,
                    actual_paid = ?,
                    completed_at = ?,
                    completed_by = ?
                WHERE id = ?
            """, (actual_paid, completed_at, completed_by, booking_id))
            return True
    finally:
        cur.close()
        conn.close()

def get_completed_bookings(
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    try:
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
    finally:
        cur.close()
        conn.close()

def mark_reminder_sent(booking_id: int, hours: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        with conn:
            if hours == 24:
                cur.execute("UPDATE bookings SET remind_24_sent = 1 WHERE id = ?", (booking_id,))
            elif hours == 1:
                cur.execute("UPDATE bookings SET remind_1_sent = 1 WHERE id = ?", (booking_id,))
    finally:
        cur.close()
        conn.close()

def add_support_message(
    user_id: int,
    username: str,
    full_name: str,
    phone: str,
    text: str,
    parent_id: Optional[int] = None,
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    created_at = datetime.now(dt_timezone.utc).isoformat()
    try:
        with conn:
            cur.execute("""
                INSERT INTO support_messages
                (user_id, username, full_name, phone, text, created_at, parent_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, username, full_name, phone, text, created_at, parent_id))
            return cur.lastrowid
    finally:
        cur.close()
        conn.close()

def get_pending_supports() -> List[Tuple]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, user_id, username, full_name, phone, text, created_at
            FROM support_messages
            WHERE handled = 0
            ORDER BY created_at
        """)
        return [tuple(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

def get_support_by_id(support_id: int) -> Optional[Tuple]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, user_id, username, full_name, phone, text,
                   created_at, handled, admin_id, admin_reply, parent_id
            FROM support_messages
            WHERE id = ?
        """, (support_id,))
        row = cur.fetchone()
        return tuple(row) if row else None
    finally:
        cur.close()
        conn.close()

def mark_support_handled(
    support_id: int,
    admin_id: Optional[int] = None,
    admin_reply: Optional[str] = None,
) -> None:
    conn = get_conn()
    cur = conn.cursor()
    try:
        with conn:
            cur.execute("""
                UPDATE support_messages
                SET handled = 1,
                    admin_id = ?,
                    admin_reply = ?
                WHERE id = ?
            """, (admin_id, admin_reply, support_id))
    finally:
        cur.close()
        conn.close()

def remove_expired_master_slots(cutoff_dt: Optional[datetime] = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    removed = 0
    try:
        now_local = (
            datetime.now(LOCAL_TZ) if cutoff_dt is None else cutoff_dt.astimezone(LOCAL_TZ)
        )
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
            with conn:
                cur.execute(f"DELETE FROM masters WHERE id IN ({placeholders})", to_del)
            removed = len(to_del)
    finally:
        cur.close()
        conn.close()
    log.info("remove_expired_master_slots: removed %d expired slots", removed)
    return removed
