import re
import asyncio
from datetime import date, time, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from nonebot import logger, require, get_driver, on_command, get_plugin_config
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, Event

from .config import USER_AGENT, REQUEST_TIMEOUT, ELECTRIC_QUERY_PATH, Config
from .models import (
    get_scheduled_rooms,
    get_usage_statistics,
    get_room_subscription,
    set_room_subscription,
    stop_room_subscription,
    get_electricity_snapshot,
    record_electricity_query,
    get_today_reading_estimate,
    bind_account_to_subscription,
    save_electricity_payment_sync,
    get_electricity_payment_amount,
    get_latest_electricity_bill_at,
    subscription_has_bound_account,
    get_electricity_payment_amounts,
    recalculate_electricity_history,
    save_electricity_daily_snapshot,
    save_electricity_payment_records,
    unbind_account_from_subscription,
    record_manual_electricity_payment,
    record_manual_electricity_reading,
    get_manual_electricity_payment_amount,
)
from .campus_card import (
    login,
    load_account,
    load_bound_accounts,
    recharge_electricity,
    query_electric_payment_records,
)

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

config = get_plugin_config(Config)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
MAX_STATISTICS_DAYS = 3650

AREA_MAP = {
    "三期": ("4", "101"),
    "四期": ("4", "102"),
}

BUILD_MAP = {
    ("三期", "10"): "2",
    ("三期", "11"): "3",
    ("三期", "12"): "4",
    ("三期", "13"): "5",
    ("三期", "14"): "6",
    ("三期", "15"): "7",
    ("三期", "16"): "8",
    ("三期", "17"): "9",
    ("三期", "18"): "10",
    ("三期", "19"): "11",
    ("三期", "20"): "12",
    ("三期", "21"): "13",
    ("三期", "22"): "14",
    ("三期", "23"): "15",
    ("三期", "24"): "16",
    ("三期", "25"): "17",
    ("三期", "26"): "18",
    ("四期", "20"): "19",
    ("四期", "21"): "20",
    ("四期", "23"): "21",
    ("四期", "24"): "22",
    ("四期", "27"): "23",
    ("四期", "28"): "24",
    ("四期", "29"): "25",
    ("四期", "30"): "26",
    ("四期", "33"): "27",
    ("四期", "34"): "28",
    ("四期", "35"): "29",
    ("四期", "36"): "30",
    ("四期", "39"): "31",
    ("四期", "40"): "32",
    ("四期", "41"): "33",
    ("四期", "42"): "34",
}


def parse_room_params(arg_text: str) -> tuple[dict[str, str] | None, str | None]:
    parts = arg_text.split()
    if len(parts) != 3:
        return None, "格式：#电费 区域 楼栋 房间号\n例：#电费 三期 21 1001"
    area_name, build_num, room_id = parts
    if area_name not in AREA_MAP:
        return None, f"不支持的区域，目前支持：{'、'.join(AREA_MAP)}"
    if (area_name, build_num) not in BUILD_MAP:
        return None, f"{area_name}没有{build_num}栋"
    if not room_id.isdigit() or len(room_id) != 4:
        return None, "房间号应为4位数字，如1001"
    sysid, areaid = AREA_MAP[area_name]
    return {
        "sysid": sysid,
        "roomid": room_id,
        "areaid": areaid,
        "buildid": BUILD_MAP[(area_name, build_num)],
    }, None


def describe_room(query_params: dict[str, str]) -> str:
    area_name = next(
        (
            name
            for name, (_, area_id) in AREA_MAP.items()
            if area_id == query_params["areaid"]
        ),
        "未知区域",
    )
    build_num = next(
        (
            building
            for (area, building), build_id in BUILD_MAP.items()
            if area == area_name and build_id == query_params["buildid"]
        ),
        "?",
    )
    masked_building = f"{build_num[:-1]}*" if build_num != "?" else "*"
    room_id = query_params["roomid"]
    masked_room = (
        f"{room_id[0]}{'*' * (len(room_id) - 2)}{room_id[-1]}"
        if len(room_id) > 2
        else room_id
    )
    return f"{area_name}{masked_building}栋{masked_room}"


