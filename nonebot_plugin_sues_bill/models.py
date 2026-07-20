import json
from copy import deepcopy
from pathlib import Path
from datetime import date, timedelta

from nonebot import require

require("nonebot_plugin_localstore")
from nonebot_plugin_localstore import get_plugin_data_file

# get_plugin_data_file("") 即插件专属目录；此前取 parent 会退回全局 data/。
DATA_DIR = get_plugin_data_file("")
LEGACY_DATA_DIR = DATA_DIR.parent
PLUGIN_USER_DATA_KEYS = frozenset(
    {"campus_card_account", "query_params", "electricity_usage"}
)


def load_json(file_path: Path) -> dict:
    """通用 JSON 加载"""
    if file_path.exists():
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_json(file_path: Path, data: dict):
    """通用 JSON 保存"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_file(user_id: str) -> Path:
    return DATA_DIR / f"user_{user_id}.json"


def migrate_legacy_data():
    """将旧版误存于全局 data 目录的本插件数据迁移到专属目录。"""
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


def load_user_data(user_id: str) -> dict:
    migrate_legacy_data()
    return load_json(get_user_file(user_id))


def save_user_data(user_id: str, data: dict):
    migrate_legacy_data()
    save_json(get_user_file(user_id), data)


def load_campus_card_account(user_id: str) -> dict:
    """加载指定用户的校园卡账号"""
    data = load_user_data(user_id)
    return data.get("campus_card_account", {})


def save_campus_card_account(user_id: str, username: str, password: str):
    """保存指定用户的校园卡账号（密码加密存储由调用方处理）"""
    data = load_user_data(user_id)
    data["campus_card_account"] = {"username": username, "password": password}
    save_user_data(user_id, data)


def get_electricity_user_ids() -> list[str]:
    """返回保存过电费查询参数的用户 ID。"""
    migrate_legacy_data()
    if not DATA_DIR.exists():
        return []
    return [
        file_path.stem.removeprefix("user_")
        for file_path in DATA_DIR.glob("user_*.json")
    ]


def save_electricity_daily_snapshot(
    data: dict,
    *,
    snapshot_date: date,
    query_params: dict,
    remaining_kwh: float,
    payment_amount_yuan: float | None,
    price_per_kwh: float,
) -> dict | None:
    """保存日界电量快照；条件满足时结算前一自然日用电。"""
    usage = data.setdefault("electricity_usage", {})
    if usage.get("query_params") != query_params:
        usage.clear()
        usage["query_params"] = deepcopy(query_params)
        usage["snapshots"] = {}
        usage["daily"] = {}

    snapshots = usage.setdefault("snapshots", {})
    daily = usage.setdefault("daily", {})
    snapshot_key = snapshot_date.isoformat()
    previous_date = snapshot_date - timedelta(days=1)
    previous_key = previous_date.isoformat()
    previous_kwh = snapshots.get(previous_key)

    snapshots[snapshot_key] = round(remaining_kwh, 3)
    if previous_kwh is None or previous_key in daily:
        return None

    if payment_amount_yuan is None:
        consumed_kwh = previous_kwh - remaining_kwh
        if consumed_kwh < -0.001:
            daily[previous_key] = {"status": "estimated_recharge_detected"}
            return daily[previous_key]

        consumed_kwh = max(consumed_kwh, 0)
        daily[previous_key] = {
            "status": "estimated",
            "consumed_kwh": round(consumed_kwh, 3),
            "cost_yuan": round(consumed_kwh * price_per_kwh, 2),
        }
        return daily[previous_key]

    consumed_kwh = previous_kwh + payment_amount_yuan / price_per_kwh - remaining_kwh
    if consumed_kwh < -0.001:
        daily[previous_key] = {
            "status": "calculation_error",
            "payment_amount_yuan": round(payment_amount_yuan, 2),
        }
        return daily[previous_key]

    consumed_kwh = max(consumed_kwh, 0)
    daily[previous_key] = {
        "status": "complete",
        "consumed_kwh": round(consumed_kwh, 3),
        "cost_yuan": round(consumed_kwh * price_per_kwh, 2),
        "payment_amount_yuan": round(payment_amount_yuan, 2),
    }
    return daily[previous_key]
