from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

QUERY_PARAMS = {
    "sysid": "4",
    "roomid": "1001",
    "areaid": "101",
    "buildid": "13",
}
PRICE_PER_KWH = 0.617


@pytest.mark.asyncio
async def test_payment_query_reports_expired_bill_session(monkeypatch):
    from nonebot_plugin_sues_bill import campus_card

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bill"):
            return httpx.Response(200, text="\n\n<html>登录已过期</html>")
        return httpx.Response(200, json={"retcode": 0, "dtls": []})

    monkeypatch.setattr(campus_card.config, "sues_base_url", "https://example.test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await campus_card.query_electric_payment_records(client)

    assert result == {"retcode": -1, "retmsg": "账单登录状态已过期"}


def _recharge_paybill_page(billno: str, refno: str, csrf: str) -> str:
    return (
        '<html><head><meta name="_csrf" content="%s"/>'
        '<meta name="_csrf_header" content="X-CSRF-TOKEN"/></head>'
        f'<body><input type="hidden" id="billno" value="{billno}">'
        f'<input type="hidden" id="refno" value="{refno}"></body></html>'
    ) % csrf


@pytest.mark.asyncio
async def test_recharge_electricity_pays_from_balance(monkeypatch):
    from nonebot_plugin_sues_bill import campus_card

    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/eleresult"):
            return httpx.Response(200, text='<input id="roomdef" left-degree="16.0">')
        if request.url.path.endswith("/elepaybill"):
            assert request.url.params["amount"] == "50"
            return httpx.Response(
                200,
                text=_recharge_paybill_page("bill-123", "ref-456", "csrf-token-789"),
            )
        if request.url.path.endswith("/payconfirm.json"):
            assert request.headers.get("X-CSRF-TOKEN") == "csrf-token-789"
            assert request.content == b"billno=bill-123&refno=ref-456"
            return httpx.Response(200, json={"retcode": "0", "retmsg": "ok"})
        raise AssertionError(f"unexpected request: {request.url}")

    monkeypatch.setattr(campus_card.config, "sues_base_url", "https://example.test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await campus_card.recharge_electricity(client, QUERY_PARAMS, 50.0)

    assert result == {
        "retcode": 0,
        "billno": "bill-123",
        "refno": "ref-456",
        "amount_yuan": 50.0,
    }
    assert [r.url.path for r in calls] == [
        "/epay/h5/eleresult",
        "/epay/h5/elepaybill",
        "/epay/h5/payconfirm.json",
    ]


@pytest.mark.asyncio
async def test_recharge_electricity_reports_insufficient_balance(monkeypatch):
    from nonebot_plugin_sues_bill import campus_card

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/eleresult"):
            return httpx.Response(200, text='<input id="roomdef" left-degree="1.0">')
        if request.url.path.endswith("/elepaybill"):
            return httpx.Response(
                200,
                text=_recharge_paybill_page("bill-1", "ref-2", "csrf-3"),
            )
        if request.url.path.endswith("/payconfirm.json"):
            return httpx.Response(200, json={"retcode": "-1", "retmsg": "账户余额不足"})
        raise AssertionError(f"unexpected request: {request.url}")

    monkeypatch.setattr(campus_card.config, "sues_base_url", "https://example.test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await campus_card.recharge_electricity(client, QUERY_PARAMS, 50.0)

    assert result == {"retcode": -1, "retmsg": "账户余额不足"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "<html>登录失效</html>",
        "<html>登陆失败，当前登录失效</html>",
        "<html>程序发生了错误，或无权限访问</html>",
        "<html>登录已过期</html>",
    ],
)
async def test_recharge_electricity_handles_expired_session(monkeypatch, body):
    from nonebot_plugin_sues_bill import campus_card

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/eleresult"):
            return httpx.Response(200, text='<input id="roomdef" left-degree="1.0">')
        return httpx.Response(200, text=body)

    monkeypatch.setattr(campus_card.config, "sues_base_url", "https://example.test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await campus_card.recharge_electricity(client, QUERY_PARAMS, 50.0)

    assert result == {"retcode": -1, "retmsg": "登录状态已过期，请重新设置校园卡账号"}


def test_parse_payment_args_rejects_invalid_amount():
    from nonebot_plugin_sues_bill import electric

    _, _, error = electric.parse_payment_args("三期 21 1001 abc")
    assert error is not None
    assert "金额格式错误" in error

    _, _, error = electric.parse_payment_args("三期 21 1001 0")
    assert error is not None
    assert "必须大于 0" in error

    _, _, error = electric.parse_payment_args("三期 21 1001 1000")
    assert error is not None
    assert "不能超过 999 元" in error


def test_parse_payment_args_accepts_room_and_amount():
    from nonebot_plugin_sues_bill import electric

    query_params, amount, error = electric.parse_payment_args("三期 21 1001 50")
    assert error is None
    assert query_params == QUERY_PARAMS
    assert amount == 50.0


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
        price_per_kwh=PRICE_PER_KWH,
    )
    record = save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 20),
        remaining_kwh=18,
        payment_amount_yuan=6.17,
        price_per_kwh=PRICE_PER_KWH,
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
        price_per_kwh=PRICE_PER_KWH,
    )
    record = save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 20),
        remaining_kwh=18,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
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
        price_per_kwh=PRICE_PER_KWH,
    )
    record = save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 20),
        remaining_kwh=25,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
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
        price_per_kwh=PRICE_PER_KWH,
    )
    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 18),
        remaining_kwh=18,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
    )
    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 19),
        remaining_kwh=13,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
    )

    statistics = get_usage_statistics(room_id, 30, date(2026, 7, 20))
    assert statistics == {
        "days": 30,
        "recorded_days": 2,
        "valid_days": 2,
        "complete_days": 0,
        "estimated_days": 2,
        "unavailable_days": 0,
        "total_kwh": 7.0,
        "total_cost_yuan": 4.31,
        "max_date": "2026-07-18",
        "max_kwh": 5.0,
    }


