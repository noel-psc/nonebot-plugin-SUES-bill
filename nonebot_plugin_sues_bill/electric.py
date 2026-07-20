import re
import asyncio
from hashlib import sha256
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from nonebot import logger, require, on_command, get_plugin_config
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, Event

from .config import USER_AGENT, REQUEST_TIMEOUT, ELECTRIC_QUERY_PATH, Config
from .models import (
    get_user_file,
    load_user_data,
    save_user_data,
    get_electricity_user_ids,
    save_electricity_daily_snapshot,
)
from .campus_card import (
    login,
    load_account,
    query_electric_payment_amount,
)

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

config = get_plugin_config(Config)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
MAX_SCHEDULED_QUERIES = 10
SETTLEMENT_WINDOW_SECONDS = 20 * 60

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


async def query_electric_bill(
    sysid: str, roomid: str, areaid: str, buildid: str
):
    """查询宿舍电费信息"""
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        ) as client:
            resp = await client.get(
                config.sues_base_url + ELECTRIC_QUERY_PATH,
                params={
                    "sysid": sysid,
                    "roomid": roomid,
                    "areaid": areaid,
                    "buildid": buildid,
                },
            )
            resp.raise_for_status()
            match = re.search(r"(\d+\.?\d*)\s*度", resp.text)
            if match:
                return {"retcode": 0, "restElecDegree": float(match.group(1))}
            return {"retcode": -1, "retmsg": "未找到剩余电量信息"}
    except httpx.TimeoutException:
        logger.error("电费查询超时")
        return {"retcode": -1, "retmsg": "查询超时"}
    except Exception as e:
        logger.error(f"电费查询异常: {e}")
        return {"retcode": -1, "retmsg": f"错误: {e}"}


electric_query = on_command("电费", priority=5, block=True)
electric_raw = on_command("电费原始", priority=5, block=True)
electric_help = on_command("电费帮助", priority=5, block=True)
electric_help_detail = on_command("电费详细帮助", priority=5, block=True)
electric_clear = on_command("清除电费设置", priority=5, block=True)
electric_yesterday_usage = on_command("昨日耗电", priority=5, block=True)


def get_settlement_delay_seconds(user_id: str) -> int:
    """为用户分配稳定的 23:50 至 00:10 错峰时段。"""
    digest = sha256(user_id.encode()).digest()
    return int.from_bytes(digest[:4], "big") % (SETTLEMENT_WINDOW_SECONDS + 1)


async def settle_user_electricity(user_id: str, snapshot_date: date):
    """在日界采样指定用户的电量，并结算前一自然日。"""
    data = await asyncio.to_thread(load_user_data, user_id)
    query_params = data.get("query_params")
    if not query_params:
        return

    result = await query_electric_bill(**query_params)
    if result.get("retcode") != 0:
        logger.warning(f"用户 {user_id} 的日界电费查询失败")
        return

    payment_amount_yuan = None
    account = await asyncio.to_thread(load_account, user_id)
    if account:
        client = await login(account["username"], account["password"])
        if client:
            try:
                payment_result = await query_electric_payment_amount(
                    client, snapshot_date - timedelta(days=1)
                )
                if payment_result.get("retcode") == 0:
                    payment_amount_yuan = payment_result["amount"]
            finally:
                await client.aclose()

    save_electricity_daily_snapshot(
        data,
        snapshot_date=snapshot_date,
        query_params=query_params,
        remaining_kwh=result["restElecDegree"],
        payment_amount_yuan=payment_amount_yuan,
        price_per_kwh=config.electricity_price_per_kwh,
    )
    await asyncio.to_thread(save_user_data, user_id, data)


@scheduler.scheduled_job(
    "cron", hour=23, minute=50, timezone="Asia/Shanghai", id="sues_daily_electricity"
)
async def settle_daily_electricity():
    """在每日 00:00 前后十分钟错峰创建日界快照。"""
    snapshot_date = (datetime.now(SHANGHAI_TZ) + timedelta(minutes=10)).date()
    user_ids = await asyncio.to_thread(get_electricity_user_ids)

    semaphore = asyncio.Semaphore(MAX_SCHEDULED_QUERIES)

    async def settle_with_limit(user_id: str):
        await asyncio.sleep(get_settlement_delay_seconds(user_id))
        async with semaphore:
            await settle_user_electricity(user_id, snapshot_date)

    await asyncio.gather(
        *(settle_with_limit(user_id) for user_id in user_ids),
        return_exceptions=True,
    )


@electric_yesterday_usage.handle()
async def handle_electric_yesterday_usage(
    bot: Bot, event: Event, args: Message = CommandArg()
):
    """展示由日界快照结算得到的昨日耗电。"""
    user_id = event.get_user_id()
    yesterday = (datetime.now(SHANGHAI_TZ) - timedelta(days=1)).date().isoformat()
    daily = load_user_data(user_id).get("electricity_usage", {}).get("daily", {})
    record = daily.get(yesterday)
    if not record:
        await electric_yesterday_usage.finish(
            "暂无昨日耗电记录。请先使用 #电费 保存宿舍，"
            "系统会在每日 00:00 前后自动采样。"
        )

    status = record.get("status")
    if status == "estimated_recharge_detected":
        await electric_yesterday_usage.finish(
            "⚠️ 昨日剩余电量增加，可能发生电费缴费；未绑定校园卡，无法准确计算昨日耗电。"
        )
    if status == "calculation_error":
        await electric_yesterday_usage.finish(
            "⚠️ 昨日耗电数据校验失败，请检查校园卡缴费记录后等待下一次日结。"
        )

    prefix = "⚠️ 估算值（缴费记录不可用）\n" if status == "estimated" else ""
    await electric_yesterday_usage.finish(
        f"{prefix}昨日耗电：{record['consumed_kwh']} 度\n"
        f"昨日电费：{record['cost_yuan']:.2f} 元"
    )


