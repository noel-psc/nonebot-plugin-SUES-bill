"""校园卡余额查询模块

需要登录，抓包分析接口后实现具体逻辑。
"""

import json

from nonebot import on_command
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, Event

from .models import DATA_DIR

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


def query_campus_card(username: str, password: str) -> dict:
    """查询校园卡余额

    TODO: 抓包分析接口后实现
    - 登录逻辑
    - 查询余额逻辑
    """
    return {"retcode": -1, "retmsg": "功能尚未实现，请等待后续更新"}


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
            "未设置账号，请先私聊发送【设置校园卡账号 用户名 密码】"
        )

    result = query_campus_card(account["username"], account["password"])
    if result.get("retcode") == 0:
        await campus_card_query.finish(result["retmsg"])
    else:
        await campus_card_query.finish(f"查询失败: {result.get('retmsg', '未知错误')}")


@campus_card_set.handle()
async def handle_campus_card_set(bot: Bot, event: Event, args: Message = CommandArg()):
    if event.message_type != "private":
        await campus_card_set.finish("请私聊机器人设置账号")

    arg_text = args.extract_plain_text().strip()
    if not arg_text:
        await campus_card_set.finish("格式：设置校园卡账号 用户名 密码")

    parts = arg_text.split()
    if len(parts) < 2:
        await campus_card_set.finish("格式：设置校园卡账号 用户名 密码")

    save_account(parts[0], parts[1])
    await campus_card_set.finish(f"校园卡账号设置成功！用户名: {parts[0]}")


@campus_card_help.handle()
async def handle_campus_card_help(bot: Bot, event: Event, args: Message = CommandArg()):
    await campus_card_help.finish(
        "💳 校园卡查询帮助\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "【使用方式】\n"
        "#校园卡 — 查询余额\n"
        "#校园卡帮助 — 查看帮助\n\n"
        "【首次使用】\n"
        "私聊发送：设置校园卡账号 用户名 密码"
    )