def test_recalculate_history_uses_verified_card_payments(room_id):
    from nonebot_plugin_sues_bill.models import (
        get_usage_statistics,
        recalculate_electricity_history,
        save_electricity_daily_snapshot,
    )

    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 17),
        remaining_kwh=20,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
    )
    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 18),
        remaining_kwh=18,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
    )
    save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 19),
        remaining_kwh=13,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
    )

    recalculated = recalculate_electricity_history(
        room_id,
        {date(2026, 7, 18): 6.17},
        PRICE_PER_KWH,
    )

    assert recalculated == 2
    statistics = get_usage_statistics(room_id, 30, date(2026, 7, 20))
    assert statistics["complete_days"] == 2
    assert statistics["estimated_days"] == 0
    assert statistics["total_kwh"] == 17.0


def test_cached_payment_records_keep_a_bill_sync_watermark(room_id):
    from nonebot_plugin_sues_bill.models import (
        save_electricity_payment_sync,
        get_electricity_payment_amount,
        get_latest_electricity_bill_at,
        save_electricity_payment_records,
    )

    paid_at = datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    save_electricity_payment_records(
        room_id,
        [
            {
                "source_key": "payment-1",
                "paid_at": paid_at.isoformat(),
                "amount_yuan": 6.17,
            }
        ],
    )
    save_electricity_payment_sync(room_id, paid_at)

    assert get_electricity_payment_amount(room_id, date(2026, 7, 18)) == 6.17
    assert get_latest_electricity_bill_at(room_id) == paid_at.astimezone(
        ZoneInfo("UTC")
    )


def test_record_statistics_accepts_compact_and_spaced_days():
    from nonebot_plugin_sues_bill.electric import parse_statistics_days

    assert parse_statistics_days("统计30天") == 30
    assert parse_statistics_days("统计 30天") == 30
    assert parse_statistics_days("统计7天") == 7
    assert parse_statistics_days("统计 7") == 7
    assert parse_statistics_days("统计 0") == 0
    assert parse_statistics_days("统计") == 30
    assert parse_statistics_days("查看") is None


def test_updated_bound_account_message_does_not_request_rebinding():
    from nonebot_plugin_sues_bill.campus_card import account_saved_message

    message = account_saved_message("20260001", has_bound_account=True)

    assert "原记录宿舍绑定已保留" in message
    assert "#电费 记录 绑定" not in message


