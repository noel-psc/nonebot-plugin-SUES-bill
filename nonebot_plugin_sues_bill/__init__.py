import io
import re
import json

import requests
from PIL import Image
from nonebot import logger, get_driver, on_command
from pytesseract import image_to_string
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
LOGIN_PATH = "/epay/person/index"
QUERY_PATH = "/epay/wxpage/wanxiao/eleresult"
HOME_PATH = "/"

# 文件路径（使用 localstore）
GLOBAL_ACCOUNT_FILE = get_plugin_data_file("global_account.json")
GLOBAL_COOKIES_FILE = get_plugin_data_file("global_cookies.json")
logger.info(f"电费插件数据目录: {GLOBAL_ACCOUNT_FILE.parent}")

# 创建命令
electric_query = on_command("电费", priority=5, block=True)
electric_set_global = on_command("设置全局电费账号", priority=5, block=True)
electric_help = on_command("电费帮助", priority=5, block=True)
electric_clear = on_command("清除电费设置", priority=5, block=True)
electric_clear_global = on_command("清除全局电费设置", priority=5, block=True)


# ─── 存储工具 ────────────────────────────────────────────────


def _get_user_file(user_id: str):
    return get_plugin_data_file(f"user_{user_id}.json")


def load_global_account() -> dict:
    """加载全局账号"""
    if GLOBAL_ACCOUNT_FILE.exists():
        try:
            with open(GLOBAL_ACCOUNT_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_global_account(username: str, password: str):
    """保存全局账号"""
    with open(GLOBAL_ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump({"username": username, "password": password}, f, indent=2)


def load_global_cookies() -> dict:
    """加载全局cookie"""
    if GLOBAL_COOKIES_FILE.exists():
        try:
            with open(GLOBAL_COOKIES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_global_cookies(cookies: dict):
    """保存全局cookie"""
    with open(GLOBAL_COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)


def load_user_data(user_id: str) -> dict:
    """加载用户数据（仅查询参数）"""
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


# ─── 验证码 & 登录 ──────────────────────────────────────────


def recognize_captcha(image_content):
    """识别数字验证码"""
    try:
        img = Image.open(io.BytesIO(image_content))
        img = img.convert("L")
        img = img.point(lambda x: 0 if x < 128 else 255, "1")
        captcha = image_to_string(
            img, config="--psm 7 -c tessedit_char_whitelist=0123456789"
        )
        captcha = captcha.strip()
        return captcha if captcha else None
    except Exception as e:
        logger.error(f"验证码识别失败: {e}")
        return None


def login(session, username, password):
    """登录系统"""
    try:
        login_url = BASE_URL + LOGIN_PATH
        response = session.get(login_url)

        csrf_token = None
        csrf_pattern = r'<meta name="_csrf" content="([^"]+)"/>'
        csrf_match = re.search(csrf_pattern, response.text)
        if csrf_match:
            csrf_token = csrf_match.group(1)

        captcha_pattern = r'<img[^>]+src="([^"]*imageCode[^"]*)"'
        captcha_match = re.search(captcha_pattern, response.text)

        captcha = None
        if captcha_match:
            captcha_url = captcha_match.group(1)
            if not captcha_url.startswith("http"):
                captcha_url = BASE_URL + captcha_url

            captcha_response = session.get(captcha_url)
            captcha = recognize_captcha(captcha_response.content)

        form_pattern = r'<form[^>]+action="([^"]+)"'
        form_match = re.search(form_pattern, response.text)

        if form_match:
            form_action = form_match.group(1)
            if form_action.startswith("/"):
                form_action = BASE_URL + form_action
            elif not form_action.startswith("http"):
                form_action = BASE_URL + "/" + form_action

            input_pattern = r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"'
            input_matches = re.findall(input_pattern, response.text)

            form_data = {}
            for name, value in input_matches:
                form_data[name] = value

            form_data["j_username"] = username
            form_data["j_password"] = password
            if captcha:
                form_data["imageCodeName"] = captcha

            headers = {}
            if csrf_token:
                headers["X-CSRF-TOKEN"] = csrf_token

            login_response = session.post(form_action, data=form_data, headers=headers)

            login_url_lower = LOGIN_PATH.lower()
            resp_url = login_response.url.lower()
            has_error = (
                "错误" in login_response.text or "登录失败" in login_response.text
            )
            on_login_page = login_url_lower in resp_url
            has_cookies = bool(session.cookies.get_dict())

            if not has_error and (not on_login_page or has_cookies):
                return True
            else:
                logger.warning(
                    f"登录失败: has_error={has_error}, "
                    f"on_login_page={on_login_page}, "
                    f"has_cookies={has_cookies}"
                )
        return False
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return False


# ─── 查询 ───────────────────────────────────────────────────


def query_electric_bill(
    sysid="4",
    roomid="4021",
    areaid="101",
    buildid="13",
    username=None,
    password=None,
    saved_cookies=None,
):
    """查询宿舍电费信息"""
    try:
        session = requests.Session()

        if saved_cookies:
            session.cookies.update(saved_cookies)
        elif username and password:
            if not login(session, username, password):
                return {
                    "retcode": -1,
                    "retmsg": "登录失败，请检查用户名、密码或验证码",
                }
        else:
            return {
                "retcode": -1,
                "retmsg": "未设置全局账号，请联系管理员",
            }

        home_url = BASE_URL + HOME_PATH
        session.get(home_url)

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

        query_response = session.get(query_url, params=params, headers=headers)

        pattern = r"(\d+\.?\d*)\s*度"
        match = re.search(pattern, query_response.text)

        if match:
            rest_degree = float(match.group(1))
            new_cookies = session.cookies.get_dict()
            return {
                "retcode": 0,
                "retmsg": "成功",
                "restElecDegree": rest_degree,
                "cookies": new_cookies,
            }
        else:
            return {"retcode": -1, "retmsg": "未找到剩余电量信息"}
    except Exception as e:
        return {"retcode": -1, "retmsg": f"错误: {e}"}


# ─── 处理器 ─────────────────────────────────────────────────


@electric_set_global.handle()
async def handle_set_global(bot: Bot, event: Event, args: Message = CommandArg()):
    """设置全局电费账号（仅管理员私聊）"""
    # 检查是否私聊
    if event.message_type != "private":
        await electric_set_global.finish("请私聊机器人设置全局账号")

    # 检查是否超级管理员
    user_id = str(event.get_user_id())
    superusers = getattr(get_driver().config, "SUPERUSERS", None) or getattr(
        get_driver().config, "superusers", set()
    )
    if user_id not in superusers:
        await electric_set_global.finish("仅管理员可设置全局账号")

    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await electric_set_global.finish("格式：设置全局电费账号 用户名 密码")

    parts = arg_text.split()
    if len(parts) < 2:
        await electric_set_global.finish("格式：设置全局电费账号 用户名 密码")

    save_global_account(parts[0], parts[1])
    # 清除旧cookie，强制下次查询重新登录
    if GLOBAL_COOKIES_FILE.exists():
        GLOBAL_COOKIES_FILE.unlink()
    await electric_set_global.finish(f"全局账号设置成功！用户名: {parts[0]}")


@electric_query.handle()
async def handle_electric_query(bot: Bot, event: Event, args: Message = CommandArg()):
    """处理电费查询命令"""
    user_id = event.get_user_id()
    data = load_user_data(user_id)

    # 获取全局账号
    global_account = load_global_account()
    logger.debug(f"全局账号文件: {GLOBAL_ACCOUNT_FILE}")
    logger.debug(f"全局账号内容: {global_account}")
    cookies = load_global_cookies()
    logger.debug(f"全局cookie文件: {GLOBAL_COOKIES_FILE}")
    logger.debug(f"全局cookie内容: {cookies}")
    if not global_account:
        await electric_query.finish(
            "全局账号未设置，请联系管理员使用【设置全局电费账号】命令"
        )

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
        username=global_account["username"],
        password=global_account["password"],
        saved_cookies=load_global_cookies(),
    )

    if result.get("retcode") == 0:
        data["query_params"] = query_params
        save_user_data(str(user_id), data)
        # 保存全局cookie
        if result.get("cookies"):
            save_global_cookies(result["cookies"])

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


@electric_clear_global.handle()
async def handle_clear_global(bot: Bot, event: Event, args: Message = CommandArg()):
    """清除全局账号和cookie（仅管理员私聊）"""
    if event.message_type != "private":
        await electric_clear_global.finish("请私聊机器人操作")

    user_id = str(event.get_user_id())
    superusers = getattr(get_driver().config, "SUPERUSERS", None) or getattr(
        get_driver().config, "superusers", set()
    )
    if user_id not in superusers:
        await electric_clear_global.finish("仅管理员可操作")

    # 删除全局账号和cookie文件
    if GLOBAL_ACCOUNT_FILE.exists():
        GLOBAL_ACCOUNT_FILE.unlink()
    if GLOBAL_COOKIES_FILE.exists():
        GLOBAL_COOKIES_FILE.unlink()

    await electric_clear_global.finish("已清除全局账号和cookie缓存")
