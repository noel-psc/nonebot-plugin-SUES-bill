"""校园卡余额查询模块"""

import io
import re
import json
import base64

import requests
import pytesseract
from PIL import Image
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
    """OCR 识别验证码"""
    try:
        img = Image.open(io.BytesIO(image_content))
        img = img.convert("L")
        img = img.point(lambda x: 0 if x < 128 else 255, "1")
        captcha = pytesseract.image_to_string(
            img, config="--psm 7 -c tessedit_char_whitelist=0123456789"
        )
        captcha = captcha.strip()
        return captcha if captcha else None
    except Exception as e:
        logger.error(f"验证码识别失败: {e}")
        return None


def login(session: requests.Session, username: str, password: str) -> bool:
    """登录校园卡系统"""
    try:
        # 获取登录页和 CSRF token
        resp = session.get(f"{BASE_URL}/epay/person/index")
        csrf_match = re.search(r'<meta name="_csrf" content="([^"]+)"', resp.text)
        csrf_token = csrf_match.group(1) if csrf_match else ""

        # 获取验证码
        captcha_resp = session.get(CAPTCHA_URL)
        captcha = recognize_captcha(captcha_resp.content)
        if not captcha:
            logger.warning("验证码识别失败")
            return False

        # 加密密码
        encrypted_pwd = encrypt_password(password)

        # 提取隐藏字段
        form_data = {
            "_csrf": csrf_token,
            "j_username": username,
            "j_password": encrypted_pwd,
            "imageCodeName": captcha,
        }

        # 登录
        login_resp = session.post(
            LOGIN_URL,
            data=form_data,
            headers={"X-CSRF-TOKEN": csrf_token},
            allow_redirects=True,
        )

        # 检查是否登录成功（跳转到首页）
        if "/epay/h5/index" in login_resp.url or "/epay/" in login_resp.url:
            # 验证：访问首页看是否有余额
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