def test_successful_queries_are_stored_without_daily_snapshot(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    room_id = models.record_electricity_query(QUERY_PARAMS, 20)
    models.record_electricity_query(QUERY_PARAMS, 18.5)

    queries = models.get_room_readings(room_id)
    assert [query["remaining_kwh"] for query in queries] == [18.5, 20.0]


def test_today_usage_is_estimated_from_first_and_latest_reading(room_id):
    from nonebot_plugin_sues_bill import models

    with models._connection() as connection:
        connection.executemany(
            """
            INSERT INTO room_readings(room_id, queried_at, remaining_kwh)
            VALUES (?, ?, ?)
            """,
            [
                (room_id, "2026-07-19 16:10:00", 20),
                (room_id, "2026-07-20 04:00:00", 18.5),
                (room_id, "2026-07-20 15:50:00", 17),
            ],
        )

    estimate = models.get_today_reading_estimate(
        room_id, date(2026, 7, 20), PRICE_PER_KWH
    )

    assert estimate == {
        "status": "estimated",
        "consumed_kwh": 3.0,
        "cost_yuan": 1.85,
    }


def test_today_usage_requires_two_readings(room_id):
    from nonebot_plugin_sues_bill import models

    with models._connection() as connection:
        connection.execute(
            """
            INSERT INTO room_readings(room_id, queried_at, remaining_kwh)
            VALUES (?, ?, ?)
            """,
            (room_id, "2026-07-20 04:00:00", 20),
        )

    estimate = models.get_today_reading_estimate(
        room_id, date(2026, 7, 20), PRICE_PER_KWH
    )

    assert estimate == {"status": "insufficient_readings", "reading_count": 1}


def test_today_usage_reports_unverified_recharge(room_id):
    from nonebot_plugin_sues_bill import models

    with models._connection() as connection:
        connection.executemany(
            """
            INSERT INTO room_readings(room_id, queried_at, remaining_kwh)
            VALUES (?, ?, ?)
            """,
            [
                (room_id, "2026-07-20 04:00:00", 20),
                (room_id, "2026-07-20 15:50:00", 25),
            ],
        )

    estimate = models.get_today_reading_estimate(
        room_id, date(2026, 7, 20), PRICE_PER_KWH
    )

    assert estimate == {"status": "recharge_unverified"}


def test_today_readings_do_not_affect_completed_day_statistics(room_id):
    from nonebot_plugin_sues_bill import models

    with models._connection() as connection:
        connection.executemany(
            """
            INSERT INTO room_readings(room_id, queried_at, remaining_kwh)
            VALUES (?, ?, ?)
            """,
            [
                (room_id, "2026-07-20 04:00:00", 20),
                (room_id, "2026-07-20 15:50:00", 17),
            ],
        )

    statistics = models.get_usage_statistics(room_id, 1, date(2026, 7, 20))

    assert statistics["valid_days"] == 0


def test_manual_entries_are_stored_in_shanghai_time_and_recalculate_usage(room_id):
    from nonebot_plugin_sues_bill import models

    shanghai_tz = ZoneInfo("Asia/Shanghai")
    models.record_manual_electricity_reading(
        QUERY_PARAMS,
        datetime(2026, 7, 20, 0, 0, tzinfo=shanghai_tz),
        18,
    )
    estimate = models.get_today_reading_estimate(
        room_id, date(2026, 7, 20), PRICE_PER_KWH
    )
    assert estimate == {"status": "insufficient_readings", "reading_count": 1}

    models.save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 19),
        remaining_kwh=20,
        payment_amount_yuan=None,
        price_per_kwh=PRICE_PER_KWH,
    )
    models.record_manual_electricity_payment(
        QUERY_PARAMS,
        datetime(2026, 7, 19, 12, 0, tzinfo=shanghai_tz),
        6.17,
    )
    payment_amount = models.get_manual_electricity_payment_amount(
        room_id, date(2026, 7, 19)
    )
    record = models.save_electricity_daily_snapshot(
        room_id,
        snapshot_date=date(2026, 7, 20),
        remaining_kwh=18,
        payment_amount_yuan=payment_amount,
        price_per_kwh=PRICE_PER_KWH,
        replace_usage=True,
    )

    assert payment_amount == 6.17
    assert record == {
        "status": "complete",
        "consumed_kwh": 12.0,
        "cost_yuan": 7.4,
        "payment_amount_yuan": 6.17,
    }


def test_room_description_masks_the_room_number():
    from nonebot_plugin_sues_bill.electric import describe_room

    assert describe_room(QUERY_PARAMS) == "三期2*栋1**1"


