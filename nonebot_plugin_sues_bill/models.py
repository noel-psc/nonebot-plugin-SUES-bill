import json

from nonebot_plugin_localstore import get_plugin_data_file

DATA_DIR = get_plugin_data_file("").parent


def load_json(file_path) -> dict:
    """通用 JSON 加载"""
    if file_path.exists():
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_json(file_path, data: dict):
    """通用 JSON 保存"""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_file(user_id: str):
    return DATA_DIR / f"user_{user_id}.json"


def load_user_data(user_id: str) -> dict:
    return load_json(get_user_file(user_id))


def save_user_data(user_id: str, data: dict):
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