async def query_electric_bill(sysid: str, roomid: str, areaid: str, buildid: str):
    """查询宿舍电费信息。"""
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        ) as client:
            response = await client.get(
                config.sues_base_url + ELECTRIC_QUERY_PATH,
                params={
                    "sysid": sysid,
                    "roomid": roomid,
                    "areaid": areaid,
                    "buildid": buildid,
                },
            )
            response.raise_for_status()
            match = re.search(r"(\d+\.?\d*)\s*度", response.text)
            if match:
                return {"retcode": 0, "restElecDegree": float(match.group(1))}
            return {"retcode": -1, "retmsg": "未找到剩余电量信息"}
    except httpx.TimeoutException:
        logger.error("电费查询超时")
        return {"retcode": -1, "retmsg": "查询超时"}
    except Exception as error:
        logger.error(f"电费查询异常: {error}")
        return {"retcode": -1, "retmsg": f"错误: {error}"}


electric_query = on_command("电费", priority=5, block=True)
electric_raw = on_command("电费原始", priority=5, block=True)
electric_help = on_command("电费帮助", priority=5, block=True)
electric_help_detail = on_command("电费详细帮助", priority=5, block=True)


async def query_bound_payment_amount(room_id: int, target_date: date) -> float | None:
    """Return all explicitly bound account payments, or None if verification fails."""
    if not await sync_bound_payment_records(room_id):
        return None
    return await asyncio.to_thread(get_electricity_payment_amount, room_id, target_date)


async def sync_bound_payment_records(room_id: int) -> bool:
    """Incrementally cache the bound account's verified electricity payments."""
    return await _sync_bound_payment_records(room_id) is None


async def _sync_bound_payment_records(room_id: int) -> str | None:
    """Cache payment records and return a privacy-safe failure reason."""
    accounts = await asyncio.to_thread(load_bound_accounts, room_id)
    if not accounts:
        return "未找到可用于校正的绑定账户"

    latest_bill_at = await asyncio.to_thread(get_latest_electricity_bill_at, room_id)
    for account in accounts:
        client = await login(account["username"], account["password"])
        if client is None:
            logger.warning(f"宿舍 {room_id} 的绑定校园卡登录失败")
            return "校园卡登录失败"
        try:
            result = await query_electric_payment_records(client, latest_bill_at)
        finally:
            await client.aclose()
        if result.get("retcode") != 0:
            logger.warning(f"宿舍 {room_id} 的绑定校园卡流水查询失败")
            return str(result.get("retmsg", "账单查询失败"))
        await asyncio.to_thread(
            save_electricity_payment_records, room_id, result["records"]
        )
        if result["latest_bill_at"] is not None:
            await asyncio.to_thread(
                save_electricity_payment_sync,
                room_id,
                datetime.fromisoformat(result["latest_bill_at"]),
            )
    return None


async def query_total_payment_amount(room_id: int, target_date: date) -> float | None:
    """Combine verified campus-card and administrator-entered payments."""
    bound_amount = await query_bound_payment_amount(room_id, target_date)
    manual_amount = await asyncio.to_thread(
        get_manual_electricity_payment_amount, room_id, target_date
    )
    if bound_amount is None:
        return manual_amount
    if manual_amount is None:
        return bound_amount
    return round(bound_amount + manual_amount, 2)


async def recalculate_bound_history(room_id: int) -> int | None:
    """Recalculate every stored day when its bound card history is verified."""
    recalculated_days, _ = await recalculate_bound_history_detailed(room_id)
    return recalculated_days


async def recalculate_bound_history_detailed(
    room_id: int,
) -> tuple[int | None, str | None]:
    """Recalculate history and retain a privacy-safe sync failure reason."""
    sync_error = await _sync_bound_payment_records(room_id)
    if sync_error is not None:
        return None, sync_error
    return await recalculate_cached_history(room_id), None