@pytest.mark.asyncio
async def test_daily_settlement_starts_all_rooms_without_stagger(monkeypatch):
    from nonebot_plugin_sues_bill import electric

    rooms = [
        {**QUERY_PARAMS, "room_id": 1},
        {**QUERY_PARAMS, "room_id": 2, "roomid": "1002"},
    ]
    settled_room_ids: list[int] = []

    async def unexpected_sleep(_: float) -> None:
        pytest.fail("日界结算不应再错峰等待")

    async def settle(room, snapshot_date):
        settled_room_ids.append(room["room_id"])

    monkeypatch.setattr(electric, "get_scheduled_rooms", lambda: rooms)
    monkeypatch.setattr(electric, "settle_room_electricity", settle)
    monkeypatch.setattr(electric.asyncio, "sleep", unexpected_sleep)

    await electric.settle_daily_electricity()

    assert settled_room_ids == [1, 2]


@pytest.mark.asyncio
async def test_daily_settlement_rebuilds_bound_room_history(monkeypatch):
    from nonebot_plugin_sues_bill import electric

    rebuilt_room_ids: list[int] = []

    async def query_bill(**_: str) -> dict[str, float | int]:
        return {"retcode": 0, "restElecDegree": 18.0}

    async def bound_amount(_: int, __: date) -> float:
        return 0.0

    async def rebuild_history(room_id: int) -> int:
        rebuilt_room_ids.append(room_id)
        return 2

    monkeypatch.setattr(electric, "query_electric_bill", query_bill)
    monkeypatch.setattr(electric, "query_bound_payment_amount", bound_amount)
    monkeypatch.setattr(
        electric, "get_manual_electricity_payment_amount", lambda *_: None
    )
    monkeypatch.setattr(electric, "record_electricity_query", lambda *_: 1)
    monkeypatch.setattr(
        electric, "save_electricity_daily_snapshot", lambda *_, **__: None
    )
    monkeypatch.setattr(electric, "recalculate_cached_history", rebuild_history)

    await electric.settle_room_electricity(
        {**QUERY_PARAMS, "room_id": 1}, date(2026, 7, 24)
    )

    assert rebuilt_room_ids == [1]


@pytest.mark.asyncio
async def test_statistics_refreshes_history_for_existing_bound_account(monkeypatch):
    from nonebot_plugin_sues_bill import electric

    refreshed_room_ids: list[int] = []

    async def refresh_history(room_id: int) -> tuple[int, None]:
        refreshed_room_ids.append(room_id)
        return 2, None

    monkeypatch.setattr(
        electric, "get_room_subscription", lambda _: {**QUERY_PARAMS, "room_id": 1}
    )
    monkeypatch.setattr(electric, "subscription_has_bound_account", lambda _: True)
    monkeypatch.setattr(electric, "recalculate_bound_history_detailed", refresh_history)
    monkeypatch.setattr(
        electric,
        "get_usage_statistics",
        lambda *_: {
            "recorded_days": 2,
            "valid_days": 2,
            "complete_days": 2,
            "estimated_days": 0,
            "unavailable_days": 0,
            "total_kwh": 12.9,
            "total_cost_yuan": 7.96,
            "max_date": "2026-07-23",
            "max_kwh": 10.3,
        },
    )

    message = await electric.show_statistics("1", 30)

    assert refreshed_room_ids == [1]
    assert "准确 2 天，估算 0 天" in message


@pytest.mark.asyncio
async def test_statistics_reports_failed_bound_history_refresh(monkeypatch):
    from nonebot_plugin_sues_bill import electric

    monkeypatch.setattr(
        electric, "get_room_subscription", lambda _: {**QUERY_PARAMS, "room_id": 1}
    )
    monkeypatch.setattr(electric, "subscription_has_bound_account", lambda _: True)

    async def failed_refresh(_: int) -> tuple[None, str]:
        return None, "校园卡登录失败"

    monkeypatch.setattr(electric, "recalculate_bound_history_detailed", failed_refresh)
    monkeypatch.setattr(
        electric,
        "get_usage_statistics",
        lambda *_: {
            "recorded_days": 1,
            "valid_days": 1,
            "complete_days": 0,
            "estimated_days": 1,
            "unavailable_days": 0,
            "total_kwh": 2.0,
            "total_cost_yuan": 1.23,
            "max_date": "2026-07-23",
            "max_kwh": 2.0,
        },
    )

    message = await electric.show_statistics("1", 30)

    assert "本次账单同步失败" in message
    assert "校园卡登录失败" in message


