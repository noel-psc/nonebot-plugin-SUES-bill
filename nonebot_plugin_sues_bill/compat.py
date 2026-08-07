"""OneBot V11 与 QQ 官方机器人之间的跨适配器兼容层。"""

import re
from typing import TYPE_CHECKING
from collections.abc import Iterable

from nonebot.message import event_preprocessor
from nonebot.adapters import Bot, Event, Message

if TYPE_CHECKING:
    from nonebot.adapters.qq.models.common import MessageKeyboard

_LEADING_MENTION_TYPES = ("mention_user", "mention_everyone")

_INLINE_MARKS = (("**", ""), ("__", ""), ("~~", ""), ("`", ""))

_CMD_TAG_RE = re.compile(
    r"<qqbot-cmd-(?:input|enter)\s+text=\"([^\"]*)\"(?:\s+show=\"([^\"]*)\")?[^>]*/>"
)


def is_private_event(event: Event) -> bool:
    """判断消息事件是否来自私聊会话。

    QQ 官方机器人中没有「私聊」概念，对应的单聊事件为 C2C 消息。
    """
    if event.get_type() != "message":
        return False
    try:
        from nonebot.adapters.onebot.v11 import PrivateMessageEvent
    except ImportError:
        pass
    else:
        if isinstance(event, PrivateMessageEvent):
            return True
    try:
        from nonebot.adapters.qq import C2CMessageCreateEvent
    except ImportError:
        pass
    else:
        if isinstance(event, C2CMessageCreateEvent):
            return True
    return False


@event_preprocessor
async def strip_qq_group_at_mention(event: Event) -> None:
    """移除公域群 @ 消息开头的机器人提及，使命令前缀匹配正常工作。

    QQ 适配器的 ``GroupAtMessageCreateEvent`` 会把开头的 @ 提及保留为第一个
    消息段，而 NoneBot 的命令前缀匹配只检查第一个文本段，导致 ``on_command``
    无法命中。该事件类型 ``to_me`` 恒为真，开头的机器人提及没有保留意义。
    """
    try:
        from nonebot.adapters.qq import GroupAtMessageCreateEvent
    except ImportError:
        return
    if not isinstance(event, GroupAtMessageCreateEvent):
        return
    message = event.get_message()
    while message and message[0].type in _LEADING_MENTION_TYPES and len(message) > 1:
        message.pop(0)


def _plain_command_tag(match: re.Match) -> str:
    """把可点击命令标签降级为命令本身（``text`` 已含命令前缀）。"""
    return match.group(1)


def strip_markdown(text: str) -> str:
    """把 markdown 文本降级为纯文本,供不支持 markdown 的适配器使用。"""
    lines = []
    in_code_block = False
    for raw_line in text.splitlines():
        line = raw_line
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            lines.append(line)
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s{0,3}>\s?", "", line)
        if re.fullmatch(r"\s*(?:\*{3,}|-{3,})\s*", line):
            lines.append("")
            continue
        line = re.sub(r"^\s*[-*+]\s+", "", line)
        line = re.sub(r"^\s*\d+\.\s+", "", line)
        for mark, replacement in _INLINE_MARKS:
            line = line.replace(mark, replacement)
        line = re.sub(r"(?<!\*)\*(?!\*)", "", line)
        line = re.sub(r"(?<!_)_(?!_)", "", line)
        line = _CMD_TAG_RE.sub(_plain_command_tag, line)
        lines.append(line)
    return "\n".join(lines)


def _command_prefix() -> str:
    """返回当前部署实际生效的命令前缀。

    插件文本中写死的 ``#`` 前缀需随 ``command_start`` 配置自适应
    （QQ 官方机器人通常配置为 ``/``）。
    """
    from nonebot import get_driver

    command_start = get_driver().config.command_start
    if "#" in command_start:
        return "#"
    for start in sorted(command_start, key=len, reverse=True):
        if start:
            return start
    return "#"


def command_prefix() -> str:
    """返回当前部署实际生效的命令前缀（如 ``/`` 或 ``#``）。"""
    return _command_prefix()


def command_input(cmd: str, show: str) -> str:
    """生成 QQ markdown 可点击命令标签，点击后把命令插入输入框。

    ``cmd`` 为不带命令前缀的命令名，``show`` 为用户看到的展示文本。
    其余适配器由 :func:`strip_markdown` 降级为完整命令文本。
    """
    text = f"{_command_prefix()}{cmd}"
    return f'<qqbot-cmd-input text="{text}" show="{show}" reference="false" />'


def quote_block(text: str) -> str:
    """把多行文本转成 QQ markdown 的块引用（每行以 ``> `` 开头）。"""
    return "\n".join(f"> {line}" for line in text.splitlines())


def rewrite_command_prefix(text: str, prefix: str) -> str:
    """把文本中的 ``#`` 命令前缀替换为实际前缀。

    仅替换命令起始的 ``#``，不会误伤 markdown 标题（``##`` 及后随空格的 ``#``）。
    """
    if prefix == "#":
        return text
    return re.sub(r"(?<!#)#(?!#)(?=\S)", lambda _match: prefix, text)


def build_keyboard(
    rows: Iterable[Iterable[tuple[str, str, str]]],
) -> "MessageKeyboard":
    """构造 QQ 消息键盘按钮。

    ``rows`` 为按钮行，每行为 ``(id, 标签, 命令)`` 三元组；命令需已含命令前缀。
    """
    from nonebot.adapters.qq.models.common import (
        Action,
        Button,
        Permission,
        RenderData,
        InlineKeyboard,
        MessageKeyboard,
        InlineKeyboardRow,
    )

    keyboard_rows = [
        InlineKeyboardRow(
            buttons=[
                Button(
                    id=button_id,
                    render_data=RenderData(
                        label=label,
                        visited_label=label,
                        style=1,
                    ),
                    action=Action(
                        type=2,
                        permission=Permission(type=2),
                        data=data,
                        enter=False,
                        unsupport_tips="当前客户端版本不支持此按钮",
                    ),
                )
                for button_id, label, data in row
            ]
        )
        for row in rows
    ]
    return MessageKeyboard(content=InlineKeyboard(rows=keyboard_rows))


def build_reply(
    bot: Bot,
    text: str,
    keyboard: "MessageKeyboard | None" = None,
) -> str | Message:
    """生成适配器对应的回复消息。

    QQ 官方机器人使用 markdown 消息渲染（可附带键盘按钮），其余适配器
    降级为纯文本。命令前缀会按当前 ``command_start`` 配置重写（如 ``/``）。
    """
    text = rewrite_command_prefix(text, _command_prefix())
    if getattr(bot, "type", "") == "QQ":
        from nonebot.adapters.qq import Message as QQMessage
        from nonebot.adapters.qq import MessageSegment as QQMessageSegment

        message = QQMessage(QQMessageSegment.markdown(text))
        if keyboard is not None:
            message.append(QQMessageSegment.keyboard(keyboard))
        return message
    return strip_markdown(text)