async def recalculate_cached_history(room_id: int) -> int:
    """Rebuild stored usage rows from cached payments and balance snapshots."""
    amounts = await asyncio.to_thread(get_electricity_payment_amounts, room_id)
    return await asyncio.to_thread(
        recalculate_electricity_history,
        room_id,
        amounts,
        config.electricity_price_per_kwh,
    )


async def settle_room_electricity(room: dict[str, object], snapshot_date: date) -> None:
    """Create one room boundary snapshot and settle its prior natural day."""
    query_params = {
        key: str(room[key]) for key in ("sysid", "roomid", "areaid", "buildid")
    }
    result = await query_electric_bill(**query_params)
    if result.get("retcode") != 0:
        logger.warning(f"宿舍 {room['room_id']} 的日界电费查询失败")
        return

    room_id = int(str(room["room_id"]))
    target_date = snapshot_date - timedelta(days=1)
    bound_amount = await query_bound_payment_amount(room_id, target_date)
    manual_amount = await asyncio.to_thread(
        get_manual_electricity_payment_amount, room_id, target_date
    )
    if bound_amount is None:
        payment_amount_yuan = manual_amount
    elif manual_amount is None:
        payment_amount_yuan = bound_amount
    else:
        payment_amount_yuan = round(bound_amount + manual_amount, 2)
    await asyncio.to_thread(
        record_electricity_query,
        query_params,
        float(result["restElecDegree"]),
    )
    await asyncio.to_thread(
        save_electricity_daily_snapshot,
        room_id,
        snapshot_date=snapshot_date,
        remaining_kwh=float(result["restElecDegree"]),
        payment_amount_yuan=payment_amount_yuan,
        price_per_kwh=config.electricity_price_per_kwh,
    )
    if bound_amount is not None:
        await recalculate_cached_history(room_id)


@scheduler.scheduled_job(
    "cron", hour=0, minute=0, timezone="Asia/Shanghai", id="sues_daily_electricity"
)
async def settle_daily_electricity() -> None:
    """Settle all subscribed rooms immediately at the date boundary."""
    snapshot_date = datetime.now(SHANGHAI_TZ).date()
    rooms = await asyncio.to_thread(get_scheduled_rooms)
    await asyncio.gather(
        *(settle_room_electricity(room, snapshot_date) for room in rooms),
        return_exceptions=True,
    )


def record_help() -> str:
    return (
        "电费记录命令\n\n"
        "#电费 记录 区域 楼栋 房间号\n"
        "#电费 统计 0（今日截至当前估算）\n"
        "#电费 统计 [天数]（已结束自然日）\n"
        "#电费 记录 状态 / 停止\n"
        "#电费 记录 绑定 / 解绑\n"
        "#电费 管理 - 管理员手动录入"
    )


def account_correction_tip(
    has_bound_account: bool,
    history_sync_succeeded: bool | None = None,
    recalculated_days: int | None = None,
    remaining_estimated_days: int = 0,
    history_sync_error: str | None = None,
) -> str:
    if has_bound_account:
        if history_sync_succeeded is False:
            return (
                "账户校正：已绑定校园卡账户，但本次账单同步失败"
                f"（{history_sync_error or '未知原因'}），"
                "历史记录尚未校正。\n请稍后重新统计；管理员可查看机器人日志。"
            )
        if history_sync_succeeded and remaining_estimated_days > 0:
            return (
                "账户校正：账单同步成功，"
                f"已重算 {recalculated_days or 0} 天；仍有"
                f" {remaining_estimated_days} 天缺少连续日界余额快照，保留估算。"
            )
        return (
            "账户校正：已绑定校园卡账户，历史及后续记录会按流水校正。\n"
            "前提：该校园卡仅给此宿舍缴费，且此宿舍仅由该校园卡缴费。"
        )
    return (
        "账户校正：未绑定，缴费日可能不准确。\n"
        "如需校正，请先私聊发送 #设置校园卡账号 学号 密码，"
        "再发送 #电费 记录 绑定；校正前提是一卡一房、该卡仅为该房缴费。"
    )


