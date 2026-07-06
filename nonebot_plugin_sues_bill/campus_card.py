"""校园卡余额查询模块"""

import re
import json
import base64

import ddddocr
import requests
from nonebot import logger, on_command
from Crypto.Cipher import DES
from nonebot.params import CommandArg
from nonebot.adapters import Message
from Crypto.Util.Padding import pad
from nonebot.adapters.onebot.v11 import Bot, Event

from .models import DATA_DIR

BASE_URL = "https://epay.sues.edu.cn"
LOGIN_URL = f"{BASE_URL}/epay/j_spring_security_check"
INDEX_URL = f"{BASE_URL}/epay/h5/index"
CAPTCHA_URL = f"{BASE_URL}/epay/codeimage"

# DES 加密参数（从网页 JS 提取）
DES_KEY = b"6eGicG6U"
DES_IV = bytes([1, 2, 3, 4, 5, 6, 7, 8])

# 校园卡账号存储文件
ACCOUNT_FILE = DATA_DIR / "campus_card_account.json"


def load_account() -> dict:
    if ACCOUNT_FILE.exists():
        try:
            with open(ACCOUNT_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_account(username: str, password: str):
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump({"username": username, "password": password}, f, indent=2)


def encrypt_password(password: str) -> str:
    """DES-CBC 加密密码"""
    cipher = DES.new(DES_KEY, DES.MODE_CBC, DES_IV)
    encrypted = cipher.encrypt(pad(password.encode(), DES.block_size))
    return base64.b64encode(encrypted).decode()


def recognize_captcha(image_content: bytes) -> str | None:
    """识别验证码"""
    try:
        ocr = ddddocr.DdddOcr(show_ad=False)
        result = ocr.classification(image_content)
        return result if result else None
    except Exception as e:
        logger.error(f"验证码识别失败: {e}")
        return None


def login(session: requests.Session, username: str, password: str) -> bool:
    """登录校园卡系统"""
    try:
        # 获取登录页
        login_page_url = f"{BASE_URL}/epay/person/index"
        resp = session.get(login_page_url)

        # 提取 CSRF token
        csrf_match = re.search(r'<meta name="_csrf" content="([^"]+)"', resp.text)
        csrf_token = csrf_match.group(1) if csrf_match else ""

        # 提取验证码图片 URL 并识别
        captcha_match = re.search(r'<img[^>]+src="([^"]*imageCode[^"]*)"', resp.text)
        captcha = None
        if captcha_match:
            captcha_url = captcha_match.group(1)
            if not captcha_url.startswith("http"):
                captcha_url = BASE_URL + captcha_url
            captcha_resp = session.get(captcha_url)
            captcha = recognize_captcha(captcha_resp.content)

        # 提取表单 action
        form_match = re.search(r'<form[^>]+action="([^"]+)"', resp.text)
        if not form_match:
            logger.warning("未找到登录表单")
            return False
        form_action = form_match.group(1)
        if form_action.startswith("/"):
            form_action = BASE_URL + form_action

        # 提取所有隐藏字段
        input_matches = re.findall(
            r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', resp.text
        )
        form_data = dict(input_matches)

        # 添加登录字段
        form_data["j_username"] = username
        form_data["j_password"] = encrypt_password(password)
        if captcha:
            form_data["imageCodeName"] = captcha

        # 提交登录
        headers = {"X-CSRF-TOKEN": csrf_token} if csrf_token else {}
        login_resp = session.post(form_action, data=form_data, headers=headers)

        # 访问首页建立会话
        session.get(f"{BASE_URL}/")

        # 验证登录
        check_resp = session.get(INDEX_URL)
        if "账户余额" in check_resp.text:
            return True

        logger.warning(f"登录失败, resp URL: {login_resp.url}")
        return False
    except Exception as e:
        logger.error(f"登录异常: {e}")
        return False


def query_balance(session: requests.Session) -> dict:
    """查询校园卡余额"""
    try:
        resp = session.get(INDEX_URL)

        # 提取账户余额
        balance_match = re.search(r"账户余额.*?￥\s*([\d.]+)", resp.text, re.DOTALL)
        frozen_match = re.search(r"冻结余额.*?￥\s*([\d.]+)", resp.text, re.DOTALL)

        if balance_match:
            return {
                "retcode": 0,
                "balance": balance_match.group(1),
                "frozen": frozen_match.group(1) if frozen_match else "0.00",
            }
        return {"retcode": -1, "retmsg": "未找到余额信息"}
    except Exception as e:
        return {"retcode": -1, "retmsg": f"查询失败: {e}"}


# ─── 命令注册 ─────────────────────────────────────────────

campus_card_query = on_command("校园卡", priority=5, block=True)
campus_card_set = on_command("设置校园卡账号", priority=5, block=True)
campus_card_help = on_command("校园卡帮助", priority=5, block=True)


@campus_card_query.handle()
async def handle_campus_card_query(
    bot: Bot, event: Event, args: Message = CommandArg()
):
    account = load_account()
    if not account:
        await campus_card_query.finish(
            "未设置账号，请先私聊发送：\n设置校园卡账号 学号 密码"
        )

    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    )

    if not login(session, account["username"], account["password"]):
        await campus_card_query.finish("登录失败，请检查账号密码或验证码")

    result = query_balance(session)
    if result.get("retcode") == 0:
        await campus_card_query.finish(
            f"💳 校园卡余额\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"账户余额: ￥{result['balance']}\n"
            f"冻结余额: ￥{result['frozen']}"
        )
    else:
        await campus_card_query.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@campus_card_set.handle()
async def handle_campus_card_set(bot: Bot, event: Event, args: Message = CommandArg()):
    if event.message_type != "private":
        await campus_card_set.finish("请私聊机器人设置账号")

    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await campus_card_set.finish("格式：设置校园卡账号 学号 密码")

    parts = arg_text.split()
    if len(parts) < 2:
        await campus_card_set.finish("格式：设置校园卡账号 学号 密码")

    save_account(parts[0], parts[1])
    await campus_card_set.finish(f"校园卡账号设置成功！学号: {parts[0]}")


@campus_card_help.handle()
async def handle_campus_card_help(bot: Bot, event: Event, args: Message = CommandArg()):
    await campus_card_help.finish(
        "💳 校园卡查询帮助\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "【使用方式】\n"
        "#校园卡 — 查询余额\n"
        "#校园卡帮助 — 查看帮助\n\n"
        "【首次使用】\n"
        "私聊发送：设置校园卡账号 学号 密码"
    )
