"""校园卡余额查询模块"""

import re

import ddddocr
import httpx
from nonebot import get_plugin_config, logger, on_command
from Crypto.Cipher import DES
from nonebot.params import CommandArg
from nonebot.adapters import Message
from Crypto.Util.Padding import pad
from cryptography.fernet import Fernet
from nonebot.adapters.onebot.v11 import Bot, Event

from .config import (
    Config,
    DES_IV,
    DES_KEY,
    USER_AGENT,
    CAMPUS_CARD_INDEX_PATH,
)
from .models import (
    DATA_DIR,
    load_campus_card_account,
    save_campus_card_account,
)

config = get_plugin_config(Config)

# 完整 URL
INDEX_URL = config.sues_base_url + CAMPUS_CARD_INDEX_PATH

# 加密密钥文件
KEY_FILE = DATA_DIR / "secret.key"

# 请求超时（秒）
REQUEST_TIMEOUT = 10

# 缓存 ddddocr 实例
_ocr_instance = None


def _get_ocr():
    """获取 OCR 实例（懒加载，避免重复初始化）"""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = ddddocr.DdddOcr(show_ad=False)
    return _ocr_instance


# ─── 加密工具 ─────────────────────────────────────────────


def _get_or_create_key() -> bytes:
    """获取或创建加密密钥"""
    _ensure_dir()
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    return key


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _encrypt_password(password: str) -> str:
    """加密密码"""
    key = _get_or_create_key()
    f = Fernet(key)
    return f.encrypt(password.encode()).decode()


def _decrypt_password(encrypted: str) -> str:
    """解密密码"""
    key = _get_or_create_key()
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()


# ─── 存储工具 ─────────────────────────────────────────────


def load_account(user_id: str) -> dict:
    """加载指定用户的校园卡账号"""
    data = load_campus_card_account(user_id)
    # 解密密码
    if "password" in data and data["password"].startswith("gAAAAA"):
        data["password"] = _decrypt_password(data["password"])
    return data


def save_account(user_id: str, username: str, password: str):
    """保存指定用户的校园卡账号（密码加密存储）"""
    encrypted = _encrypt_password(password)
    save_campus_card_account(user_id, username, encrypted)


# ─── 工具函数 ─────────────────────────────────────────────


def recognize_captcha(image_content: bytes) -> str | None:
    """OCR 识别验证码"""
    try:
        ocr = _get_ocr()
        result = ocr.classification(image_content)
        return result if result else None
    except Exception as e:
        logger.error(f"验证码识别失败: {e}")
        return None


def des_encrypt(password: str) -> str:
    """DES-CBC 加密密码（返回 hex 格式）"""
    cipher = DES.new(DES_KEY, DES.MODE_CBC, DES_IV)
    encrypted = cipher.encrypt(pad(password.encode(), DES.block_size))
    return encrypted.hex()


# ─── 登录 ─────────────────────────────────────────────────


async def login(username: str, password: str) -> httpx.AsyncClient | None:
    """登录校园卡系统，返回已认证的 httpx 客户端"""
    try:
        client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )

        # 获取登录页
        resp = await client.get(f"{config.sues_base_url}/epay/person/index")
        resp.raise_for_status()

        # 提取 CSRF token
        csrf_match = re.search(
            r'<meta name="_csrf" content="([^"]+)"/>', resp.text
        )
        csrf_token = csrf_match.group(1) if csrf_match else ""
        if not csrf_token:
            logger.warning("未找到 CSRF token")

        # 提取验证码并识别
        captcha_match = re.search(
            r'<img[^>]+src="([^"]*imageCode[^"]*)"', resp.text
        )
        captcha = None
        if captcha_match:
            captcha_url = captcha_match.group(1)
            if not captcha_url.startswith("http"):
                captcha_url = config.sues_base_url + captcha_url
            captcha_resp = await client.get(captcha_url)
            captcha = recognize_captcha(captcha_resp.content)

        # 提取登录表单 action
        form_match = re.search(
            r'<form[^>]*action="([^"]+)"[^>]*name="loginFr"', resp.text
        )
        if not form_match:
            form_match = re.search(
                r'<form[^>]*name="loginFr"[^>]*action="([^"]+)"', resp.text
            )
        if not form_match:
            logger.warning("未找到登录表单")
            await client.aclose()
            return None

        form_action = form_match.group(1)
        if form_action.startswith("/"):
            form_action = config.sues_base_url + form_action

        # 提取所有隐藏字段
        input_matches = re.findall(
            r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', resp.text
        )
        form_data = dict(input_matches)

        # 添加登录字段
        form_data["j_username"] = username
        form_data["j_password"] = des_encrypt(password)
        if captcha:
            form_data["imageCodeName"] = captcha

        # 提交登录
        headers = {"X-CSRF-TOKEN": csrf_token} if csrf_token else {}
        await client.post(form_action, data=form_data, headers=headers)

        # 验证：访问 H5 首页检查是否显示余额
        h5_resp = await client.get(INDEX_URL)
        h5_resp.raise_for_status()
        if "账户余额" in h5_resp.text:
            return client
        await client.aclose()
        return None
    except httpx.TimeoutException:
        logger.error("登录超时")
        return None
    except Exception as e:
        logger.error(f"登录异常: {e}")
        return None


