"""OneBot V11 与 QQ 官方机器人之间的跨适配器兼容层。"""

from nonebot.message import event_preprocessor
from nonebot.adapters import Event

_LEADING_MENTION_TYPES = ("mention_user", "mention_everyone")


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