async def get_record_status_message(user_id: str) -> str:
    subscription = await asyncio.to_thread(get_room_subscription, user_id)
    if subscription is None:
        return "当前未设置记录宿舍"
    has_account = await asyncio.to_thread(subscription_has_bound_account, user_id)
    return (
        f"记录宿舍：{describe_room(subscription)}\n"
        f"{account_correction_tip(has_account)}"
    )


def parse_statistics_days(arguments: str) -> int | None:
    match = re.fullmatch(r"统计\s*(?:(\d+)\s*天?)?", arguments)
    if match is None:
        return None
    return int(match.group(1) or 30)


async def handle_record_command(user_id: str, arguments: str) -> str:
    action, _, payload = arguments.partition(" ")
    payload = payload.strip()
    if not action:
        return record_help()
    if action in AREA_MAP:
        query_params, error = parse_room_params(arguments)
        if error:
            return error.replace("#电费", "#电费 记录")
        assert query_params is not None
        await asyncio.to_thread(set_room_subscription, user_id, query_params)
        return (
            f"已设置记录宿舍：{describe_room(query_params)}\n"
            "每天 00:00 会查询并结算昨日耗电。\n"
            "如需缴费日精确校正，请先私聊设置校园卡账号，再发送 #电费 记录 绑定。\n"
            "校正前提：绑定卡仅为本宿舍缴费，且本宿舍仅由此卡缴费。"
        )
    if action == "状态":
        return await get_record_status_message(user_id)
    if action == "停止":
        stopped = await asyncio.to_thread(stop_room_subscription, user_id)
        return (
            "已停止定时电费查询，历史记录会保留。"
            if stopped
            else "当前没有启用的记录宿舍。"
        )
    if action == "绑定":
        result = await asyncio.to_thread(bind_account_to_subscription, user_id)
        if result == "bound":
            subscription = await asyncio.to_thread(get_room_subscription, user_id)
            assert subscription is not None
            recalculated_days = await recalculate_bound_history(subscription["room_id"])
            correction_note = (
                f"已按账单流水校正 {recalculated_days} 天历史记录。"
                if recalculated_days is not None
                else "暂未能读取账单流水，历史记录会在下次成功绑定时校正。"
            )
            return (
                "已绑定校园卡账户到记录宿舍。\n"
                f"{correction_note}\n"
                "校正前提：该账户仅给此宿舍缴费，且此宿舍仅由该账户缴费。"
            )
        messages = {
            "no_subscription": "请先设置记录宿舍：#电费 记录 三期 21 1001",
            "no_account": "请先私聊设置校园卡账号：#设置校园卡账号 学号 密码",
            "room_bound": "该记录宿舍已绑定其他校园卡账户，请先由原账户解绑。",
        }
        return messages[result]
    if action == "解绑":
        unbound = await asyncio.to_thread(unbind_account_from_subscription, user_id)
        return (
            "已解绑校园卡账户，后续缴费日将无法精确校正。"
            if unbound
            else "当前没有绑定校园卡账户。"
        )
    return record_help()


def parse_payment_args(
    arguments: str,
) -> tuple[dict[str, str] | None, float | None, str | None]:
    parts = arguments.split()
    if len(parts) != 4:
        return (
            None,
            None,
            "格式：#电费 缴费 区域 楼栋 房间号 金额\n例：#电费 缴费 三期 21 1001 50",
        )
    query_params, error = parse_room_params(" ".join(parts[:3]))
    if error:
        return None, None, error.replace("#电费", "#电费 缴费")
    amount_text = parts[3]
    if not amount_text.isdigit():
        return None, None, f"金额格式错误：{amount_text}"
    amount = int(amount_text)
    if amount <= 0:
        return None, None, "缴费金额必须大于 0。"
    if amount > 999:
        return None, None, "单次缴费金额不能超过 999 元。"
    return query_params, float(amount), None