# ─── 查询 ─────────────────────────────────────────────────


async def query_balance(client: httpx.AsyncClient) -> dict:
    """查询校园卡余额"""
    try:
        resp = await client.get(INDEX_URL)

        # 提取余额
        balance_match = re.search(
            r"账户余额.*?￥\s*([\d.]+)", resp.text, re.DOTALL
        )
        frozen_match = re.search(
            r"冻结余额.*?￥\s*([\d.]+)", resp.text, re.DOTALL
        )

        if balance_match:
            return {
                "retcode": 0,
                "balance": balance_match.group(1),
                "frozen": frozen_match.group(1) if frozen_match else "0.00",
            }
        return {"retcode": -1, "retmsg": "未找到余额信息"}
    except httpx.TimeoutException:
        return {"retcode": -1, "retmsg": "查询超时"}
    except Exception as e:
        return {"retcode": -1, "retmsg": f"查询失败: {e}"}


# ─── 处理器 ───────────────────────────────────────────────

campus_card_query = on_command("校园卡", priority=5, block=True)
campus_card_set = on_command("设置校园卡账号", priority=5, block=True)
campus_card_help = on_command("校园卡帮助", priority=5, block=True)


@campus_card_query.handle()
async def handle_campus_card_query(
    bot: Bot, event: Event, args: Message = CommandArg()
):
    """查询校园卡余额"""
    user_id = str(event.user_id)
    account = load_account(user_id)
    if not account:
        await campus_card_query.finish(
            "未设置账号，请先私聊发送：\n设置校园卡账号 学号 密码"
        )

    # 登录并获取客户端
    client = await login(account["username"], account["password"])
    if not client:
        await campus_card_query.finish("登录失败，请检查账号密码或验证码")

    try:
        # 查询余额
        result = await query_balance(client)
        if result.get("retcode") == 0:
            await campus_card_query.finish(
                f"💳 校园卡余额\n"
                f"━━━━━━━━━━━━\n"
                f"账户余额: ￥{result['balance']}\n"
                f"冻结余额: ￥{result['frozen']}"
            )
        else:
            await campus_card_query.finish(
                f"查询失败: {result.get('retmsg', '未知错误')}"
            )
    finally:
        await client.aclose()


@campus_card_set.handle()
async def handle_campus_card_set(bot: Bot, event: Event, args: Message = CommandArg()):
    """设置校园卡账号（仅私聊）"""
    if event.message_type != "private":
        await campus_card_set.finish("请私聊机器人设置账号")

    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await campus_card_set.finish("格式：设置校园卡账号 学号 密码")

    # 支持密码包含空格
    parts = arg_text.split(maxsplit=1)
    if len(parts) < 2:
        await campus_card_set.finish("格式：设置校园卡账号 学号 密码")

    save_account(str(event.user_id), parts[0], parts[1])
    await campus_card_set.finish(f"校园卡账号设置成功！学号: {parts[0]}")


@campus_card_help.handle()
async def handle_campus_card_help(bot: Bot, event: Event, args: Message = CommandArg()):
    """校园卡帮助"""
    await campus_card_help.finish(
        "💳 校园卡查询帮助\n"
        "━━━━━━━━━━━━\n\n"
        "【使用方式】\n"
        "#校园卡 — 查询余额\n"
        "#校园卡帮助 — 查看帮助\n\n"
        "【首次使用】\n"
        "私聊发送：设置校园卡账号 学号 密码"
    )