@pytest.mark.asyncio
async def test_statistics_reports_missing_boundary_snapshots(monkeypatch):
    from nonebot_plugin_sues_bill import electric

    monkeypatch.setattr(
        electric, "get_room_subscription", lambda _: {**QUERY_PARAMS, "room_id": 1}
    )
    monkeypatch.setattr(electric, "subscription_has_bound_account", lambda _: True)

    async def empty_refresh(_: int) -> tuple[int, None]:
        return 0, None

    monkeypatch.setattr(electric, "recalculate_bound_history_detailed", empty_refresh)
    monkeypatch.setattr(
        electric,
        "get_usage_statistics",
        lambda *_: {
            "recorded_days": 1,
            "valid_days": 1,
            "complete_days": 0,
            "estimated_days": 1,
            "unavailable_days": 0,
            "total_kwh": 2.0,
            "total_cost_yuan": 1.23,
            "max_date": "2026-07-23",
            "max_kwh": 2.0,
        },
    )

    message = await electric.show_statistics("1", 30)

    assert "账单同步成功" in message
    assert "缺少连续日界余额快照" in message


def test_recharge_bill_is_remembered_and_looked_up(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    models.set_room_subscription("1", QUERY_PARAMS)
    subscription = models.get_room_subscription("1")
    assert subscription is not None
    room_id = subscription["room_id"]

    assert models.get_recharge_bill_room("bill-xyz") is None
    models.record_recharge_bill("bill-xyz", room_id)
    assert models.get_recharge_bill_room("bill-xyz") == room_id


def test_synced_payments_route_to_owning_room(monkeypatch, tmp_path):
    from nonebot_plugin_sues_bill import models, electric

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    models.set_room_subscription("1", QUERY_PARAMS)
    bound_subscription = models.get_room_subscription("1")
    assert bound_subscription is not None
    bound_room = bound_subscription["room_id"]
    other_params = {**QUERY_PARAMS, "roomid": "2002"}
    models.set_room_subscription("2", other_params)
    other_subscription = models.get_room_subscription("2")
    assert other_subscription is not None
    other_room = other_subscription["room_id"]
    models.record_recharge_bill("bill-for-other", other_room)

    records = [
        {
            "source_key": "a" * 64,
            "billno": "bill-for-other",
            "paid_at": "2026-08-04T10:00:00+08:00",
            "amount_yuan": 50.0,
        },
        {
            "source_key": "b" * 64,
            "billno": "unknown-bill",
            "paid_at": "2026-08-04T11:00:00+08:00",
            "amount_yuan": 30.0,
        },
    ]
    electric.route_synced_payment_records(bound_room, records)

    assert models.get_electricity_payment_amount(other_room, date(2026, 8, 4)) == 50.0
    assert models.get_electricity_payment_amount(bound_room, date(2026, 8, 4)) == 30.0


def test_synced_payments_remove_manual_copy_from_owning_room(monkeypatch, tmp_path):
    from datetime import datetime

    from nonebot_plugin_sues_bill import models, electric

    monkeypatch.setattr(models, "DATA_DIR", tmp_path / "nonebot_plugin_sues_bill")
    monkeypatch.setattr(models, "LEGACY_DATA_DIR", tmp_path / "data")
    models.set_room_subscription("1", QUERY_PARAMS)
    subscription = models.get_room_subscription("1")
    assert subscription is not None
    room_id = subscription["room_id"]
    paid_at = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    models.record_manual_electricity_payment(QUERY_PARAMS, paid_at, 50.0)
    assert (
        models.get_manual_electricity_payment_amount(room_id, date(2026, 8, 4)) == 50.0
    )

    electric.route_synced_payment_records(
        room_id,
        [
            {
                "source_key": "c" * 64,
                "billno": "confirmed-bill",
                "paid_at": paid_at.isoformat(),
                "amount_yuan": 50.0,
            }
        ],
    )

    assert (
        models.get_manual_electricity_payment_amount(room_id, date(2026, 8, 4)) is None
    )