async def handle_payment_command(user_id: str, arguments: str) -> str:
    query_params, amount, error = parse_payment_args(arguments)
    if error:
        return error
    assert query_params is not None
    assert amount is not None

    account = await asyncio.to_thread(load_account, user_id)
    if not account:
        return (
            "尚未设置校园卡账号。\n"
            "请先私聊发送 #设置校园卡账号 学号 密码，"
            "缴费将从该校园卡余额中直接扣除。"
        )

    client = await login(account["username"], account["password"])
    if client is None:
        return "校园卡登录失败，请检查账号密码或稍后重试。"
    try:
        result = await recharge_electricity(client, query_params, amount)
    finally:
        await client.aclose()

    if result.get("retcode") == 0:
        return (
            f"缴费成功：{describe_room(query_params)} 充值 {amount:.2f} 元\n"
            f"已从校园卡余额扣除。"
        )
    return f"缴费失败：{result.get('retmsg', '未知错误')}"


def parse_admin_entry(
    arguments: str,
) -> tuple[str, dict[str, str], datetime, float] | str:
    """Parse an administrator's dated meter reading or payment entry."""
    parts = arguments.split()
    if not parts or parts[0] not in {"读数", "缴费"}:
        return admin_help()
    if len(parts) not in {6, 7}:
        return "格式：#电费 管理 读数/缴费 区域 楼栋 房间号 日期 [时间] 数值"
    action = parts[0]
    query_params, error = parse_room_params(" ".join(parts[1:4]))
    if error:
        return error.replace("#电费", "#电费 管理")
    assert query_params is not None
    try:
        entry_date = date.fromisoformat(parts[4])
        entry_time = time.fromisoformat(parts[5]) if len(parts) == 7 else time.min
        amount = float(parts[-1])
    except ValueError:
        return "日期应为 YYYY-MM-DD，时间应为 HH:MM，数值应为正数。"
    if amount < 0 or (action == "缴费" and amount == 0):
        return "读数不能小于 0，缴费金额必须大于 0。"
    entered_at = datetime.combine(entry_date, entry_time, SHANGHAI_TZ)
    return action, query_params, entered_at, amount


def admin_help() -> str:
    return (
        "管理员电费录入命令\n\n"
        "#电费 管理 读数 区域 楼栋 房间号 日期 [时间] 剩余电量\n"
        "#电费 管理 缴费 区域 楼栋 房间号 日期 [时间] 金额\n"
        "日期格式：YYYY-MM-DD；时间可省略，默认为 00:00。"
    )


async def handle_admin_command(user_id: str, arguments: str) -> str:
    if user_id not in get_driver().config.superusers:
        return "仅机器人管理员可使用电费管理命令。"
    entry = parse_admin_entry(arguments)
    if isinstance(entry, str):
        return entry
    action, query_params, entered_at, amount = entry
    if action == "读数":
        room_id = await asyncio.to_thread(
            record_manual_electricity_reading, query_params, entered_at, amount
        )
    else:
        room_id = await asyncio.to_thread(
            record_manual_electricity_payment, query_params, entered_at, amount
        )
    entry_date = entered_at.date()
    if action == "读数":
        payment_amount = await query_total_payment_amount(
            room_id, entry_date - timedelta(days=1)
        )
        record = await asyncio.to_thread(
            save_electricity_daily_snapshot,
            room_id,
            snapshot_date=entry_date,
            remaining_kwh=amount,
            payment_amount_yuan=payment_amount,
            price_per_kwh=config.electricity_price_per_kwh,
            replace_usage=True,
        )
        settlement_message = "已重算前一日耗电。"
        if record is None:
            settlement_message = "已保存读数，尚缺前一日读数，暂无法结算。"
        return (
            f"已录入 {describe_room(query_params)} 在"
            f" {entered_at:%Y-%m-%d %H:%M} 的剩余电量：{amount} 度。\n"
            f"{settlement_message}"
        )
    next_snapshot = await asyncio.to_thread(
        get_electricity_snapshot, room_id, entry_date + timedelta(days=1)
    )
    if next_snapshot is None:
        return (
            f"已录入 {describe_room(query_params)} 在"
            f" {entered_at:%Y-%m-%d %H:%M} 的缴费：{amount:.2f} 元。\n"
            "次日读数生成后会自动参与该日结算。"
        )
    payment_amount = await query_total_payment_amount(room_id, entry_date)
    record = await asyncio.to_thread(
        save_electricity_daily_snapshot,
        room_id,
        snapshot_date=entry_date + timedelta(days=1),
        remaining_kwh=next_snapshot,
        payment_amount_yuan=payment_amount,
        price_per_kwh=config.electricity_price_per_kwh,
        replace_usage=True,
    )
    return (
        f"已录入 {describe_room(query_params)} 在"
        f" {entered_at:%Y-%m-%d %H:%M} 的缴费：{amount:.2f} 元。\n"
        f"{'已重算该日耗电。' if record is not None else '已保存缴费记录。'}"
    )


