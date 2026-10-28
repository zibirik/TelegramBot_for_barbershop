# db.py – Production-ready SQLite DB layer (v2-fixed for SQLite UNIQUE constraints)
# Fix: no expressions (e.g., COALESCE) inside table UNIQUE constraints.
# Compatible with: main.py / handlers.py from this thread

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

# --- config imports (safe) ---
from config import DB_PATH, TIMEZONE, HAIRCUT_DURATIONS

try:
    from config import OLD_BOOKINGS_RETENTION_DAYS
except Exception:
    OLD_BOOKINGS_RETENTION_DAYS = 90

try:
    from config import BOOKING_GRACE_HOURS
except Exception:
    BOOKING_GRACE_HOURS = 2

try:
    from config import ENABLE_MULTI_BRANCH, BRANCHES
except Exception:
    ENABLE_MULTI_BRANCH = False
    BRANCHES = {}

try:
    from config import ENABLE_PROMOCODES, PROMOCODE_DISCOUNTS, MAX_PROMOCODE_USES
except Exception:
    ENABLE_PROMOCODES = False
    PROMOCODE_DISCOUNTS = {}
    MAX_PROMOCODE_USES = 0

try:
    from config import ENABLE_ROLES, ENABLE_CLIENT_SEGMENTS
except Exception:
    ENABLE_ROLES = True
    ENABLE_CLIENT_SEGMENTS = True

log = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Timezone
# -----------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo(TIMEZONE) if TIMEZONE else dt_timezone.utc
except Exception:
    LOCAL_TZ = dt_timezone.utc


# -----------------------------------------------------------------------------
# SQLite connection handling
# -----------------------------------------------------------------------------
_connection_lock = Lock()


@contextmanager
def get_conn():
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
            cur.execute("PRAGMA temp_store=MEMORY;")
            cur.close()
        except Exception:
            log.exception("db: Failed to apply PRAGMA")

        try:
            yield conn
        finally:
            conn.close()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _utc_now() -> datetime:
    return datetime.now(dt_timezone.utc)


def _to_local_dt(date_str: str, time_str: str) -> datetime:
    naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=LOCAL_TZ)


def _to_utc(local_dt: datetime) -> datetime:
    return local_dt.astimezone(dt_timezone.utc)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = {row["name"] for row in cur.fetchall()}
    cur.close()
    return cols


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> bool:
    cols = _table_columns(conn, table)
    if col in cols:
        return False
    cur = conn.cursor()
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    cur.close()
    return True


