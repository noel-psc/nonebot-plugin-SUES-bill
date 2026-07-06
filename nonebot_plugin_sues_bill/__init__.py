import re
import json

import requests
from nonebot import on_command
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Message
from nonebot_plugin_localstore import get_plugin_data_file
from nonebot.adapters.onebot.v11 import Bot, Event

__plugin_meta__ = PluginMetadata(
    name="电费查询",
    description="电费查询插件",
    usage="#电费帮助 查看详细参数说明",
)

# 配置
BASE_URL = "https://epay.sues.edu.cn"
QUERY_PATH = "/epay/wxpage/wanxiao/eleresult"

# 用户数据文件
DATA_DIR = get_plugin_data_file("").parent


def _get_user_file(user_id: str):
    return DATA_DIR / f"user_{user_id}.json"


def load_user_data(user_id: str) -> dict:
    """加载用户数据（查询参数）"""
    user_file = _get_user_file(user_id)
    if user_file.exists():
        try:
            with open(user_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_user_data(user_id: str, data: dict):
    """保存用户数据"""
    user_file = _get_user_file(user_id)
    with open(user_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 查询 ───────────────────────────────────────────────────


def query_electric_bill(sysid="4", roomid="4021", areaid="101", buildid="13"):
    """查询宿舍电费信息"""
    try:
        session = requests.Session()

        # 发送查询请求
        query_url = BASE_URL + QUERY_PATH
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

        response = session.get(query_url, params=params, headers=headers)

        # 提取剩余电量
        pattern = r"(\d+\.?\d*)\s*度"
        match = re.search(pattern, response.text)

        if match:
            rest_degree = float(match.group(1))
            return {
                "retcode": 0,
                "retmsg": "成功",
                "restElecDegree": rest_degree,
            }
        else:
            return {"retcode": -1, "retmsg": "未找到剩余电量信息"}
    except Exception as e:
        return {"retcode": -1, "retmsg": f"错误: {e}"}


# ─── 处理器 ─────────────────────────────────────────────────

electric_query = on_command("电费", priority=5, block=True)
electric_help = on_command("电费帮助", priority=5, block=True)
electric_clear = on_command("清除电费设置", priority=5, block=True)


@electric_query.handle()
async def handle_electric_query(bot: Bot, event: Event, args: Message = CommandArg()):
    """处理电费查询命令"""
    user_id = event.get_user_id()
    data = load_user_data(user_id)

    # 获取查询参数
    arg_text = args.extract_plain_text().strip()

    if arg_text:
        parts = arg_text.split()
        if len(parts) >= 4:
            query_params = {
                "sysid": parts[0],
                "roomid": parts[1],
                "areaid": parts[2],
                "buildid": parts[3],
            }
        else:
            await electric_query.finish(
                "参数不足，格式：#电费 [系统ID] [房间号] [区域ID] [楼栋ID]\n"
                "或直接使用【#电费】使用上次保存的参数"
            )
    else:
        if "query_params" not in data:
            await electric_query.finish(
                "请提供查询参数，格式：#电费 [系统ID] [房间号] [区域ID] [楼栋ID]\n"
                "输入【#电费帮助】查看参数说明"
            )
        query_params = data["query_params"]

    # 查询电费
    result = query_electric_bill(
        sysid=query_params["sysid"],
        roomid=query_params["roomid"],
        areaid=query_params["areaid"],
        buildid=query_params["buildid"],
    )

    if result.get("retcode") == 0:
        # 保存本次使用的参数
        data["query_params"] = query_params
        save_user_data(str(user_id), data)

        room = query_params["roomid"]
        degree = result["restElecDegree"]
        await electric_query.finish(
            f"电费查询成功！\n房间: {room}\n剩余电量: {degree} 度"
        )
    else:
        await electric_query.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@electric_help.handle()
async def handle_electric_help(bot: Bot, event: Event, args: Message = CommandArg()):
    await electric_help.finish(
        "💡 电费查询帮助\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "【使用方式】\n"
        "#电费 系统ID 房间号 区域ID 楼栋ID\n"
        "#电费（使用上次保存的参数）\n"
        "#清除电费设置（清除保存的参数）\n\n"
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
    """清除保存的查询参数"""
    user_id = event.get_user_id()
    user_file = _get_user_file(str(user_id))

    if user_file.exists():
        user_file.unlink()
        await electric_clear.finish("已清除保存的查询参数")
    else:
        await electric_clear.finish("没有需要清除的设置")
