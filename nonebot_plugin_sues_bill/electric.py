import re

import requests
from nonebot import on_command
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, Event

from .models import load_user_data, save_user_data

BASE_URL = "https://epay.sues.edu.cn"
QUERY_PATH = "/epay/wxpage/wanxiao/eleresult"

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


def query_electric_bill(sysid="4", roomid="4021", areaid="101", buildid="13"):
    try:
        session = requests.Session()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
            )
        }
        params = {
            "sysid": sysid,
            "roomid": roomid,
            "areaid": areaid,
            "buildid": buildid,
        }
        resp = session.get(BASE_URL + QUERY_PATH, params=params, headers=headers)
        match = re.search(r"(\d+\.?\d*)\s*度", resp.text)
        if match:
            return {"retcode": 0, "restElecDegree": float(match.group(1))}
        return {"retcode": -1, "retmsg": "未找到剩余电量信息"}
    except Exception as e:
        return {"retcode": -1, "retmsg": f"错误: {e}"}


electric_query = on_command("电费", priority=5, block=True)
electric_raw = on_command("电费原始", priority=5, block=True)
electric_help = on_command("电费帮助", priority=5, block=True)
electric_help_detail = on_command("电费详细帮助", priority=5, block=True)
electric_clear = on_command("清除电费设置", priority=5, block=True)


@electric_query.handle()
async def handle_electric_query(bot: Bot, event: Event, args: Message = CommandArg()):
    user_id = event.get_user_id()
    data = load_user_data(user_id)
    arg_text = args.extract_plain_text().strip()

    if arg_text:
        parts = arg_text.split()
        if len(parts) < 3:
            await electric_query.finish(
                "格式：#电费 区域 楼栋 房间号\n例：#电费 三期 21 4021"
            )
        area_name, build_num, room_id = parts[0], parts[1], parts[2]
        if area_name not in AREA_MAP:
            await electric_query.finish(
                f"不支持的区域，目前支持：{'、'.join(AREA_MAP.keys())}"
            )
        if (area_name, build_num) not in BUILD_MAP:
            await electric_query.finish(f"{area_name}没有{build_num}栋")
        if not room_id.isdigit() or len(room_id) != 4:
            await electric_query.finish("房间号应为4位数字，如4021")
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
                "格式：#电费 区域 楼栋 房间号\n例：#电费 三期 21 4021"
            )
        query_params = data["query_params"]

    result = query_electric_bill(**query_params)
    if result.get("retcode") == 0:
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
    result = query_electric_bill(*parts[:4])
    if result.get("retcode") == 0:
        await electric_raw.finish(f"剩余电量: {result['restElecDegree']} 度")
    await electric_raw.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@electric_help.handle()
async def handle_electric_help(bot: Bot, event: Event, args: Message = CommandArg()):
    await electric_help.finish(
        "💡 电费查询帮助\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "【使用方式】\n"
        "#电费 区域 楼栋 房间号\n"
        "#电费（使用上次保存的参数）\n"
        "#清除电费设置\n\n"
        "【示例】\n"
        "#电费 三期 21 4021\n"
        "#电费 四期 28 1021\n\n"
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
        "━━━━━━━━━━━━━━━━\n\n"
        "格式：#电费原始 系统ID 房间号 区域ID 楼栋ID\n"
        "例：#电费原始 4 4021 101 13\n\n"
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
    from .models import get_user_file

    user_file = get_user_file(str(user_id))
    if user_file.exists():
        user_file.unlink()
        await electric_clear.finish("已清除保存的查询参数")
    else:
        await electric_clear.finish("没有需要清除的设置")