# -----------------------------------------------------------------------------
# Init DB + migrations
# -----------------------------------------------------------------------------
def init_db() -> None:
    with get_conn() as conn:
        cur = conn.cursor()

        # USERS
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'client',
                client_segment TEXT NOT NULL DEFAULT 'new',
                total_bookings INTEGER NOT NULL DEFAULT 0,
                total_spent INTEGER NOT NULL DEFAULT 0,
                last_visit_date TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # BRANCHES (optional)
        if ENABLE_MULTI_BRANCH:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS branches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    address TEXT,
                    phone TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

        # MASTERS slots
        # IMPORTANT FIX: branch_code is NOT NULL DEFAULT '' so UNIQUE can be pure column list.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS masters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                telegram_id INTEGER,
                branch_code TEXT NOT NULL DEFAULT '',
                available_date TEXT NOT NULL,
                available_time TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(name, branch_code, available_date, available_time)
            )
            """
        )

        # BOOKINGS
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                haircut TEXT NOT NULL,
                price INTEGER NOT NULL,
                discount_percent INTEGER NOT NULL DEFAULT 0,
                promocode TEXT,
                branch_code TEXT NOT NULL DEFAULT '',
                master TEXT NOT NULL,
                master_tg_id INTEGER,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
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
            """
        )

        # PROMOCODES (optional)
        if ENABLE_PROMOCODES:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS promocodes (
                    code TEXT PRIMARY KEY,
                    discount_percent INTEGER NOT NULL CHECK(discount_percent BETWEEN 0 AND 100),
                    max_uses INTEGER NOT NULL DEFAULT 0,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    description TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

        # SUPPORT
        cur.execute(
            """
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
            """
        )

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_segment ON users(client_segment)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_masters_date_time ON masters(available_date, available_time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_masters_name ON masters(name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_masters_branch ON masters(branch_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_masters_telegram ON masters(telegram_id) WHERE telegram_id IS NOT NULL")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id) WHERE user_id IS NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_completed ON bookings(completed)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date_time ON bookings(date, time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_master_date_time ON bookings(master, date, time)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_branch ON bookings(branch_code)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_promocode ON bookings(promocode)")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_support_handled ON support_messages(handled)")

        conn.commit()
        cur.close()

        _ensure_columns(conn)
        _seed_branches(conn)
        _seed_promocodes(conn)

        conn.commit()
        log.info("db: init_db completed")


def _ensure_columns(conn: sqlite3.Connection) -> None:
    # USERS
    _add_column_if_missing(conn, "users", "role", "role TEXT NOT NULL DEFAULT 'client'")
    _add_column_if_missing(conn, "users", "client_segment", "client_segment TEXT NOT NULL DEFAULT 'new'")
    _add_column_if_missing(conn, "users", "total_bookings", "total_bookings INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "users", "total_spent", "total_spent INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "users", "last_visit_date", "last_visit_date TEXT")

    # MASTERS
    _add_column_if_missing(conn, "masters", "telegram_id", "telegram_id INTEGER")
    added_branch = _add_column_if_missing(conn, "masters", "branch_code", "branch_code TEXT NOT NULL DEFAULT ''")
    # if column existed but nullable in old DB, normalize NULL -> ''
    try:
        conn.execute("UPDATE masters SET branch_code='' WHERE branch_code IS NULL")
    except Exception:
        pass

    # BOOKINGS
    _add_column_if_missing(conn, "bookings", "duration_minutes", "duration_minutes INTEGER NOT NULL DEFAULT 60")
    _add_column_if_missing(conn, "bookings", "completed", "completed INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "bookings", "actual_paid", "actual_paid INTEGER")
    _add_column_if_missing(conn, "bookings", "completed_at", "completed_at TEXT")
    _add_column_if_missing(conn, "bookings", "completed_by", "completed_by INTEGER")

    _add_column_if_missing(conn, "bookings", "remind_24_sent", "remind_24_sent INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "bookings", "remind_1_sent", "remind_1_sent INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "bookings", "remind_30_sent", "remind_30_sent INTEGER NOT NULL DEFAULT 0")

    _add_column_if_missing(conn, "bookings", "discount_percent", "discount_percent INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "bookings", "promocode", "promocode TEXT")
    _add_column_if_missing(conn, "bookings", "branch_code", "branch_code TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "bookings", "master_tg_id", "master_tg_id INTEGER")

    try:
        conn.execute("UPDATE bookings SET branch_code='' WHERE branch_code IS NULL")
    except Exception:
        pass

    # SUPPORT
    _add_column_if_missing(conn, "support_messages", "parent_id", "parent_id INTEGER")

    # Ensure uniqueness for masters slots even on old DBs:
    # If table was created without UNIQUE(name, branch_code, available_date, available_time),
    # this unique index will enforce it.
    try:
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_masters_slot
            ON masters(name, branch_code, available_date, available_time)
            """
        )
    except Exception:
        # If duplicates exist, index creation can fail. It's better to log and continue.
        log.exception("db: Failed to create uq_masters_slot (duplicates?)")


def ensure_support_parent_column() -> None:
    with get_conn() as conn:
        _ensure_columns(conn)
        conn.commit()


def _seed_branches(conn: sqlite3.Connection) -> None:
    if not ENABLE_MULTI_BRANCH:
        return
    try:
        for code, data in (BRANCHES or {}).items():
            conn.execute(
                """
                INSERT OR IGNORE INTO branches (code, name, address, phone, active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (code, data.get("name", code), data.get("address"), data.get("phone")),
            )
    except Exception:
        log.exception("db: Failed seeding branches")


def _seed_promocodes(conn: sqlite3.Connection) -> None:
    if not ENABLE_PROMOCODES:
        return
    try:
        for code, discount in (PROMOCODE_DISCOUNTS or {}).items():
            conn.execute(
                """
                INSERT OR IGNORE INTO promocodes (code, discount_percent, max_uses, used_count, active, description)
                VALUES (?, ?, ?, 0, 1, ?)
                """,
                (code.strip().upper(), int(discount), int(MAX_PROMOCODE_USES), f"{discount}%"),
            )
    except Exception:
        log.exception("db: Failed seeding promocodes")


# -----------------------------------------------------------------------------
# USERS
# -----------------------------------------------------------------------------
def add_user(user_id: int, full_name: str, phone: str) -> None:
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
            (int(user_id), full_name, phone),
        )
        conn.commit()


def get_user(user_id: int) -> Optional[Tuple[str, str]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT full_name, phone FROM users WHERE user_id=?", (int(user_id),))
        row = cur.fetchone()
        cur.close()
        return (row["full_name"], row["phone"]) if row else None


# -----------------------------------------------------------------------------
# PROMOCODES
# -----------------------------------------------------------------------------
def validate_promocode(code: str) -> Optional[Dict[str, Any]]:
    if not ENABLE_PROMOCODES:
        return None
    code = (code or "").strip().upper()
    if not code:
        return None

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT code, discount_percent, max_uses, used_count, active
            FROM promocodes
            WHERE code=? AND active=1
            """,
            (code,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        if int(row["used_count"]) >= int(row["max_uses"]):
            return None
        return {
            "code": row["code"],
            "discount_percent": int(row["discount_percent"]),
            "uses_left": int(row["max_uses"]) - int(row["used_count"]),
        }


def use_promocode(code: str) -> bool:
    if not ENABLE_PROMOCODES:
        return False
    code = (code or "").strip().upper()
    if not code:
        return False
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE promocodes
            SET used_count = used_count + 1
            WHERE code=? AND active=1 AND used_count < max_uses
            """,
            (code,),
        )
        ok = cur.rowcount > 0
        conn.commit()
        cur.close()
        return ok


# -----------------------------------------------------------------------------
# MASTERS / SLOTS
# -----------------------------------------------------------------------------
def update_master_schedule(
    name: str,
    start_date: str,
    end_date: str,
    start_time: str,
    end_time: str,
    step_minutes: int = 60,
    telegram_id: Optional[int] = None,
    branch_code: Optional[str] = None,
) -> None:
    sd = datetime.strptime(start_date, "%Y-%m-%d").date()
    ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    st = datetime.strptime(start_time, "%H:%M").time()
    et = datetime.strptime(end_time, "%H:%M").time()

    if ed < sd:
        raise ValueError("Конечная дата не может быть раньше начальной")
    if datetime.combine(sd, et) <= datetime.combine(sd, st):
        raise ValueError("Конечное время не может быть раньше или равно начальному")
    if step_minutes <= 0:
        raise ValueError("Шаг должен быть положительным числом")

    bc = (branch_code or "") if ENABLE_MULTI_BRANCH else ""
    slots: List[Tuple[str, Optional[int], str, str, str]] = []

    cur_date = sd
    while cur_date <= ed:
        cur_dt = datetime.combine(cur_date, st)
        end_dt = datetime.combine(cur_date, et)
        while cur_dt < end_dt:
            slots.append(
                (
                    name,
                    telegram_id,
                    bc,
                    cur_date.strftime("%Y-%m-%d"),
                    cur_dt.time().strftime("%H:%M"),
                )
            )
            cur_dt += timedelta(minutes=step_minutes)
        cur_date += timedelta(days=1)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT OR IGNORE INTO masters (name, telegram_id, branch_code, available_date, available_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            slots,
        )
        conn.commit()
        cur.close()


def set_master_telegram(master_name: str, telegram_id: int) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE masters SET telegram_id=? WHERE name=?", (int(telegram_id), master_name))
        conn.commit()
        n = cur.rowcount
        cur.close()
        return int(n)


def get_all_master_slots() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, telegram_id, branch_code, available_date, available_time
            FROM masters
            ORDER BY available_date, available_time, name
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows


def remove_master_slots(slot_id: int) -> int:
    """Delete one slot by id. Returns 0/1."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM masters WHERE id=?", (int(slot_id),))
        conn.commit()
        n = cur.rowcount
        cur.close()
        return int(n)


def remove_master_slots_by_name(master_name: str) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM masters WHERE name=?", (master_name,))
        conn.commit()
        n = cur.rowcount
        cur.close()
        return int(n)


def remove_expired_master_slots() -> int:
    now_local = datetime.now(LOCAL_TZ)
    removed = 0
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, available_date, available_time FROM masters")
        rows = cur.fetchall()
        for r in rows:
            try:
                slot_local = _to_local_dt(r["available_date"], r["available_time"])
            except Exception:
                cur.execute("DELETE FROM masters WHERE id=?", (int(r["id"]),))
                removed += 1
                continue
            if slot_local < now_local:
                cur.execute("DELETE FROM masters WHERE id=?", (int(r["id"]),))
                removed += 1
        conn.commit()
        cur.close()
    return removed


# -----------------------------------------------------------------------------
# Availability for booking
# -----------------------------------------------------------------------------
def get_available_dates(master_name: Optional[str] = None) -> List[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        if master_name:
            cur.execute(
                """
                SELECT DISTINCT available_date
                FROM masters
                WHERE name=?
                ORDER BY available_date
                """,
                (master_name,),
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT available_date
                FROM masters
                ORDER BY available_date
                """
            )
        dates = [row["available_date"] for row in cur.fetchall()]
        cur.close()
        return dates


def get_available_times(date: str, master_name: Optional[str] = None) -> List[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        if master_name:
            cur.execute(
                """
                SELECT available_time
                FROM masters
                WHERE available_date=? AND name=?
                ORDER BY available_time
                """,
                (date, master_name),
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT available_time
                FROM masters
                WHERE available_date=?
                ORDER BY available_time
                """,
                (date,),
            )
        times = [row["available_time"] for row in cur.fetchall()]
        cur.close()
        return times


def get_available_masters(date: str, time: str) -> List[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT name
            FROM masters
            WHERE available_date=? AND available_time=?
            ORDER BY name
            """,
            (date, time),
        )
        masters = [row["name"] for row in cur.fetchall()]
        cur.close()
        return masters


def check_booking(master: str, date: str, time: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM bookings
            WHERE master=? AND date=? AND time=? AND completed=0
            LIMIT 1
            """,
            (master, date, time),
        )
        ok = cur.fetchone() is not None
        cur.close()
        return ok


# -----------------------------------------------------------------------------
# BOOKINGS
# -----------------------------------------------------------------------------
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
    branch_code: Optional[str] = None,
    promocode: Optional[str] = None,
    discount_percent: int = 0,
) -> int:
    if duration_minutes is None:
        duration_minutes = int(HAIRCUT_DURATIONS.get(haircut, 60))

    # cannot book in the past
    local_dt = _to_local_dt(date, time)
    if _to_utc(local_dt) < _utc_now():
        raise ValueError("❌ Нельзя создать запись на прошедшее время")

    promo_code_norm: Optional[str] = None
    promo_discount = 0
    if ENABLE_PROMOCODES and promocode:
        info = validate_promocode(promocode)
        if info:
            promo_code_norm = info["code"]
            promo_discount = int(info["discount_percent"])

    final_discount = int(promo_discount if promo_discount > 0 else (discount_percent or 0))
    final_discount = max(0, min(100, final_discount))

    created_at = _utc_now().isoformat()
    bc = (branch_code or "") if ENABLE_MULTI_BRANCH else ""

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, telegram_id, branch_code
            FROM masters
            WHERE name=? AND available_date=? AND available_time=?
            LIMIT 1
            """,
            (master, date, time),
        )
        slot = cur.fetchone()
        if not slot:
            cur.close()
            raise ValueError("❌ Выбранный слот не существует или уже занят")

        # prefer slot branch
        slot_bc = slot["branch_code"] if slot["branch_code"] is not None else ""
        stored_branch = slot_bc if slot_bc != "" else bc

        # double-check no active booking
        cur.execute(
            """
            SELECT 1 FROM bookings
            WHERE master=? AND date=? AND time=? AND completed=0
            LIMIT 1
            """,
            (master, date, time),
        )
        if cur.fetchone():
            cur.close()
            raise ValueError("❌ Слот уже занят другим клиентом")

        cur.execute(
            """
            INSERT INTO bookings
            (user_id, username, full_name, phone, haircut, price,
             discount_percent, promocode, branch_code,
             master, master_tg_id,
             date, time, duration_minutes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                username,
                full_name,
                phone,
                haircut,
                int(price),
                int(final_discount),
                promo_code_norm,
                stored_branch,
                master,
                slot["telegram_id"],
                date,
                time,
                int(duration_minutes),
                created_at,
            ),
        )
        booking_id = int(cur.lastrowid)

        # consume promocode
        if promo_code_norm:
            use_promocode(promo_code_norm)

        # remove slot
        cur.execute("DELETE FROM masters WHERE id=?", (int(slot["id"]),))

        conn.commit()
        cur.close()

    return booking_id


def get_user_bookings(user_id: int) -> List[Tuple]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, haircut, price, date, time, master
            FROM bookings
            WHERE user_id=? AND completed=0
            ORDER BY date, time
            """,
            (int(user_id),),
        )
        rows = [tuple(r) for r in cur.fetchall()]
        cur.close()
        return rows


def get_booking_by_id(booking_id: int) -> Optional[Tuple]:
    # handlers.py expects booking[6]=date and booking[7]=time
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, user_id, username, full_name, phone, haircut,
                date, time, master,
                price, duration_minutes,
                remind_24_sent, remind_1_sent, remind_30_sent,
                completed, actual_paid, completed_at, completed_by,
                discount_percent, promocode, branch_code, master_tg_id, created_at
            FROM bookings
            WHERE id=?
            """,
            (int(booking_id),),
        )
        row = cur.fetchone()
        cur.close()
        return tuple(row) if row else None


def cancel_booking(booking_id: int, force: bool = False) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, completed, master, master_tg_id, branch_code, date, time
            FROM bookings
            WHERE id=?
            """,
            (int(booking_id),),
        )
        b = cur.fetchone()
        if not b:
            cur.close()
            return False

        if int(b["completed"] or 0) == 1 and not force:
            cur.close()
            return False

        # delete booking
        cur.execute("DELETE FROM bookings WHERE id=?", (int(booking_id),))

        # restore slot if still future
        try:
            slot_local = _to_local_dt(b["date"], b["time"])
            if slot_local >= datetime.now(LOCAL_TZ):
                cur.execute(
                    """
                    INSERT OR IGNORE INTO masters (name, telegram_id, branch_code, available_date, available_time)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        b["master"],
                        b["master_tg_id"],
                        (b["branch_code"] or ""),
                        b["date"],
                        b["time"],
                    ),
                )
        except Exception:
            log.exception("db: Failed to restore slot for canceled booking #%s", booking_id)

        conn.commit()
        cur.close()
        return True


def get_all_bookings_for_admin() -> List[Tuple]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, username, full_name, phone, haircut, price,
                date, time, master, duration_minutes,
                completed, actual_paid
            FROM bookings
            ORDER BY date DESC, time DESC
            """
        )
        rows = [tuple(r) for r in cur.fetchall()]
        cur.close()
        return rows


def mark_booking_completed(booking_id: int, actual_paid: int, completed_by: int) -> bool:
    completed_at = _utc_now().isoformat()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE bookings
            SET completed=1, actual_paid=?, completed_at=?, completed_by=?
            WHERE id=?
            """,
            (int(actual_paid), completed_at, int(completed_by), int(booking_id)),
        )
        ok = cur.rowcount > 0
        conn.commit()
        cur.close()
        return ok


def get_completed_bookings(start_dt_utc: datetime, end_dt_utc: datetime) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, user_id, full_name, phone, haircut, price, date, time, master,
                actual_paid, completed_at, branch_code, promocode, discount_percent
            FROM bookings
            WHERE completed=1
              AND completed_at IS NOT NULL
              AND completed_at >= ?
              AND completed_at <= ?
            ORDER BY completed_at DESC
            """,
            (start_dt_utc.isoformat(), end_dt_utc.isoformat()),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows


# -----------------------------------------------------------------------------
# Reminders (main.py)
# -----------------------------------------------------------------------------
def get_all_bookings_due_between(window_start_utc: datetime, window_end_utc: datetime) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, user_id, full_name, phone, haircut, price, master,
                date, time,
                remind_24_sent, remind_1_sent, remind_30_sent
            FROM bookings
            WHERE completed=0 AND user_id IS NOT NULL
            """
        )
        rows = cur.fetchall()
        cur.close()

    for r in rows:
        try:
            utc_dt = _to_utc(_to_local_dt(r["date"], r["time"]))
        except Exception:
            continue
        if window_start_utc <= utc_dt <= window_end_utc:
            out.append(
                {
                    "id": int(r["id"]),
                    "user_id": int(r["user_id"]),
                    "full_name": r["full_name"],
                    "phone": r["phone"],
                    "haircut": r["haircut"],
                    "price": int(r["price"]),
                    "master": r["master"],
                    "datetime": utc_dt,
                    "remind_24_sent": int(r["remind_24_sent"] or 0),
                    "remind_1_sent": int(r["remind_1_sent"] or 0),
                    "remind_30_sent": int(r["remind_30_sent"] or 0),
                }
            )
    return out


def mark_reminder_sent(booking_id: int, hours: float) -> None:
    col = None
    if hours == 24:
        col = "remind_24_sent"
    elif hours == 1:
        col = "remind_1_sent"
    elif hours == 0.5:
        col = "remind_30_sent"
    else:
        return

    with get_conn() as conn:
        conn.execute(f"UPDATE bookings SET {col}=1 WHERE id=?", (int(booking_id),))
        conn.commit()


def get_bookings_ending_before(now_utc: datetime, lookback_minutes: int = 180) -> List[Dict[str, Any]]:
    res: List[Dict[str, Any]] = []
    cutoff = now_utc - timedelta(minutes=int(lookback_minutes))

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                id, user_id, full_name, phone, haircut, price, master,
                date, time, duration_minutes, master_tg_id, branch_code
            FROM bookings
            WHERE completed=0
            """
        )
        rows = cur.fetchall()
        cur.close()

    for r in rows:
        try:
            start_utc = _to_utc(_to_local_dt(r["date"], r["time"]))
            end_utc = start_utc + timedelta(minutes=int(r["duration_minutes"] or 60))
        except Exception:
            continue

        if cutoff <= end_utc <= now_utc:
            res.append(
                {
                    "id": int(r["id"]),
                    "user_id": r["user_id"],
                    "full_name": r["full_name"],
                    "phone": r["phone"],
                    "haircut": r["haircut"],
                    "price": int(r["price"]),
                    "master": r["master"],
                    "master_tg_id": r["master_tg_id"],
                    "branch_code": r["branch_code"],
                    "start_utc": start_utc,
                    "end_utc": end_utc,
                }
            )
    return res


# -----------------------------------------------------------------------------
# SUPPORT
# -----------------------------------------------------------------------------
def add_support_message(user_id: int, username: str, full_name: str, phone: str, text: str) -> int:
    created_at = _utc_now().isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO support_messages
            (user_id, username, full_name, phone, text, created_at, handled)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (int(user_id), username, full_name, phone, text, created_at),
        )
        sid = int(cur.lastrowid)
        conn.commit()
        cur.close()
        return sid


def get_pending_supports(limit: int = 20) -> List[Tuple]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, user_id, username, full_name, phone, text, created_at
            FROM support_messages
            WHERE handled=0
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = [tuple(r) for r in cur.fetchall()]
        cur.close()
        return rows


def get_support_by_id(support_id: int) -> Optional[Tuple]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, user_id, username, full_name, phone, text, created_at,
                   handled, admin_id, admin_reply, parent_id
            FROM support_messages
            WHERE id=?
            """,
            (int(support_id),),
        )
        row = cur.fetchone()
        cur.close()
        return tuple(row) if row else None


def mark_support_handled(support_id: int, admin_id: int, admin_reply: Optional[str] = None) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE support_messages
            SET handled=1, admin_id=?, admin_reply=?
            WHERE id=?
            """,
            (int(admin_id), admin_reply, int(support_id)),
        )
        ok = cur.rowcount > 0
        conn.commit()
        cur.close()
        return ok


# -----------------------------------------------------------------------------
# STATS / CLEANUP / VACUUM
# -----------------------------------------------------------------------------
def get_database_stats() -> Dict[str, int]:
    with get_conn() as conn:
        cur = conn.cursor()
        stats = {
            "users": int(cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
            "masters_slots": int(cur.execute("SELECT COUNT(*) FROM masters").fetchone()[0]),
            "active_bookings": int(cur.execute("SELECT COUNT(*) FROM bookings WHERE completed=0").fetchone()[0]),
            "completed_bookings": int(cur.execute("SELECT COUNT(*) FROM bookings WHERE completed=1").fetchone()[0]),
            "pending_support": int(cur.execute("SELECT COUNT(*) FROM support_messages WHERE handled=0").fetchone()[0]),
        }
        cur.close()
        return stats


def vacuum_database() -> None:
    with get_conn() as conn:
        conn.execute("VACUUM")
        conn.commit()


def _remove_expired_bookings_no_show() -> int:
    now_utc = _utc_now()
    removed = 0

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, date, time, duration_minutes
            FROM bookings
            WHERE completed=0
            """
        )
        rows = cur.fetchall()

        for r in rows:
            try:
                start_utc = _to_utc(_to_local_dt(r["date"], r["time"]))
                end_utc = start_utc + timedelta(minutes=int(r["duration_minutes"] or 60))
            except Exception:
                continue

            if end_utc + timedelta(hours=int(BOOKING_GRACE_HOURS)) < now_utc:
                cur.execute("DELETE FROM bookings WHERE id=?", (int(r["id"]),))
                removed += 1

        conn.commit()
        cur.close()

    return removed


def _remove_old_completed_bookings() -> int:
    days = int(OLD_BOOKINGS_RETENTION_DAYS or 0)
    if days <= 0:
        return 0

    cutoff = _utc_now() - timedelta(days=days)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM bookings
            WHERE completed=1 AND completed_at IS NOT NULL AND completed_at < ?
            """,
            (cutoff.isoformat(),),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        return int(deleted)


def cleanup_all_expired_data() -> Dict[str, int]:
    expired_slots = remove_expired_master_slots()
    expired_bookings = _remove_expired_bookings_no_show()
    old_completed = _remove_old_completed_bookings()
    return {
        "expired_slots": int(expired_slots),
        "expired_bookings": int(expired_bookings),
        "old_completed": int(old_completed),
    }
