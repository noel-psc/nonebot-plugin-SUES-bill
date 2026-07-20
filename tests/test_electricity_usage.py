from datetime import date

import pytest

QUERY_PARAMS = {
    "sysid": "4",
    "roomid": "1001",
    "areaid": "101",
    "buildid": "13",
}


@pytest.mark.asyncio
async def test_daily_usage_is_corrected_by_electricity_payment():
    from nonebot_plugin_sues_bill.models import save_electricity_daily_snapshot

    data = {}
    save_electricity_daily_snapshot(
        data,
        snapshot_date=date(2026, 7, 19),
        query_params=QUERY_PARAMS,
        remaining_kwh=20,
        payment_amount_yuan=0,
        price_per_kwh=0.617,
    )
    record = save_electricity_daily_snapshot(
        data,
        snapshot_date=date(2026, 7, 20),
        query_params=QUERY_PARAMS,
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


@pytest.mark.asyncio
async def test_daily_usage_is_estimated_without_payment_history():
    from nonebot_plugin_sues_bill.models import save_electricity_daily_snapshot

    data = {}
    save_electricity_daily_snapshot(
        data,
        snapshot_date=date(2026, 7, 19),
        query_params=QUERY_PARAMS,
        remaining_kwh=20,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )
    record = save_electricity_daily_snapshot(
        data,
        snapshot_date=date(2026, 7, 20),
        query_params=QUERY_PARAMS,
        remaining_kwh=18,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )

    assert record == {
        "status": "estimated",
        "consumed_kwh": 2,
        "cost_yuan": 1.23,
    }


@pytest.mark.asyncio
async def test_balance_increase_is_marked_as_inaccurate_without_account():
    from nonebot_plugin_sues_bill.models import save_electricity_daily_snapshot

    data = {}
    save_electricity_daily_snapshot(
        data,
        snapshot_date=date(2026, 7, 19),
        query_params=QUERY_PARAMS,
        remaining_kwh=20,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )
    record = save_electricity_daily_snapshot(
        data,
        snapshot_date=date(2026, 7, 20),
        query_params=QUERY_PARAMS,
        remaining_kwh=25,
        payment_amount_yuan=None,
        price_per_kwh=0.617,
    )

    assert record == {"status": "estimated_recharge_detected"}
