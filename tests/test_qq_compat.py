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
    from nonebot.adapters.qq import Message as QQMessage

    from nonebot_plugin_sues_bill.compat import build_reply

    reply = build_reply(cast(Bot, _QQBot()), "**标题**\n- 项目")
    assert isinstance(reply, QQMessage)
    assert reply[0].data["markdown"].content == "**标题**\n- 项目"


def test_build_reply_lowers_to_plain_text_for_other_bots():
    from nonebot_plugin_sues_bill.compat import build_reply

    reply = build_reply(cast(Bot, _OneBotBot()), "**标题**\n- 项目")
    assert reply == "标题\n项目"


def test_command_input_generates_clickable_tag_and_strips_to_command():
    from nonebot_plugin_sues_bill.compat import command_input, strip_markdown

    tag = command_input("电费 统计 7", "📊 近7天统计")
    expected = (
        '<qqbot-cmd-input text="#电费 统计 7" show="📊 近7天统计" reference="false" />'
    )
    assert tag == expected
    assert strip_markdown(tag) == "#电费 统计 7"


def test_build_keyboard_builds_command_buttons():
    from nonebot_plugin_sues_bill.compat import build_keyboard

    keyboard = build_keyboard([[("a", "查询", "#电费"), ("b", "统计", "#电费 统计 7")]])
    assert keyboard.content is not None
    rows = keyboard.content.rows
    assert rows is not None
    assert len(rows) == 1
    first_row_buttons = rows[0].buttons
    assert first_row_buttons is not None
    button = first_row_buttons[0]
    assert button.id == "a"
    assert button.render_data is not None
    assert button.render_data.label == "查询"
    assert button.action is not None
    assert button.action.type == 2
    assert button.action.data == "#电费"
