"""
飞书 WebSocket 客户端模块
使用 lark-oapi SDK 建立长连接，实时接收飞书消息事件
"""

import os
import threading
import time
from loguru import logger

# 禁用代理，强制直连
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

try:
    import lark_oapi as lark
    from lark_oapi import im
    LARK_SDK_AVAILABLE = True
except ImportError:
    LARK_SDK_AVAILABLE = False
    logger.warning("[feishu_ws_client] lark-oapi SDK 未安装，请运行: pip install lark-oapi")

import core.feishu_handler as feishu_handler
import core.feishu_messenger as feishu_messenger
import core.llm as llm

_cli = None
_running = False
_reconnect_delay = 10  # 重连间隔（秒）
_processed_messages = {}  # 已处理消息ID字典：{message_id: timestamp}
_message_lock = threading.Lock()  # 线程锁
_dedup_ttl = 3600  # 去重TTL：1小时


def init(config: dict):
    """
    初始化 WebSocket 客户端

    Args:
        config: 包含 app_id, app_secret 的配置字典
    """
    if not LARK_SDK_AVAILABLE:
        raise RuntimeError("lark-oapi SDK 未安装，请运行: pip install lark-oapi")

    app_id = config.get("app_id")
    app_secret = config.get("app_secret")

    if not app_id or not app_secret:
        raise ValueError("飞书配置缺少 app_id 或 app_secret")

    logger.info(f"[feishu_ws_client] WebSocket 客户端初始化成功: app_id={app_id}")

    return app_id, app_secret


def start(app_id: str, app_secret: str):
    """
    启动 WebSocket 连接（后台线程）
    开始监听飞书消息事件

    Args:
        app_id: 飞书应用 ID
        app_secret: 飞书应用密钥
    """
    global _running

    _running = True

    # 在后台线程启动 WebSocket
    thread = threading.Thread(
        target=_run_ws_loop,
        args=(app_id, app_secret),
        daemon=True
    )
    thread.start()

    logger.info("[feishu_ws_client] WebSocket 监听已启动（后台线程）")


def _run_ws_loop(app_id: str, app_secret: str):
    """
    WebSocket 主循环（内部使用）
    负责建立连接、事件处理、自动重连
    """
    global _cli

    while _running:
        try:
            logger.info("[feishu_ws_client] 正在连接飞书 WebSocket...")

            # 创建事件处理器
            event_handler = lark.EventDispatcherHandler.builder("", "") \
                .register_p2_im_message_receive_v1(_on_message_receive) \
                .build()

            # 创建 WebSocket 客户端
            _cli = lark.ws.Client(
                app_id,
                app_secret,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO
            )

            # 启动连接（阻塞）
            _cli.start()

        except Exception as e:
            logger.error(f"[feishu_ws_client] WebSocket 连接异常: {e}")

        # 如果还在运行，等待后重连
        if _running:
            logger.info(f"[feishu_ws_client] {_reconnect_delay}秒后尝试重连...")
            time.sleep(_reconnect_delay)


def _on_message_receive(data: im.v1.P2ImMessageReceiveV1) -> None:
    """
    消息接收事件处理器（异步处理，3秒内立即返回）

    Args:
        data: 飞书 P2ImMessageReceiveV1 事件数据
    """
    global _processed_messages

    try:
        # 获取消息ID用于去重
        message_id = data.event.message.message_id

        # 线程安全检查消息是否已处理
        with _message_lock:
            now = time.time()

            # 清理过期记录
            expired = [mid for mid, ts in _processed_messages.items() if now - ts > _dedup_ttl]
            for mid in expired:
                del _processed_messages[mid]

            # 检查是否已处理
            if message_id in _processed_messages:
                logger.info(f"[feishu_ws_client] 消息已处理，跳过: {message_id}")
                return

            # 记录处理时间
            _processed_messages[message_id] = now

        # 将 SDK 事件转换为 feishu_handler 期望的格式
        event = _convert_to_event_format(data)

        # 解析事件
        open_id, text, chat_type, chat_id, message_id = feishu_handler.parse_event(event)

        logger.info(f"[feishu_ws_client] 💬 收到消息: {text}")

        # 后台线程异步处理 LLM，避免阻塞导致飞书重推
        thread = threading.Thread(
            target=_process_message_async,
            args=(open_id, text, chat_type, chat_id, message_id),
            daemon=True
        )
        thread.start()

    except ValueError as e:
        # 解析失败（如不支持的事件类型、自己发送的消息等）
        logger.info(f"[feishu_ws_client] 消息过滤: {e}")
    except Exception as e:
        logger.error(f"[feishu_ws_client] 处理消息事件失败: {e}")


def _process_message_async(open_id: str, text: str, chat_type: str, chat_id: str, message_id: str):
    """
    后台线程异步处理消息（调用 LLM 并发送回复）

    Args:
        open_id: 发送者 open_id
        text: 消息文本
        chat_type: 聊天类型
        chat_id: 群聊 ID（群聊时使用）
        message_id: 消息 ID（用于创建飞书"回复"）
    """
    try:
        # 调用 LLM 生成回复（使用 dm_{open_id} 作为 session_id 保持上下文）
        session_key = f"dm_{open_id}"
        reply = llm.chat(text, session_key)
        logger.info(f"[feishu_ws_client] 🤖 LLM 回复: {reply}")

        # MVP-4：将 LLM 回复发送回飞书（使用飞书"回复"功能创建带引用线的消息）
        feishu_messenger.reply_message(open_id, reply, chat_type, chat_id, text, message_id)
        logger.info(f"[feishu_ws_client] ✅ 回复已发送给用户")
    except Exception as e:
        logger.error(f"[feishu_ws_client] 异步处理消息失败: {e}")


def _convert_to_event_format(data: im.v1.P2ImMessageReceiveV1) -> dict:
    """
    将 SDK 事件对象转换为 feishu_handler 期望的字典格式

    Args:
        data: P2ImMessageReceiveV1 事件对象

    Returns:
        符合 feishu_handler.parse_event 格式的字典
    """
    return {
        "header": {
            "event_type": "im.message.receive_v1"
        },
        "event": {
            "message": {
                "message_id": data.event.message.message_id,
                "chat_type": data.event.message.chat_type,
                "chat_id": data.event.message.chat_id,
                "content": data.event.message.content,
                "mentions": [
                    {"id": {"open_id": mention.id.open_id}}
                    for mention in (data.event.message.mentions or [])
                ] if data.event.message.mentions else [],
                "sender": {
                    "sender_id": {
                        "open_id": data.event.sender.sender_id.open_id
                    }
                }
            }
        }
    }


def stop():
    """
    停止 WebSocket 连接
    """
    global _running, _cli

    _running = False

    if _cli:
        try:
            # lark ws client 没有显式 stop 方法，通过设置 _running 停止重连
            logger.info("[feishu_ws_client] WebSocket 连接已停止")
        except Exception as e:
            logger.error(f"[feishu_ws_client] 停止 WebSocket 失败: {e}")