@electric_query.handle()
async def handle_electric_query(bot: Bot, event: Event, args: Message = CommandArg()):
    user_id = event.get_user_id()
    data = load_user_data(user_id)
    arg_text = args.extract_plain_text().strip()

    if arg_text:
        parts = arg_text.split()
        if len(parts) < 3:
            await electric_query.finish(
                "格式：#电费 区域 楼栋 房间号\n例：#电费 三期 21 1001"
            )
        area_name, build_num, room_id = parts[0], parts[1], parts[2]
        if area_name not in AREA_MAP:
            await electric_query.finish(
                f"不支持的区域，目前支持：{'、'.join(AREA_MAP.keys())}"
            )
        if (area_name, build_num) not in BUILD_MAP:
            await electric_query.finish(f"{area_name}没有{build_num}栋")
        if not room_id.isdigit() or len(room_id) != 4:
            await electric_query.finish("房间号应为4位数字，如1001")
        sysid, areaid = AREA_MAP[area_name]
        query_params = {
            "sysid": sysid,
            "roomid": room_id,
            "areaid": areaid,
            "buildid": BUILD_MAP[(area_name, build_num)],
        }
    else:
        if "query_params" not in data:
            await electric_query.finish(
                "格式：#电费 区域 楼栋 房间号\n例：#电费 三期 21 1001"
            )
        query_params = data["query_params"]

    result = await query_electric_bill(**query_params)
    if result.get("retcode") == 0:
        # 仅在参数变化时保存
        if data.get("query_params") != query_params:
            data["query_params"] = query_params
            save_user_data(str(user_id), data)
        await electric_query.finish(f"剩余电量: {result['restElecDegree']} 度")
    else:
        await electric_query.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@electric_raw.handle()
async def handle_electric_raw(bot: Bot, event: Event, args: Message = CommandArg()):
    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await electric_raw.finish("格式：#电费原始 sysid roomid areaid buildid")
    parts = arg_text.split()
    if len(parts) < 4:
        await electric_raw.finish("需要4个参数：sysid roomid areaid buildid")
    result = await query_electric_bill(*parts[:4])
    if result.get("retcode") == 0:
        await electric_raw.finish(f"剩余电量: {result['restElecDegree']} 度")
    else:
        await electric_raw.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@electric_help.handle()
async def handle_electric_help(bot: Bot, event: Event, args: Message = CommandArg()):
    await electric_help.finish(
        "💡 电费查询帮助\n"
        "━━━━━━━━━━━━\n\n"
        "【使用方式】\n"
        "#电费 区域 楼栋 房间号\n"
        "#电费（使用上次保存的参数）\n"
        "#昨日耗电\n"
        "#清除电费设置\n\n"
        "【示例】\n"
        "#电费 三期 21 1001\n"
        "#电费 四期 28 1021\n\n"
        "【昨日耗电】\n"
        "系统会在每日 00:00 前后十分钟错峰结算；"
        "设置校园卡账号后可自动校正当天缴费。\n\n"
        "【支持的区域和楼栋】\n"
        "三期：10-26栋\n"
        "四期：20、21、23、24、27-30、33-36、39-42栋\n\n"
        "输入【#电费详细帮助】查看更多"
    )


@electric_help_detail.handle()
async def handle_electric_help_detail(
    bot: Bot, event: Event, args: Message = CommandArg()
):
    await electric_help_detail.finish(
        "📖 电费原始查询帮助\n"
        "━━━━━━━━━━━━\n\n"
        "格式：#电费原始 系统ID 房间号 区域ID 楼栋ID\n"
        "例：#电费原始 4 1001 101 13\n\n"
        "【系统ID】\n"
        "3 = 后勤部综合楼\n"
        "4 = 上海工程技术大学电控充值\n\n"
        "【区域ID】\n"
        "101 = 三期学生公寓\n"
        "102 = 四期学生公寓\n"
        "104 = 长宁南北宿舍楼\n"
        "105 = 研究生一号楼9-11层\n"
        "106 = 北区创客中心\n"
        "107 = 长宁产教融合大楼\n"
        "108 = 研究生宿舍楼\n\n"
        "【楼栋ID】\n"
        "三期：2=10栋 3=11栋 4=12栋 5=13栋\n"
        "　　6=14栋 7=15栋 8=16栋 9=17栋\n"
        "　　10=18栋 11=19栋 12=20栋 13=21栋\n"
        "　　14=22栋 15=23栋 16=24栋 17=25栋\n"
        "　　18=26栋\n"
        "四期：19=20栋 20=21栋 21=23栋 22=24栋\n"
        "　　23=27栋 24=28栋 25=29栋 26=30栋\n"
        "　　27=33栋 28=34栋 29=35栋 30=36栋\n"
        "　　31=39栋 32=40栋 33=41栋 34=42栋\n"
        "其他：35=南楼 36=北楼\n"
        "　　38=研究生一号楼 39=创客中心\n"
        "　　40=产教融合4-9楼 41=产教融合10-15楼\n"
        "　　42=研究生二号楼1-6层\n"
        "　　43=研究生一号楼1-4层\n"
        "　　44=研究生二号楼7-12层\n"
        "　　45=研究生一号楼5-8层"
    )


@electric_clear.handle()
async def handle_electric_clear(bot: Bot, event: Event, args: Message = CommandArg()):
    user_id = event.get_user_id()
    user_file = get_user_file(str(user_id))
    user_file.unlink(missing_ok=True)
    await electric_clear.finish("已清除保存的查询参数")
