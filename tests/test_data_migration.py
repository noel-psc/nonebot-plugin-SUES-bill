import json
from datetime import date

QUERY_PARAMS = {
    "sysid": "4",
    "roomid": "1001",
    "areaid": "101",
    "buildid": "13",
}


def test_legacy_json_is_migrated_to_sqlite_once(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    legacy_dir = tmp_path / "data"
    target_dir = legacy_dir / "nonebot_plugin_sues_bill"
    legacy_dir.mkdir()
    (legacy_dir / "secret.key").write_bytes(b"legacy-key")
    (legacy_dir / "user_1.json").write_text(
        json.dumps(
            {
                "campus_card_account": {
                    "username": "20260001",
                    "password": "gAAAAA...",
                },
                "query_params": QUERY_PARAMS,
                "electricity_usage": {
                    "query_params": QUERY_PARAMS,
                    "snapshots": {"2026-07-19": 20},
                    "daily": {
                        "2026-07-18": {
                            "status": "estimated",
                            "consumed_kwh": 2,
                            "cost_yuan": 1.23,
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(models, "DATA_DIR", target_dir)
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", legacy_dir)
    models.initialize_database()

    subscription = models.get_room_subscription("1")
    assert subscription is not None
    assert subscription["roomid"] == "1001"
    assert models.load_campus_card_account("1") == {
        "username": "20260001",
        "password": "gAAAAA...",
    }
    assert models.get_daily_usage(subscription["room_id"], date(2026, 7, 18)) == {
        "status": "estimated",
        "consumed_kwh": 2.0,
        "cost_yuan": 1.23,
        "payment_amount_yuan": None,
    }
    assert not models.subscription_has_bound_account("1")
    assert (target_dir / "secret.key").read_bytes() == b"legacy-key"
    assert (target_dir / "user_1.json").exists()

    models.initialize_database()
    statistics = models.get_usage_statistics(
        subscription["room_id"], 30, date(2026, 7, 20)
    )
    assert statistics["valid_days"] == 1


def test_subscription_and_binding_are_independent(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    models.set_room_subscription("1", QUERY_PARAMS)
    assert models.save_campus_card_account("1", "20260001", "encrypted")
    assert models.bind_account_to_subscription("1") == "bound"
    assert models.save_campus_card_account("2", "20260002", "other-encrypted")
    models.set_room_subscription("2", QUERY_PARAMS)
    assert models.bind_account_to_subscription("2") == "room_bound"

    changed_params = {**QUERY_PARAMS, "roomid": "1002"}
    models.set_room_subscription("1", changed_params)
    new_subscription = models.get_room_subscription("1")
    assert new_subscription is not None
    assert not models.subscription_has_bound_account("1")
    assert models.bind_account_to_subscription("1") == "bound"
    assert models.subscription_has_bound_account("1")

    assert not models.save_campus_card_account("3", "20260001", "other-encrypted")


def test_scheduled_rooms_are_deduplicated(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    models.set_room_subscription("1", QUERY_PARAMS)
    models.set_room_subscription("2", QUERY_PARAMS)

    rooms = models.get_scheduled_rooms()
    assert len(rooms) == 1
    assert rooms[0]["roomid"] == "1001"
