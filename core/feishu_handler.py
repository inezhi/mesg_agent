"""
飞书消息处理模块
解析飞书事件 JSON，提取关键信息，调用 debounce.debounce_message() 处理消息
webhook_server.py (收到HTTP请求)
        ↓
parse_event(event_json)  ← 第1步：解析原始JSON，返回 (open_id, text, chat_type)
        ↓
handle_message(open_id, text, chat_type)  ← 第2步：处理业务逻辑
        ↓
调用 debounce.debounce_message()

"""

import json
from loguru import logger

import core.debounce as debounce


def parse_event(event_json: dict) -> tuple[str, str, str, str, str]:
    """
    解析飞书事件 JSON，提取关键信息

    Args:
        event_json: 飞书 im.message.receive_v1 事件格式

    Returns:
        (open_id, text, chat_type, chat_id, message_id)

    Raises:
        ValueError: 解析失败或消息格式不支持
    """
    try:
        event_type = event_json.get("header", {}).get("event_type")
        if event_type != "im.message.receive_v1":
            raise ValueError(f"不支持的事件类型: {event_type}")

        event_data = event_json.get("event", {})
        message = event_data.get("message", {})

        chat_type = message.get("chat_type", "p2p")
        chat_id = message.get("chat_id", "")
        message_id = message.get("message_id", "")

        sender = message.get("sender", {})
        sender_type = sender.get("sender_type")

        if sender_type == "app":
            raise ValueError("过滤自己发送的消息")

        sender_id = sender.get("sender_id", {})
        open_id = sender_id.get("open_id")
        if not open_id:
            raise ValueError("无法获取发送者 open_id")

        msg_type = message.get("message_type")
        # WebSocket 事件可能没有 message_type，通过 content 判断
        if msg_type and msg_type != "text":
            raise ValueError(f"不支持的消息类型: {msg_type}")

        content_str = message.get("content", "{}")
        content_json = json.loads(content_str)
        text = content_json.get("text", "")
        if not text:
            raise ValueError("消息内容为空")

        logger.info(f"[feishu_handler] 解析成功: open_id={open_id}, text={text[:50]}, chat_type={chat_type}")
        return open_id, text, chat_type, chat_id, message_id

    except json.JSONDecodeError as e:
        raise ValueError(f"消息内容JSON解析失败: {e}")
    except Exception as e:
        raise ValueError(f"解析飞书事件失败: {e}")


def handle_message(open_id: str, text: str, chat_type: str = "p2p"):
    """
    处理飞书消息的入口

    Args:
        open_id: 发送者的飞书 open_id
        text: 消息文本内容
        chat_type: 聊天类型，p2p(私聊) 或 group(群聊)
    """
    logger.info(f"[feishu_handler] 开始处理消息: open_id={open_id}, chat_type={chat_type}")

    debounce.debounce_message(open_id, text)

    logger.info(f"[feishu_handler] 消息处理完成: open_id={open_id}")
