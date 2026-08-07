from typing import Literal, cast

import pytest
from pydantic import create_model
from nonebot.adapters import Bot


def fake_qq_c2c_message_event(content: str = "#电费 三期 21 1001"):
    from nonebot.adapters.qq import C2CMessageCreateEvent
    from nonebot.adapters.qq.models import FriendAuthor

    _Fake = create_model("_Fake", __base__=C2CMessageCreateEvent)

    class FakeEvent(_Fake):
        type: Literal["C2C_MESSAGE_CREATE"] = "C2C_MESSAGE_CREATE"
        id: str = "eventid-1"
        timestamp: str = "0"
        author: FriendAuthor = FriendAuthor(user_openid="user1", id="user1")
        content: str = ""

    return FakeEvent(content=content)  # type: ignore[reportCallIssue]


def fake_qq_group_at_message_event(content: str = "<@!10001> #电费 三期 21 1001"):
    from nonebot.adapters.qq import GroupAtMessageCreateEvent
    from nonebot.adapters.qq.models import GroupMemberAuthor

    _Fake = create_model("_Fake", __base__=GroupAtMessageCreateEvent)

    class FakeEvent(_Fake):
        type: Literal["GROUP_AT_MESSAGE_CREATE"] = "GROUP_AT_MESSAGE_CREATE"
        id: str = "eventid-1"
        timestamp: str = "0"
        group_id: str = "gid"
        group_openid: str = "go"
        author: GroupMemberAuthor = GroupMemberAuthor(
            id="member1", bot=False, member_openid="member1"
        )
        content: str = ""

    return FakeEvent(content=content)  # type: ignore[reportCallIssue]


def test_qq_c2c_event_is_private():
    from nonebot_plugin_sues_bill.compat import is_private_event

    assert is_private_event(fake_qq_c2c_message_event())


def test_qq_group_at_event_is_not_private():
    from nonebot_plugin_sues_bill.compat import is_private_event

    assert not is_private_event(fake_qq_group_at_message_event())


def test_onebot_private_event_is_private():
    from fake import fake_private_message_event_v11

    from nonebot_plugin_sues_bill.compat import is_private_event

    assert is_private_event(fake_private_message_event_v11())


def test_onebot_group_event_is_not_private():
    from fake import fake_group_message_event_v11

    from nonebot_plugin_sues_bill.compat import is_private_event

    assert not is_private_event(fake_group_message_event_v11())


@pytest.mark.asyncio
async def test_qq_group_at_preprocessor_enables_command_matching():
    from nonebot.rule import TrieRule

    from nonebot_plugin_sues_bill.compat import strip_qq_group_at_mention

    event = fake_qq_group_at_message_event("<@!10001> #电费 三期 21 1001")
    before = TrieRule.get_value(None, event, {})  # type: ignore[reportArgumentType]
    assert before["command"] is None

    await strip_qq_group_at_mention(event)

    after = TrieRule.get_value(None, event, {})  # type: ignore[reportArgumentType]
    assert after["command"] == ("电费",)
    command_arg = after["command_arg"]
    assert command_arg is not None
    assert command_arg.extract_plain_text() == "三期 21 1001"


@pytest.mark.asyncio
async def test_qq_group_at_preprocessor_keeps_mention_only_message_intact():
    from nonebot.adapters.qq import Message as QQMessage

    from nonebot_plugin_sues_bill.compat import strip_qq_group_at_mention

    event = fake_qq_group_at_message_event("<@!10001>")
    await strip_qq_group_at_mention(event)

    message = event.get_message()
    assert message.extract_plain_text() == ""
    assert isinstance(message, QQMessage)


class _QQBot:
    type = "QQ"


class _OneBotBot:
    type = "OneBot V11"


def test_strip_markdown_lowers_to_plain_text():
    from nonebot_plugin_sues_bill.compat import strip_markdown

    text = (
        "## 标题\n"
        "---\n"
        "- 项目一\n"
        "1. 项目二\n"
        "**加粗** `code` ~~删除~~\n"
        "```\n"
        "block\n"
        "```\n"
        "尾行"
    )
    assert strip_markdown(text) == "标题\n\n项目一\n项目二\n加粗 code 删除\nblock\n尾行"


def test_rewrite_command_prefix_only_touches_commands():
    from nonebot_plugin_sues_bill.compat import rewrite_command_prefix

    text = "## 标题\n- `#电费 记录`\n#校园卡帮助\n参照 # 开头"
    expected = "## 标题\n- `/电费 记录`\n/校园卡帮助\n参照 # 开头"
    assert rewrite_command_prefix(text, "/") == expected


def test_rewrite_command_prefix_keeps_hash_prefix():
    from nonebot_plugin_sues_bill.compat import rewrite_command_prefix

    text = "发送 `#电费` 查询"
    assert rewrite_command_prefix(text, "#") == text


def test_build_reply_uses_markdown_for_qq_bot():
    from nonebot.adapters.qq import MessageSegment as QQMessageSegment

    from nonebot_plugin_sues_bill.compat import build_reply

    reply = build_reply(cast(Bot, _QQBot()), "**标题**\n- 项目")
    assert isinstance(reply, QQMessageSegment)
    assert reply.data["markdown"].content == "**标题**\n- 项目"


def test_build_reply_lowers_to_plain_text_for_other_bots():
    from nonebot_plugin_sues_bill.compat import build_reply

    reply = build_reply(cast(Bot, _OneBotBot()), "**标题**\n- 项目")
    assert reply == "标题\n项目"
