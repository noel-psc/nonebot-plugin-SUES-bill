QUERY_PARAMS = {
    "sysid": "4",
    "roomid": "1001",
    "areaid": "101",
    "buildid": "13",
}
OTHER_QUERY_PARAMS = {
    "sysid": "4",
    "roomid": "1002",
    "areaid": "101",
    "buildid": "13",
}


def _fresh_models(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    data_dir = tmp_path / "data"
    monkeypatch.setattr(models, "DATA_DIR", data_dir)
    models.initialize_database()
    return models


def test_migrate_legacy_user_moves_account_and_subscription(monkeypatch, tmp_path):
    models = _fresh_models(monkeypatch, tmp_path)
    models.set_room_subscription("2943185485", QUERY_PARAMS)
    models.save_campus_card_account("2943185485", "028125142", "encrypted")

    result = models.migrate_legacy_user("openid-new", "2943185485")

    assert result == "migrated"
    subscription = models.get_room_subscription("openid-new")
    assert subscription is not None
    assert subscription["roomid"] == "1001"
    assert models.load_campus_card_account("openid-new") == {
        "username": "028125142",
        "password": "encrypted",
    }
    assert models.get_room_subscription("2943185485", include_disabled=True) is None
    assert models.load_campus_card_account("2943185485") == {}


def test_migrate_legacy_user_rejects_non_numeric_old_id(monkeypatch, tmp_path):
    models = _fresh_models(monkeypatch, tmp_path)
    assert models.migrate_legacy_user("openid-new", "not-a-qq") == "invalid_old_id"


def test_migrate_legacy_user_reports_missing_data(monkeypatch, tmp_path):
    models = _fresh_models(monkeypatch, tmp_path)
    assert models.migrate_legacy_user("openid-new", "123456789") == "no_data"


def test_migrate_legacy_user_rejects_account_conflict(monkeypatch, tmp_path):
    models = _fresh_models(monkeypatch, tmp_path)
    models.save_campus_card_account("1000000001", "028125142", "encrypted")
    models.save_campus_card_account("openid-new", "111111111", "encrypted")

    result = models.migrate_legacy_user("openid-new", "1000000001")

    assert result == "account_conflict"
    assert models.load_campus_card_account("1000000001") != {}


def test_migrate_legacy_user_rejects_subscription_conflict(monkeypatch, tmp_path):
    models = _fresh_models(monkeypatch, tmp_path)
    models.set_room_subscription("1000000001", QUERY_PARAMS)
    models.set_room_subscription("openid-new", OTHER_QUERY_PARAMS)

    result = models.migrate_legacy_user("openid-new", "1000000001")

    assert result == "subscription_conflict"
    assert models.get_room_subscription("openid-new") is not None
