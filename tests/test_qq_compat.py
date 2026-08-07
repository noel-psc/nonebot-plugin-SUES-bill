from typing import Literal

import pytest
from pydantic import create_model


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
