import json

import pytest


@pytest.mark.asyncio
async def test_legacy_plugin_data_migration_preserves_existing_files(
    monkeypatch, tmp_path
):
    from nonebot_plugin_sues_bill import models

    legacy_dir = tmp_path / "data"
    target_dir = legacy_dir / "nonebot_plugin_sues_bill"
    legacy_dir.mkdir()
    legacy_user = legacy_dir / "user_1.json"
    legacy_user.write_text(
        json.dumps({"query_params": {"roomid": "1001"}}), encoding="utf-8"
    )
    unrelated_user = legacy_dir / "user_2.json"
    unrelated_user.write_text(json.dumps({"other_plugin": True}), encoding="utf-8")

    monkeypatch.setattr(models, "DATA_DIR", target_dir)
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", legacy_dir)

    assert models.load_user_data("1") == {"query_params": {"roomid": "1001"}}
    assert (target_dir / "user_1.json").exists()
    assert not legacy_user.exists()
    assert unrelated_user.exists()


@pytest.mark.asyncio
async def test_legacy_key_is_migrated_before_encrypted_account(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    legacy_dir = tmp_path / "data"
    target_dir = legacy_dir / "nonebot_plugin_sues_bill"
    legacy_dir.mkdir()
    (legacy_dir / "secret.key").write_bytes(b"legacy-key")
    (legacy_dir / "user_1.json").write_text(
        json.dumps(
            {"campus_card_account": {"username": "1", "password": "gAAAAA..."}}
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(models, "DATA_DIR", target_dir)
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", legacy_dir)
    models.migrate_legacy_data()

    assert (target_dir / "secret.key").read_bytes() == b"legacy-key"
    assert (target_dir / "user_1.json").exists()
