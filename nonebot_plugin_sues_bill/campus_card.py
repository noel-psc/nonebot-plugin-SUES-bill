"""校园卡余额查询模块"""

import re
import json
import asyncio
import hashlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import ddddocr
from nonebot import logger, on_command, get_plugin_config
from Crypto.Cipher import DES
from nonebot.params import CommandArg
from nonebot.adapters import Message
from Crypto.Util.Padding import pad
from cryptography.fernet import Fernet
from nonebot.adapters.onebot.v11 import Bot, Event, PrivateMessageEvent

from .config import (
    USER_AGENT,
    BILL_LOAD_PATH,
    BILL_PAGE_PATH,
    REQUEST_TIMEOUT,
    ELECTRIC_PAYBILL_PATH,
    CAMPUS_CARD_INDEX_PATH,
    ELECTRIC_RECHARGE_PATH,
    ELECTRIC_PAY_CONFIRM_PATH,
    Config,
)
from .models import (
    DATA_DIR,
    load_campus_card_account,
    save_campus_card_account,
    get_bound_accounts_for_room,
    subscription_has_bound_account,
)

config = get_plugin_config(Config)
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# 完整 URL
INDEX_URL = config.sues_base_url + CAMPUS_CARD_INDEX_PATH

# 加密密钥文件
KEY_FILE = DATA_DIR / "secret.key"

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


def load_bound_accounts(room_id: int) -> list[dict[str, str]]:
    """Load decrypted accounts explicitly bound to a room for daily settlement."""
    accounts = []
    for account in get_bound_accounts_for_room(room_id):
        encrypted_password = account["password"]
        if encrypted_password.startswith("gAAAAA"):
            account["password"] = _decrypt_password(encrypted_password)
        accounts.append(account)
    return accounts


def save_account(user_id: str, username: str, password: str) -> bool:
    """保存指定用户的校园卡账号（密码加密存储）"""
    encrypted = _encrypt_password(password)
    return save_campus_card_account(user_id, username, encrypted)


def account_saved_message(username: str, has_bound_account: bool) -> str:
    """Describe whether updated credentials still need an explicit room binding."""
    if has_bound_account:
        return (
            f"校园卡账号更新成功！学号: {username}\n"
            "原记录宿舍绑定已保留，统计时会自动同步账单并校正历史。"
        )
    return (
        f"校园卡账号设置成功！学号: {username}\n"
        "如需校正记录宿舍的缴费，请再发送：#电费 记录 绑定"
    )


# ─── 工具函数 ─────────────────────────────────────────────


def recognize_captcha(image_content: bytes) -> str | None:
    """OCR 识别验证码"""
    try:
        ocr = _get_ocr()
        result = ocr.classification(image_content)
        return result if isinstance(result, str) and result else None
    except Exception as e:
        logger.error(f"验证码识别失败: {e}")
        return None


def des_encrypt(password: str) -> str:
    """DES-CBC 加密密码（返回 hex 格式）"""
    cipher = DES.new(config.des_key, DES.MODE_CBC, config.des_iv)
    encrypted = cipher.encrypt(pad(password.encode(), DES.block_size))
    return encrypted.hex()


# ─── 登录 ─────────────────────────────────────────────────


async def login(username: str, password: str) -> httpx.AsyncClient | None:
    """登录校园卡系统，返回已认证的 httpx 客户端"""
    client = httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )
    success = False
    try:
        # 获取登录页
        resp = await client.get(f"{config.sues_base_url}/epay/person/index")
        resp.raise_for_status()

        # 提取 CSRF token
        csrf_match = re.search(r'<meta name="_csrf" content="([^"]+)"/>', resp.text)
        csrf_token = csrf_match.group(1) if csrf_match else ""
        if not csrf_token:
            logger.warning("未找到 CSRF token")

        # 提取验证码并识别
        captcha_match = re.search(r'<img[^>]+src="([^"]*imageCode[^"]*)"', resp.text)
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
            success = True
            return client
        return None
    except httpx.TimeoutException:
        logger.error("登录超时")
        return None
    except Exception as e:
        logger.error(f"登录异常: {e}")
        return None
    finally:
        if not success:
            await client.aclose()


# ─── 查询 ─────────────────────────────────────────────────


async def query_balance(client: httpx.AsyncClient) -> dict:
    """查询校园卡余额"""
    try:
        resp = await client.get(INDEX_URL)

        # 提取余额
        balance_match = re.search(r"账户余额.*?￥\s*([\d.]+)", resp.text, re.DOTALL)
        frozen_match = re.search(r"冻结余额.*?￥\s*([\d.]+)", resp.text, re.DOTALL)

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


