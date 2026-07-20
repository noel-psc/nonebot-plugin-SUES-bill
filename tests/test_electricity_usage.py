from datetime import date

import pytest

QUERY_PARAMS = {
    "sysid": "4",
    "roomid": "1001",
    "areaid": "101",
    "buildid": "13",
}


@pytest.fixture
def room_id(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    models.set_room_subscription("1", QUERY_PARAMS)
    subscription = models.get_room_subscription("1")
    assert subscription is not None
    return subscription["room_id"]


def test_daily_usage_is_corrected_by_electricity_payment(room_id):
    from nonebot_plugin_sues_bill.models import save_electricity_daily_snapshot

    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 19),
        remaining_kwh=20,
        payment_amount_yuan=0,
        price_per_kwh=0.617,
    )
    record = save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 20),
        remaining_kwh=18,
        payment_amount_yuan=6.17,
        price_per_kwh=0.617,
    )

    assert record == {
        "status": "complete",
        "consumed_kwh": 12.0,
        "cost_yuan": 7.4,
        "payment_amount_yuan": 6.17,
    }


def test_daily_usage_is_estimated_without_payment_history(room_id):
    from nonebot_plugin_sues_bill.models import save_electricity_daily_snapshot

    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 19),
        remaining_kwh=20,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )
    record = save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 20),
        remaining_kwh=18,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )

    assert record == {
        "status": "estimated",
        "consumed_kwh": 2,
        "cost_yuan": 1.23,
    }


def test_balance_increase_is_not_included_in_statistics(room_id):
    from nonebot_plugin_sues_bill.models import (
        get_usage_statistics,
        save_electricity_daily_snapshot,
    )

    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 19),
        remaining_kwh=20,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )
    record = save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 20),
        remaining_kwh=25,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )

    assert record == {"status": "recharge_unverified"}
    statistics = get_usage_statistics(room_id, 30, date(2026, 7, 20))
    assert statistics["valid_days"] == 0
    assert statistics["unavailable_days"] == 1


def test_statistics_returns_highest_usage_day(room_id):
    from nonebot_plugin_sues_bill.models import (
        get_usage_statistics,
        save_electricity_daily_snapshot,
    )

    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 17),
        remaining_kwh=20,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )
    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 18),
        remaining_kwh=18,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )
    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 19),
        remaining_kwh=13,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )

    statistics = get_usage_statistics(room_id, 30, date(2026, 7, 20))
    assert statistics == {
        "days": 30,
        "valid_days": 2,
        "complete_days": 0,
        "estimated_days": 2,
        "unavailable_days": 0,
        "total_kwh": 7.0,
        "total_cost_yuan": 4.31,
        "max_date": "2026-07-18",
        "max_kwh": 5.0,
    }


def test_record_statistics_accepts_compact_and_spaced_days():
    from nonebot_plugin_sues_bill.electric import parse_statistics_days

    assert parse_statistics_days("统计30天") == 30
    assert parse_statistics_days("统计 30天") == 30
    assert parse_statistics_days("统计7天") == 7
    assert parse_statistics_days("统计 7") == 7
    assert parse_statistics_days("统计") == 30
    assert parse_statistics_days("查看") is None


def test_successful_queries_are_stored_without_daily_snapshot(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    room_id = models.record_electricity_query(QUERY_PARAMS, 20)
    models.record_electricity_query(QUERY_PARAMS, 18.5)

    queries = models.get_room_readings(room_id)
    assert [query["remaining_kwh"] for query in queries] == [18.5, 20.0]
