"""校园卡余额查询模块"""

import re
import json
import base64

import ddddocr
import requests
from nonebot import logger, on_command
from Crypto.Cipher import PKCS1_v1_5
from nonebot.params import CommandArg
from Crypto.PublicKey import RSA
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, Event

from .models import DATA_DIR

BASE_URL = "https://epay.sues.edu.cn"
INDEX_URL = f"{BASE_URL}/epay/h5/index"

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


def recognize_captcha(image_content: bytes) -> str | None:
    """识别验证码"""
    try:
        ocr = ddddocr.DdddOcr(show_ad=False)
        result = ocr.classification(image_content)
        return result if result else None
    except Exception as e:
        logger.error(f"验证码识别失败: {e}")
        return None


def rsa_encrypt(password: str, modulus_hex: str, exponent_hex: str) -> str:
    """RSA 加密密码"""
    modulus = int(modulus_hex, 16)
    exponent = int(exponent_hex, 16)
    pub_key = RSA.construct((modulus, exponent))
    cipher = PKCS1_v1_5.new(pub_key)
    encrypted = cipher.encrypt(password.encode())
    return base64.b64encode(encrypted).decode()


def login(session: requests.Session, username: str, password: str) -> bool:
    """登录校园卡系统"""
    try:
        # 获取桌面端登录页
        resp = session.get(f"{BASE_URL}/epay/person/index")
        logger.info(f"登录页: {resp.url}, len={len(resp.text)}")
        logger.info(f"登录页前500字:\n{resp.text[:500]}")

        # 提取 CSRF token
        csrf_match = re.search(r'<meta name="_csrf" content="([^"]+)"/>', resp.text)
        csrf_token = csrf_match.group(1) if csrf_match else ""

        # 提取验证码图片 URL 并识别
        captcha_match = re.search(
            r"""<img[^>]+src=(?:"|')([^"']*(?:codeimage|imageCode)[^"']*)(?:"|')""",
            resp.text,
        )
        captcha = None
        if captcha_match:
            captcha_url = captcha_match.group(1)
            if not captcha_url.startswith("http"):
                captcha_url = BASE_URL + captcha_url
            captcha_resp = session.get(captcha_url)
            captcha = recognize_captcha(captcha_resp.content)

        # 提取登录表单 action（包含 j_username 的表单）
        # 找到包含 j_username 的 form 区块
        login_form_match = re.search(
            r'<form[^>]*action="([^"]+)"[^>]*name="loginFr"', resp.text
        )
        if not login_form_match:
            login_form_match = re.search(
                r'<form[^>]*name="loginFr"[^>]*action="([^"]+)"', resp.text
            )
        if not login_form_match:
            logger.warning("未找到登录表单")
            return False
        form_action = login_form_match.group(1)
        if form_action.startswith("/"):
            form_action = BASE_URL + form_action
        elif not form_action.startswith("http"):
            form_action = BASE_URL + "/" + form_action

        # 提取所有输入字段
        input_matches = re.findall(
            r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', resp.text
        )
        form_data = dict(input_matches)

        # 提取 RSA 加密参数（从 JavaScript 中提取）
        rsa_match = re.search(
            r'RSAKeyPair\("([^"]+)","([^"]*)","([^"]+)"\)', resp.text
        )

        # 加密密码
        if rsa_match:
            exponent = rsa_match.group(1)
            modulus = rsa_match.group(3)
            encrypted_pwd = rsa_encrypt(password, modulus, exponent)
            form_data["j_password"] = encrypted_pwd
            logger.info("使用 RSA 加密密码")
        else:
            form_data["j_password"] = password
            logger.info("未找到 RSA 参数，使用明文密码")

        form_data["j_username"] = username
        if captcha:
            form_data["imageCodeName"] = captcha

        logger.info(f"登录表单: action={form_action}, fields={list(form_data.keys())}")
        logger.info(f"验证码: {captcha}")

        # 提交登录
        headers = {"X-CSRF-TOKEN": csrf_token} if csrf_token else {}
        login_resp = session.post(form_action, data=form_data, headers=headers)
        logger.info(f"登录响应: status={login_resp.status_code}, url={login_resp.url}")
        logger.info(f"登录后cookies: {dict(session.cookies)}")

        # 检查是否登录成功（响应不包含登录页重定向）
        if "window.location" in login_resp.text and "person/index" in login_resp.text:
            logger.warning("登录失败：被重定向回登录页")
            return False
        if "锁定" in login_resp.text:
            logger.warning("账号已被锁定")
            return False
        if "errinfo" in login_resp.text:
            # 提取错误信息
            err_match = re.search(r"errinfo.*?>(.*?)<", login_resp.text)
            if err_match:
                logger.warning(f"登录错误: {err_match.group(1)}")
            return False

        # 尝试访问 H5
        h5_resp = session.get(INDEX_URL)
        logger.info(f"H5: url={h5_resp.url}, len={len(h5_resp.text)}")
        if "账户余额" in h5_resp.text:
            return True

        return False
        return False
    except Exception as e:
        logger.error(f"登录异常: {e}")
        return False


def query_balance(session: requests.Session) -> dict:
    """查询校园卡余额"""
    try:
        resp = session.get(INDEX_URL)
        logger.info(f"查询余额: url={resp.url}, status={resp.status_code}")

        # 检查响应内容
        if "账户余额" in resp.text:
            logger.info("找到'账户余额'")
        else:
            logger.info("未找到'账户余额'")
            logger.info(f"响应长度: {len(resp.text)}")
            if "登录" in resp.text:
                logger.info("响应包含'登录'，可能未登录")

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