async def query_electric_payment_records(
    client: httpx.AsyncClient, since: datetime | None = None
) -> dict:
    """Load new electricity-payment records from reverse-chronological bills.

    The endpoint has no time-range parameter. After the first full sync, pages
    older than the newest cached payment are not requested.
    """

    async def load_page(page_no: int) -> dict:
        resp = await client.get(
            config.sues_base_url + BILL_LOAD_PATH,
            params={"pageno": page_no},
        )
        resp.raise_for_status()
        response_text = resp.text.lstrip()
        if response_text.startswith("<"):
            reason = (
                "账单登录状态已过期"
                if "登录已过期" in response_text
                else "账单接口返回网页而非数据"
            )
            logger.error(
                f"{reason}: status={resp.status_code}, "
                f"content_type={resp.headers.get('content-type', 'unknown')}"
            )
            return {"retcode": -1, "retmsg": reason}
        try:
            payload = json.loads(response_text, strict=False)
        except json.JSONDecodeError as error:
            logger.error(
                "账单接口返回无效 JSON: "
                f"status={resp.status_code}, content_type="
                f"{resp.headers.get('content-type', 'unknown')}, "
                f"line={error.lineno}, column={error.colno}"
            )
            return {"retcode": -1, "retmsg": "账单接口返回无效数据"}
        return (
            payload
            if isinstance(payload, dict)
            else {
                "retcode": -1,
                "retmsg": "账单接口返回无效数据",
            }
        )

    try:
        bill_page = await client.get(config.sues_base_url + BILL_PAGE_PATH)
        bill_page.raise_for_status()
        if "登录已过期" in bill_page.text:
            return {"retcode": -1, "retmsg": "账单登录状态已过期"}
        first_page = await load_page(1)
        if first_page.get("retcode") != 0:
            return {"retcode": -1, "retmsg": first_page.get("retmsg", "账单查询失败")}

        total_pages = max(int(first_page.get("totalpage", 1)), 1)
        records: list[dict[str, object]] = []
        page = first_page
        newest_at: datetime | None = None
        for page_no in range(1, total_pages + 1):
            if page_no > 1:
                page = await load_page(page_no)
                if page.get("retcode") != 0:
                    return {"retcode": -1, "retmsg": "账单查询失败"}
            page_records = page.get("dtls", [])
            oldest_at: datetime | None = None
            for record in page_records:
                created_at = datetime.fromtimestamp(
                    float(record["createtime"]) / 1000, tz=SHANGHAI_TZ
                )
                if newest_at is None or created_at > newest_at:
                    newest_at = created_at
                if oldest_at is None or created_at < oldest_at:
                    oldest_at = created_at
                if (
                    record.get("tradename") != "电费缴费"
                    or int(record.get("status", -1)) != 2
                ):
                    continue
                source_key = hashlib.sha256(
                    json.dumps(record, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                records.append(
                    {
                        "source_key": source_key,
                        "billno": str(record.get("id", "")),
                        "paid_at": created_at.isoformat(),
                        "amount_yuan": float(record["amount"]),
                    }
                )
            if since is not None and oldest_at is not None and oldest_at < since:
                break
        return {
            "retcode": 0,
            "records": records,
            "latest_bill_at": newest_at.isoformat() if newest_at else None,
        }
    except (KeyError, TypeError, ValueError, httpx.HTTPError) as e:
        logger.error(f"缴费记录查询失败: {e}")
        return {"retcode": -1, "retmsg": "缴费记录查询失败"}


async def query_electric_payment_amounts(client: httpx.AsyncClient) -> dict:
    """查询账单中所有成功的电费缴费，并按上海自然日汇总。"""
    result = await query_electric_payment_records(client)
    if result.get("retcode") != 0:
        return result
    amounts: dict[date, float] = {}
    for record in result["records"]:
        paid_at = datetime.fromisoformat(str(record["paid_at"]))
        payment_date = paid_at.astimezone(SHANGHAI_TZ).date()
        amounts[payment_date] = amounts.get(payment_date, 0.0) + float(
            record["amount_yuan"]
        )
    return {"retcode": 0, "amounts": amounts}


async def query_electric_payment_amount(
    client: httpx.AsyncClient, target_date: date
) -> dict:
    """查询指定自然日内成功的电费缴费金额。"""
    result = await query_electric_payment_amounts(client)
    if result.get("retcode") != 0:
        return result
    amounts: dict[date, float] = result["amounts"]
    return {"retcode": 0, "amount": amounts.get(target_date, 0.0)}


# ─── 电费充值 ─────────────────────────────────────────────


def _extract_hidden_input(page_text: str, field_id: str) -> str | None:
    match = re.search(
        rf'<input\s+type="hidden"\s+id="{re.escape(field_id)}"\s+value="([^"]+)"',
        page_text,
    )
    return match.group(1) if match else None


def _extract_csrf(page_text: str) -> str | None:
    match = re.search(r'<meta name="_csrf" content="([^"]+)"', page_text)
    return match.group(1) if match else None


def _extract_csrf_header(page_text: str) -> str:
    match = re.search(r'<meta name="_csrf_header" content="([^"]+)"', page_text)
    return match.group(1) if match else "X-CSRF-TOKEN"


async def recharge_electricity(
    client: httpx.AsyncClient,
    query_params: dict[str, str],
    amount_yuan: float,
) -> dict:
    """从校园卡余额直接为指定宿舍充值电费，无需额外密码。

    流程：查询当前剩余电量 → 生成缴费订单 → 确认支付（账户余额扣款）。
    """
    params = {
        key: str(query_params[key]) for key in ("sysid", "roomid", "areaid", "buildid")
    }
    try:
        ele_result = await client.get(
            config.sues_base_url + ELECTRIC_RECHARGE_PATH, params=params
        )
        ele_result.raise_for_status()
        rest_match = re.search(r'left-degree="([\d.]+)"', ele_result.text)
        rest = rest_match.group(1) if rest_match else ""

        pay_params = {**params, "amount": f"{amount_yuan:g}", "rest": rest}
        paybill_page = await client.get(
            config.sues_base_url + ELECTRIC_PAYBILL_PATH, params=pay_params
        )
        paybill_page.raise_for_status()
        billno = _extract_hidden_input(paybill_page.text, "billno")
        refno = _extract_hidden_input(paybill_page.text, "refno")
        csrf_token = _extract_csrf(paybill_page.text)
        if not billno or not refno or not csrf_token:
            reason = (
                "登录状态已过期，请重新设置校园卡账号"
                if any(
                    keyword in paybill_page.text
                    for keyword in ("登录失效", "登陆失败", "无权限访问", "登录已过期")
                )
                else "缴费订单生成失败"
            )
            logger.error(f"缴费订单页解析失败: {reason}")
            return {"retcode": -1, "retmsg": reason}

        csrf_header = _extract_csrf_header(paybill_page.text)
        headers = {csrf_header: csrf_token}
        confirm = await client.post(
            config.sues_base_url + ELECTRIC_PAY_CONFIRM_PATH,
            data={"billno": billno, "refno": refno},
            headers=headers,
        )
        confirm.raise_for_status()
        try:
            payload = json.loads(confirm.text)
        except json.JSONDecodeError:
            logger.error("缴费确认返回非 JSON 响应")
            return {"retcode": -1, "retmsg": "缴费确认响应异常"}
        if payload.get("retcode") != "0":
            return {
                "retcode": -1,
                "retmsg": str(payload.get("retmsg", "缴费失败")),
            }
        return {
            "retcode": 0,
            "billno": billno,
            "refno": refno,
            "amount_yuan": amount_yuan,
        }
    except httpx.TimeoutException:
        logger.error("电费缴费超时")
        return {"retcode": -1, "retmsg": "缴费超时"}
    except httpx.HTTPError as e:
        logger.error(f"电费缴费请求失败: {e}")
        return {"retcode": -1, "retmsg": "缴费请求失败"}
    except Exception as e:
        logger.error(f"电费缴费异常: {e}")
        return {"retcode": -1, "retmsg": f"缴费异常: {e}"}


# ─── 处理器 ───────────────────────────────────────────────

campus_card_query = on_command("校园卡", priority=5, block=True)
campus_card_set = on_command("设置校园卡账号", priority=5, block=True)
campus_card_help = on_command("校园卡帮助", priority=5, block=True)


@campus_card_query.handle()
async def handle_campus_card_query(
    bot: Bot, event: Event, args: Message = CommandArg()
):
    """查询校园卡余额"""
    user_id = event.get_user_id()
    account = load_account(user_id)
    if not account:
        await campus_card_query.finish(
            "未设置账号，请先私聊发送：\n#设置校园卡账号 学号 密码"
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
    if not isinstance(event, PrivateMessageEvent):
        await campus_card_set.finish("请私聊机器人设置账号")

    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await campus_card_set.finish("格式：#设置校园卡账号 学号 密码")

    # 支持密码包含空格
    parts = arg_text.split(maxsplit=1)
    if len(parts) < 2:
        await campus_card_set.finish("格式：#设置校园卡账号 学号 密码")

    user_id = event.get_user_id()
    if not save_account(user_id, parts[0], parts[1]):
        await campus_card_set.finish("该校园卡账号已由其他用户设置，不能重复绑定")
    has_bound_account = await asyncio.to_thread(subscription_has_bound_account, user_id)
    await campus_card_set.finish(account_saved_message(parts[0], has_bound_account))


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
        "私聊发送：#设置校园卡账号 学号 密码\n"
        "如需校正电费缴费，设置记录宿舍后再发送：#电费 记录 绑定"
    )