async def show_statistics(user_id: str, days: int) -> str:
    subscription = await asyncio.to_thread(get_room_subscription, user_id)
    if subscription is None:
        return "未设置记录宿舍，请先发送：#电费 记录 三期 21 1001"
    has_bound_account = await asyncio.to_thread(subscription_has_bound_account, user_id)
    if days == 0:
        correction_tip = account_correction_tip(has_bound_account)
        query_params = {
            key: str(subscription[key])
            for key in ("sysid", "roomid", "areaid", "buildid")
        }
        result = await query_electric_bill(**query_params)
        if result.get("retcode") != 0:
            return f"查询当前电费失败：{result.get('retmsg', '未知错误')}"
        await asyncio.to_thread(
            record_electricity_query,
            query_params,
            float(result["restElecDegree"]),
        )
        estimate = await asyncio.to_thread(
            get_today_reading_estimate,
            subscription["room_id"],
            datetime.now(SHANGHAI_TZ).date(),
            config.electricity_price_per_kwh,
        )
        if estimate["status"] == "insufficient_readings":
            return (
                f"{describe_room(subscription)}今日截至当前暂无可估算的耗电记录。\n"
                f"今日已记录 {estimate['reading_count']} 次，至少需要两次成功查询。\n"
                f"{correction_tip}"
            )
        if estimate["status"] == "recharge_unverified":
            return (
                f"{describe_room(subscription)}今日截至当前无法估算耗电。\n"
                f"检测到余额增加，今日可能已缴费。\n{correction_tip}"
            )
        return (
            f"{describe_room(subscription)}今日截至当前耗电（估算）\n"
            f"耗电：{estimate['consumed_kwh']} 度\n"
            f"电费：{estimate['cost_yuan']:.2f} 元\n"
            f"按今日首次和最新查询余额计算；缴费后可能不准确。\n{correction_tip}"
        )
    recalculated_days: int | None = None
    history_sync_error: str | None = None
    if has_bound_account:
        (
            recalculated_days,
            history_sync_error,
        ) = await recalculate_bound_history_detailed(subscription["room_id"])
    statistics = await asyncio.to_thread(
        get_usage_statistics,
        subscription["room_id"],
        days,
        datetime.now(SHANGHAI_TZ).date(),
    )
    correction_tip = account_correction_tip(
        has_bound_account,
        recalculated_days is not None if has_bound_account else None,
        recalculated_days,
        statistics["estimated_days"],
        history_sync_error,
    )
    if statistics["valid_days"] == 0:
        return (
            f"已记录 {statistics['recorded_days']} 天，但暂无可统计的耗电记录。\n"
            f"{correction_tip}"
        )
    average = statistics["total_kwh"] / statistics["valid_days"]
    status_summary = (
        f"准确 {statistics['complete_days']} 天，"
        f"估算 {statistics['estimated_days']} 天，"
        f"未计入 {statistics['unavailable_days']} 天"
    )
    return (
        f"{describe_room(subscription)}已记录"
        f" {statistics['recorded_days']} 天耗电统计\n"
        f"总耗电：{statistics['total_kwh']} 度\n"
        f"总电费：{statistics['total_cost_yuan']:.2f} 元\n"
        f"日均耗电：{average:.2f} 度（{statistics['valid_days']}天）\n"
        f"最高耗电：{statistics['max_date']}，{statistics['max_kwh']} 度\n"
        f"{status_summary}\n"
        f"{correction_tip}"
    )


