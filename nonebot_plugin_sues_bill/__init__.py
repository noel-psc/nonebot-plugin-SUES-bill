import io
import re
import json
from pathlib import Path

import requests
from PIL import Image
from nonebot import logger, get_driver, on_command
from pytesseract import image_to_string
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, Event

__plugin_meta__ = PluginMetadata(
    name="电费查询",
    description="电费查询插件",
    usage=(
        "电费 [系统ID] [房间号] [区域ID] [楼栋ID]\n"
        "电费帮助\n清除电费设置\n"
        "(管理员私聊) 设置全局电费账号 用户名 密码"
    ),
)

# 配置
BASE_URL = "https://epay.sues.edu.cn"
LOGIN_PATH = "/epay/person/index"
QUERY_PATH = "/epay/wxpage/wanxiao/eleresult"
HOME_PATH = "/"

# 数据存储目录
DATA_DIR = Path.home() / ".cache" / "nonebot-plugin-sues-bill"
GLOBAL_ACCOUNT_FILE = DATA_DIR / "global_account.json"
GLOBAL_COOKIES_FILE = DATA_DIR / "global_cookies.json"

# 创建命令
electric_query = on_command("电费", priority=5, block=True)
electric_set_global = on_command("设置全局电费账号", priority=5, block=True)
electric_help = on_command("电费帮助", priority=5, block=True)
electric_clear = on_command("清除电费设置", priority=5, block=True)


# ─── 存储工具 ────────────────────────────────────────────────


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _get_user_file(user_id: str) -> Path:
    return DATA_DIR / f"{user_id}.json"


def load_global_account() -> dict:
    """加载全局账号"""
    _ensure_data_dir()
    if GLOBAL_ACCOUNT_FILE.exists():
        try:
            with open(GLOBAL_ACCOUNT_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_global_account(username: str, password: str):
    """保存全局账号"""
    _ensure_data_dir()
    with open(GLOBAL_ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump({"username": username, "password": password}, f, indent=2)


def load_global_cookies() -> dict:
    """加载全局cookie"""
    _ensure_data_dir()
    if GLOBAL_COOKIES_FILE.exists():
        try:
            with open(GLOBAL_COOKIES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_global_cookies(cookies: dict):
    """保存全局cookie"""
    _ensure_data_dir()
    with open(GLOBAL_COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)


def load_user_data(user_id: str) -> dict:
    """加载用户数据（仅查询参数）"""
    _ensure_data_dir()
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
    _ensure_data_dir()
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
    await electric_set_global.finish(f"全局账号设置成功！用户名: {parts[0]}")


@electric_query.handle()
async def handle_electric_query(bot: Bot, event: Event, args: Message = CommandArg()):
    """处理电费查询命令"""
    user_id = event.get_user_id()
    data = load_user_data(user_id)

    # 获取全局账号
    global_account = load_global_account()
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
        "====电费查询帮助菜单====\n"
        "格式：#电费 [系统ID] [房间号] [区域ID] [楼栋ID]\n"
        "直接输入【#电费】将使用上次保存的参数查询\n\n"
        "系统ID：\n"
        "  3：后勤部综合楼\n"
        "  4：上海工程技术大学电控充值\n\n"
        "区域ID：\n"
        "  101：三期学生公寓\n"
        "  102：四期学生公寓\n"
        "  104：长宁南北宿舍楼\n"
        "  105：研究生一号楼9-11层\n"
        "  106：北区创客中心\n"
        "  107：长宁产教融合大楼\n"
        "  108：研究生宿舍楼\n\n"
        "楼栋ID：\n"
        "  2：三期10     3：三期11     4：三期12\n"
        "  5：三期13     6：三期14     7：三期15\n"
        "  8：三期16     9：三期17     10：三期18\n"
        "  11：三期19   12：三期20   13：三期21\n"
        "  14：三期22   15：三期23   16：三期24\n"
        "  17：三期25   18：三期26   19：四期20\n"
        "  20：四期21   21：四期23   22：四期24\n"
        "  23：四期27   24：四期28   25：四期29\n"
        "  26：四期30   27：四期33   28：四期34\n"
        "  29：四期35   30：四期36   31：四期39\n"
        "  32：四期40   33：四期41   34：四期42\n"
        "  35：南楼   36：北楼\n"
        "  38：研究生一号楼\n"
        "  39：创客中心\n"
        "  40：产教融合4-9楼\n"
        "  41：产教融合10-15楼\n"
        "  42：研究生二号楼1-6层\n"
        "  43：研究生一号楼1-4层\n"
        "  44：研究生二号楼7-12层\n"
        "  45：研究生一号楼5-8层"
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
