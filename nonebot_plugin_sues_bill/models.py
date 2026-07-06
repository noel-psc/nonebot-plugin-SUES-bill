import json

from nonebot_plugin_localstore import get_plugin_data_file

DATA_DIR = get_plugin_data_file("").parent


def get_user_file(user_id: str):
    return DATA_DIR / f"user_{user_id}.json"


def load_user_data(user_id: str) -> dict:
    user_file = get_user_file(user_id)
    if user_file.exists():
        try:
            with open(user_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_user_data(user_id: str, data: dict):
    with open(get_user_file(user_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