@electric_query.handle()
async def handle_electric_query(
    bot: Bot, event: Event, args: Message = CommandArg()
) -> None:
    user_id = event.get_user_id()
    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        subscription = await asyncio.to_thread(get_room_subscription, user_id)
        if subscription is None:
            await electric_query.finish("请先设置记录宿舍：#电费 记录 三期 21 1001")
        query_params = {
            key: str(subscription[key])
            for key in ("sysid", "roomid", "areaid", "buildid")
        }
    elif arg_text == "管理" or arg_text.startswith("管理 "):
        arguments = arg_text.removeprefix("管理").strip()
        await electric_query.finish(await handle_admin_command(user_id, arguments))
    elif arg_text == "记录" or arg_text.startswith("记录 "):
        arguments = arg_text.removeprefix("记录").strip()
        await electric_query.finish(await handle_record_command(user_id, arguments))
    elif arg_text == "缴费" or arg_text.startswith("缴费 "):
        arguments = arg_text.removeprefix("缴费").strip()
        await electric_query.finish(await handle_payment_command(user_id, arguments))
    elif (days := parse_statistics_days(arg_text)) is not None:
        if not 0 <= days <= MAX_STATISTICS_DAYS:
            await electric_query.finish(f"统计天数应为 0 或 1 到 {MAX_STATISTICS_DAYS}")
        await electric_query.finish(await show_statistics(user_id, days))
    else:
        query_params, error = parse_room_params(arg_text)
        if error:
            await electric_query.finish(error)
    assert query_params is not None
    result = await query_electric_bill(**query_params)
    if result.get("retcode") == 0:
        await asyncio.to_thread(
            record_electricity_query,
            query_params,
            float(result["restElecDegree"]),
        )
        await electric_query.finish(f"剩余电量: {result['restElecDegree']} 度")
    await electric_query.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@electric_raw.handle()
async def handle_electric_raw(
    bot: Bot, event: Event, args: Message = CommandArg()
) -> None:
    parts = args.extract_plain_text().strip().split()
    if len(parts) < 4:
        await electric_raw.finish("格式：#电费原始 sysid roomid areaid buildid")
    result = await query_electric_bill(*parts[:4])
    if result.get("retcode") == 0:
        query_params: dict[str, str] = {
            "sysid": parts[0],
            "roomid": parts[1],
            "areaid": parts[2],
            "buildid": parts[3],
        }
        await asyncio.to_thread(
            record_electricity_query,
            query_params,
            float(result["restElecDegree"]),
        )
        await electric_raw.finish(f"剩余电量: {result['restElecDegree']} 度")
    await electric_raw.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@electric_help.handle()
async def handle_electric_help(
    bot: Bot, event: Event, args: Message = CommandArg()
) -> None:
    await electric_help.finish(
        "电费查询帮助\n\n"
        "#电费 - 查询记录宿舍当前余额\n"
        "#电费 区域 楼栋 房间号 - 即时查询余额\n"
        "#电费 缴费 区域 楼栋 房间号 金额 - 从校园卡余额充值电费\n\n"
        f"{record_help()}\n\n"
        "定时日结在每日 00:00 执行；绑定账户后可用缴费流水校正历史及后续记录。\n"
        "校正前提：该校园卡只给这一间宿舍缴费，且该宿舍只由这张卡缴费。\n"
        "三期：10-26栋；四期：20、21、23、24、27-30、33-36、39-42栋"
    )


@electric_help_detail.handle()
async def handle_electric_help_detail(
    bot: Bot, event: Event, args: Message = CommandArg()
) -> None:
    await electric_help_detail.finish(
        "电费原始查询帮助\n\n"
        "格式：#电费原始 系统ID 房间号 区域ID 楼栋ID\n"
        "例：#电费原始 4 1001 101 13\n\n"
        "系统ID：4 = 上海工程技术大学电控充值\n"
        "区域ID：101 = 三期学生公寓，102 = 四期学生公寓"
    )
