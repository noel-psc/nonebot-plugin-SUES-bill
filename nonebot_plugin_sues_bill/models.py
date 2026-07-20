import json
import sqlite3
from typing import Any
from pathlib import Path
from datetime import UTC, date, time, datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import contextmanager
from collections.abc import Iterator

from nonebot import require

require("nonebot_plugin_localstore")
from nonebot_plugin_localstore import get_plugin_data_file

# get_plugin_data_file("") is the plugin-specific directory. Earlier releases
# accidentally wrote directly to the parent global data directory.
DATA_DIR = get_plugin_data_file("")
LEGACY_DATA_DIR = DATA_DIR.parent
DB_FILE_NAME = "sues_bill.sqlite3"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
PLUGIN_USER_DATA_KEYS = frozenset(
    {"campus_card_account", "query_params", "electricity_usage"}
)


def get_database_path() -> Path:
    return DATA_DIR / DB_FILE_NAME


def load_json(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    try:
        with file_path.open(encoding="utf-8") as file:
            value = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def migrate_legacy_data() -> None:
    """Move plugin JSON mistakenly saved in the global data directory."""
    if LEGACY_DATA_DIR == DATA_DIR or not LEGACY_DATA_DIR.exists():
        return

    legacy_users = [
        file_path
        for file_path in LEGACY_DATA_DIR.glob("user_*.json")
        if PLUGIN_USER_DATA_KEYS.intersection(load_json(file_path))
    ]
    if not legacy_users:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    has_encrypted_account = any(
        load_json(file_path)
        .get("campus_card_account", {})
        .get("password", "")
        .startswith("gAAAAA")
        for file_path in legacy_users
    )
    legacy_key = LEGACY_DATA_DIR / "secret.key"
    target_key = DATA_DIR / "secret.key"
    if has_encrypted_account and legacy_key.exists() and not target_key.exists():
        legacy_key.replace(target_key)

    for legacy_file in legacy_users:
        target_file = DATA_DIR / legacy_file.name
        if not target_file.exists():
            legacy_file.replace(target_file)


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_users (
    user_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY,
    sysid TEXT NOT NULL,
    roomid TEXT NOT NULL,
    areaid TEXT NOT NULL,
    buildid TEXT NOT NULL,
    UNIQUE(sysid, roomid, areaid, buildid)
);
CREATE TABLE IF NOT EXISTS room_subscriptions (
    user_id TEXT PRIMARY KEY REFERENCES bot_users(user_id) ON DELETE CASCADE,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS campus_accounts (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES bot_users(user_id) ON DELETE CASCADE,
    username TEXT NOT NULL UNIQUE,
    encrypted_password TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_room_bindings (
    account_id INTEGER PRIMARY KEY REFERENCES campus_accounts(id) ON DELETE CASCADE,
    room_id INTEGER NOT NULL UNIQUE REFERENCES rooms(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS room_snapshots (
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    snapshot_date TEXT NOT NULL,
    remaining_kwh REAL NOT NULL,
    PRIMARY KEY(room_id, snapshot_date)
);
CREATE TABLE IF NOT EXISTS room_readings (
    id INTEGER PRIMARY KEY,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    queried_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    remaining_kwh REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS room_daily_usage (
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    usage_date TEXT NOT NULL,
    status TEXT NOT NULL,
    consumed_kwh REAL,
    cost_yuan REAL,
    payment_amount_yuan REAL,
    PRIMARY KEY(room_id, usage_date)
);
CREATE INDEX IF NOT EXISTS idx_room_daily_usage_date
    ON room_daily_usage(room_id, usage_date);
CREATE INDEX IF NOT EXISTS idx_room_readings_room_date
    ON room_readings(room_id, queried_at);
"""


def _ensure_user(connection: sqlite3.Connection, user_id: str) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO bot_users(user_id) VALUES (?)", (str(user_id),)
    )


def _room_id(connection: sqlite3.Connection, query_params: dict[str, str]) -> int:
    values = tuple(
        str(query_params[key]) for key in ("sysid", "roomid", "areaid", "buildid")
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO rooms(sysid, roomid, areaid, buildid)
        VALUES (?, ?, ?, ?)
        """,
        values,
    )
    row = connection.execute(
        """
        SELECT id FROM rooms
        WHERE sysid = ? AND roomid = ? AND areaid = ? AND buildid = ?
        """,
        values,
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _row_to_params(row: sqlite3.Row) -> dict[str, str]:
    return {
        "sysid": str(row["sysid"]),
        "roomid": str(row["roomid"]),
        "areaid": str(row["areaid"]),
        "buildid": str(row["buildid"]),
    }


def _import_legacy_json(connection: sqlite3.Connection) -> None:
    already_imported = connection.execute(
        "SELECT 1 FROM metadata WHERE key = 'legacy_json_imported'"
    ).fetchone()
    if already_imported:
        return

    for file_path in DATA_DIR.glob("user_*.json"):
        user_id = file_path.stem.removeprefix("user_")
        data = load_json(file_path)
        if not PLUGIN_USER_DATA_KEYS.intersection(data):
            continue
        _ensure_user(connection, user_id)

        account = data.get("campus_card_account", {})
        username = account.get("username")
        password = account.get("password")
        if isinstance(username, str) and isinstance(password, str):
            # A duplicated historical account remains owned by the first user.
            connection.execute(
                """
                INSERT OR IGNORE INTO campus_accounts(
                    user_id, username, encrypted_password
                )
                VALUES (?, ?, ?)
                """,
                (user_id, username, password),
            )

        query_params = data.get("query_params")
        if isinstance(query_params, dict) and all(
            key in query_params for key in ("sysid", "roomid", "areaid", "buildid")
        ):
            room_id = _room_id(connection, query_params)
            connection.execute(
                """
                INSERT INTO room_subscriptions(user_id, room_id, enabled)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id) DO UPDATE SET room_id = excluded.room_id,
                    enabled = 1, updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, room_id),
            )

        usage = data.get("electricity_usage", {})
        usage_params = (
            usage.get("query_params", query_params) if isinstance(usage, dict) else None
        )
        if not isinstance(usage_params, dict) or not all(
            key in usage_params for key in ("sysid", "roomid", "areaid", "buildid")
        ):
            continue
        room_id = _room_id(connection, usage_params)
        for snapshot_date, remaining_kwh in usage.get("snapshots", {}).items():
            try:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO room_snapshots(
                        room_id, snapshot_date, remaining_kwh
                    )
                    VALUES (?, ?, ?)
                    """,
                    (room_id, snapshot_date, float(remaining_kwh)),
                )
            except (TypeError, ValueError):
                continue
        for usage_date, record in usage.get("daily", {}).items():
            if not isinstance(record, dict):
                continue
            status = str(record.get("status", "estimated"))
            if status == "estimated_recharge_detected":
                status = "recharge_unverified"
            connection.execute(
                """
                INSERT OR IGNORE INTO room_daily_usage(
                    room_id, usage_date, status, consumed_kwh, cost_yuan,
                    payment_amount_yuan
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    room_id,
                    usage_date,
                    status,
                    record.get("consumed_kwh"),
                    record.get("cost_yuan"),
                    record.get("payment_amount_yuan"),
                ),
            )

    connection.execute(
        "INSERT INTO metadata(key, value) VALUES ('legacy_json_imported', '1')"
    )


def initialize_database() -> None:
    migrate_legacy_data()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', '1')"
        )
        _import_legacy_json(connection)


def load_campus_card_account(user_id: str) -> dict[str, str]:
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT username, encrypted_password FROM campus_accounts WHERE user_id = ?
            """,
            (str(user_id),),
        ).fetchone()
    if row is None:
        return {}
    return {"username": row["username"], "password": row["encrypted_password"]}


def save_campus_card_account(user_id: str, username: str, password: str) -> bool:
    """Save an account. A username cannot be owned by multiple bot users."""
    initialize_database()
    with _connection() as connection:
        _ensure_user(connection, str(user_id))
        owner = connection.execute(
            "SELECT user_id FROM campus_accounts WHERE username = ?", (username,)
        ).fetchone()
        if owner is not None and owner["user_id"] != str(user_id):
            return False
        existing = connection.execute(
            "SELECT id, username FROM campus_accounts WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        if existing is not None and existing["username"] != username:
            connection.execute(
                "DELETE FROM account_room_bindings WHERE account_id = ?",
                (int(existing["id"]),),
            )
        connection.execute(
            """
            INSERT INTO campus_accounts(user_id, username, encrypted_password)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username,
                encrypted_password = excluded.encrypted_password
            """,
            (str(user_id), username, password),
        )
    return True


def set_room_subscription(user_id: str, query_params: dict[str, str]) -> None:
    initialize_database()
    with _connection() as connection:
        _ensure_user(connection, str(user_id))
        room_id = _room_id(connection, query_params)
        connection.execute(
            """
            INSERT INTO room_subscriptions(user_id, room_id, enabled)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET room_id = excluded.room_id,
                enabled = 1, updated_at = CURRENT_TIMESTAMP
            """,
            (str(user_id), room_id),
        )


def get_room_subscription(
    user_id: str, include_disabled: bool = False
) -> dict[str, Any] | None:
    initialize_database()
    enabled_filter = "" if include_disabled else "AND subscriptions.enabled = 1"
    with _connection() as connection:
        row = connection.execute(
            f"""
            SELECT rooms.id AS room_id, rooms.sysid, rooms.roomid, rooms.areaid,
                   rooms.buildid, subscriptions.enabled
            FROM room_subscriptions AS subscriptions
            JOIN rooms ON rooms.id = subscriptions.room_id
            WHERE subscriptions.user_id = ? {enabled_filter}
            """,
            (str(user_id),),
        ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = _row_to_params(row)
    result["room_id"] = int(row["room_id"])
    result["enabled"] = bool(row["enabled"])
    return result


def stop_room_subscription(user_id: str) -> bool:
    initialize_database()
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE room_subscriptions SET enabled = 0, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND enabled = 1
            """,
            (str(user_id),),
        )
    return cursor.rowcount > 0


def bind_account_to_subscription(user_id: str) -> str:
    """Bind the caller's account to their enabled room subscription.

    Returns a stable result code for command handlers.
    """
    initialize_database()
    with _connection() as connection:
        subscription = connection.execute(
            """
            SELECT room_id FROM room_subscriptions WHERE user_id = ? AND enabled = 1
            """,
            (str(user_id),),
        ).fetchone()
        if subscription is None:
            return "no_subscription"
        account = connection.execute(
            "SELECT id FROM campus_accounts WHERE user_id = ?", (str(user_id),)
        ).fetchone()
        if account is None:
            return "no_account"
        room_id = int(subscription["room_id"])
        occupied = connection.execute(
            "SELECT account_id FROM account_room_bindings WHERE room_id = ?",
            (room_id,),
        ).fetchone()
        if occupied is not None and occupied["account_id"] != account["id"]:
            return "room_bound"
        connection.execute(
            """
            INSERT INTO account_room_bindings(account_id, room_id) VALUES (?, ?)
            ON CONFLICT(account_id) DO UPDATE SET room_id = excluded.room_id
            """,
            (int(account["id"]), room_id),
        )
    return "bound"


def unbind_account_from_subscription(user_id: str) -> bool:
    initialize_database()
    with _connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM account_room_bindings
            WHERE account_id = (SELECT id FROM campus_accounts WHERE user_id = ?)
            """,
            (str(user_id),),
        )
    return cursor.rowcount > 0


def get_bound_accounts_for_room(room_id: int) -> list[dict[str, str]]:
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT campus_accounts.username, campus_accounts.encrypted_password
            FROM account_room_bindings
            JOIN campus_accounts
                ON campus_accounts.id = account_room_bindings.account_id
            WHERE account_room_bindings.room_id = ?
            """,
            (room_id,),
        ).fetchall()
    return [
        {"username": row["username"], "password": row["encrypted_password"]}
        for row in rows
    ]


def subscription_has_bound_account(user_id: str) -> bool:
    subscription = get_room_subscription(user_id)
    return bool(
        subscription is not None
        and get_bound_accounts_for_room(subscription["room_id"])
    )


def get_scheduled_rooms() -> list[dict[str, Any]]:
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT rooms.id AS room_id, rooms.sysid, rooms.roomid,
                   rooms.areaid, rooms.buildid
            FROM room_subscriptions AS subscriptions
            JOIN rooms ON rooms.id = subscriptions.room_id
            WHERE subscriptions.enabled = 1
            """
        ).fetchall()
    result = []
    for row in rows:
        room: dict[str, Any] = _row_to_params(row)
        room["room_id"] = int(row["room_id"])
        result.append(room)
    return result


def record_electricity_query(
    query_params: dict[str, str], remaining_kwh: float
) -> int:
    """Store a room reading without changing daily boundary snapshots."""
    initialize_database()
    with _connection() as connection:
        room_id = _room_id(connection, query_params)
        connection.execute(
            """
            INSERT INTO room_readings(room_id, remaining_kwh)
            VALUES (?, ?)
            """,
            (room_id, round(remaining_kwh, 3)),
        )
    return room_id


def get_room_readings(room_id: int) -> list[dict[str, Any]]:
    """Return a room's manual query records, newest first."""
    initialize_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT queried_at, remaining_kwh
            FROM room_readings
            WHERE room_id = ?
            ORDER BY id DESC
            """,
            (room_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_today_reading_estimate(
    room_id: int, target_date: date, price_per_kwh: float
) -> dict[str, Any]:
    """Estimate today's usage from the first and latest Shanghai-day readings."""
    initialize_database()
    start = datetime.combine(target_date, time.min, SHANGHAI_TZ).astimezone(UTC)
    end = datetime.combine(
        target_date + timedelta(days=1), time.min, SHANGHAI_TZ
    ).astimezone(UTC)
    bounds = tuple(moment.strftime("%Y-%m-%d %H:%M:%S") for moment in (start, end))
    with _connection() as connection:
        first = connection.execute(
            """
            SELECT remaining_kwh
            FROM room_readings
            WHERE room_id = ? AND queried_at >= ? AND queried_at < ?
            ORDER BY queried_at, id
            LIMIT 1
            """,
            (room_id, *bounds),
        ).fetchone()
        latest = connection.execute(
            """
            SELECT remaining_kwh
            FROM room_readings
            WHERE room_id = ? AND queried_at >= ? AND queried_at < ?
            ORDER BY queried_at DESC, id DESC
            LIMIT 1
            """,
            (room_id, *bounds),
        ).fetchone()
        reading_count = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM room_readings
                WHERE room_id = ? AND queried_at >= ? AND queried_at < ?
                """,
                (room_id, *bounds),
            ).fetchone()[0]
        )

    if reading_count < 2 or first is None or latest is None:
        return {"status": "insufficient_readings", "reading_count": reading_count}

    consumed_kwh = float(first["remaining_kwh"]) - float(latest["remaining_kwh"])
    if consumed_kwh < -0.001:
        return {"status": "recharge_unverified"}
    consumed_kwh = max(consumed_kwh, 0)
    return {
        "status": "estimated",
        "consumed_kwh": round(consumed_kwh, 3),
        "cost_yuan": round(consumed_kwh * price_per_kwh, 2),
    }


def save_electricity_daily_snapshot(
    room_id: int,
    *,
    snapshot_date: date,
    remaining_kwh: float,
    payment_amount_yuan: float | None,
    price_per_kwh: float,
) -> dict[str, Any] | None:
    """Persist a room boundary snapshot and settle the prior natural day."""
    initialize_database()
    snapshot_key = snapshot_date.isoformat()
    previous_key = (snapshot_date - timedelta(days=1)).isoformat()
    with _connection() as connection:
        previous = connection.execute(
            """
            SELECT remaining_kwh FROM room_snapshots
            WHERE room_id = ? AND snapshot_date = ?
            """,
            (room_id, previous_key),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO room_snapshots(room_id, snapshot_date, remaining_kwh)
            VALUES (?, ?, ?)
            ON CONFLICT(room_id, snapshot_date) DO UPDATE SET
                remaining_kwh = excluded.remaining_kwh
            """,
            (room_id, snapshot_key, round(remaining_kwh, 3)),
        )
        if previous is None:
            return None
        exists = connection.execute(
            """
            SELECT 1 FROM room_daily_usage WHERE room_id = ? AND usage_date = ?
            """,
            (room_id, previous_key),
        ).fetchone()
        if exists:
            return None

        previous_kwh = float(previous["remaining_kwh"])
        if payment_amount_yuan is None:
            consumed_kwh = previous_kwh - remaining_kwh
            if consumed_kwh < -0.001:
                record = {"status": "recharge_unverified"}
            else:
                consumed_kwh = max(consumed_kwh, 0)
                record = {
                    "status": "estimated",
                    "consumed_kwh": round(consumed_kwh, 3),
                    "cost_yuan": round(consumed_kwh * price_per_kwh, 2),
                }
        else:
            consumed_kwh = (
                previous_kwh + payment_amount_yuan / price_per_kwh - remaining_kwh
            )
            if consumed_kwh < -0.001:
                record = {
                    "status": "calculation_error",
                    "payment_amount_yuan": round(payment_amount_yuan, 2),
                }
            else:
                consumed_kwh = max(consumed_kwh, 0)
                record = {
                    "status": "complete",
                    "consumed_kwh": round(consumed_kwh, 3),
                    "cost_yuan": round(consumed_kwh * price_per_kwh, 2),
                    "payment_amount_yuan": round(payment_amount_yuan, 2),
                }
        connection.execute(
            """
            INSERT INTO room_daily_usage(
                room_id, usage_date, status, consumed_kwh, cost_yuan,
                payment_amount_yuan
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                room_id,
                previous_key,
                record["status"],
                record.get("consumed_kwh"),
                record.get("cost_yuan"),
                record.get("payment_amount_yuan"),
            ),
        )
    return record


def get_daily_usage(room_id: int, usage_date: date) -> dict[str, Any] | None:
    initialize_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT status, consumed_kwh, cost_yuan, payment_amount_yuan
            FROM room_daily_usage WHERE room_id = ? AND usage_date = ?
            """,
            (room_id, usage_date.isoformat()),
        ).fetchone()
    return dict(row) if row is not None else None


def get_usage_statistics(room_id: int, days: int, today: date) -> dict[str, Any]:
    """Return complete/estimated values for the previous ``days`` natural days."""
    initialize_database()
    start = today - timedelta(days=days)
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT usage_date, status, consumed_kwh, cost_yuan
            FROM room_daily_usage
            WHERE room_id = ? AND usage_date >= ? AND usage_date < ?
            ORDER BY usage_date
            """,
            (room_id, start.isoformat(), today.isoformat()),
        ).fetchall()
    valid = [row for row in rows if row["status"] in {"complete", "estimated"}]
    maximum = max(valid, key=lambda row: float(row["consumed_kwh"])) if valid else None
    return {
        "days": days,
        "valid_days": len(valid),
        "complete_days": sum(row["status"] == "complete" for row in rows),
        "estimated_days": sum(row["status"] == "estimated" for row in rows),
        "unavailable_days": len(rows) - len(valid),
        "total_kwh": round(sum(float(row["consumed_kwh"]) for row in valid), 3),
        "total_cost_yuan": round(sum(float(row["cost_yuan"]) for row in valid), 2),
        "max_date": maximum["usage_date"] if maximum is not None else None,
        "max_kwh": round(float(maximum["consumed_kwh"]), 3)
        if maximum is not None
        else None,
    }
