"""
飞书消息发送模块
使用 lark-oapi SDK 发送消息到飞书
支持智能判断：简单文本用 text，复杂/Markdown 用 interactive 卡片
"""

import json
import re
import threading
import time
from loguru import logger

try:
    from lark_oapi import Client
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, ReplyMessageRequest, ReplyMessageRequestBody
    LARK_SDK_AVAILABLE = True
except ImportError:
    LARK_SDK_AVAILABLE = False
    logger.warning("[feishu_messenger] lark-oapi SDK 未安装")


_client = None
_app_id = None


def init(config: dict):
    """
    初始化飞书客户端

    Args:
        config: 包含 app_id, app_secret 的配置字典
    """
    global _client, _app_id

    if not LARK_SDK_AVAILABLE:
        raise RuntimeError("lark-oapi SDK 未安装，请运行: pip install lark-oapi")

    app_id = config.get("app_id")
    app_secret = config.get("app_secret")

    if not app_id or not app_secret:
        raise ValueError("飞书配置缺少 app_id 或 app_secret")

    _client = Client.builder() \
        .app_id(app_id) \
        .app_secret(app_secret) \
        .build()

    _app_id = app_id
    logger.info(f"[feishu_messenger] 飞书客户端初始化成功: app_id={app_id}")


def send_text(open_id: str, content: str):
    """
    发送文本消息到飞书用户（异步）
    智能判断使用纯文本还是卡片消息

    Args:
        open_id: 接收者的飞书 open_id
        content: 消息内容

    Raises:
        RuntimeError: 发送失败（重试3次后仍失败）
    """
    if not _client:
        raise RuntimeError("飞书客户端未初始化，请先调用 init()")

    thread = threading.Thread(
        target=_send_text_sync,
        args=(open_id, content),
        daemon=True
    )
    thread.start()


def _should_use_card(content: str) -> bool:
    """
    判断是否使用卡片消息

    使用卡片的条件：
    1. 包含 Markdown 标记
    2. 内容超过 200 字且有多行
    3. 包含代码块

    Args:
        content: 消息内容

    Returns:
        是否使用卡片
    """
    # Markdown 标记模式
    markdown_patterns = [
        r'^#{1,6}\s',           # 标题
        r'\*\*.*?\*\*',          # 粗体
        r'\*[^*]+\*',            # 斜体
        r'`[^`]+`',              # 行内代码
        r'```[\s\S]*?```',       # 代码块
        r'^\s*[-*+]\s',         # 无序列表
        r'^\s*\d+\.\s',          # 有序列表
        r'^\s*>\s',              # 引用
        r'\[.*?\]\(.*?\)',       # 链接
        r'!\[.*?\]\(.*?\)',      # 图片
    ]

    # 检查是否包含 Markdown
    has_markdown = any(re.search(pattern, content, re.MULTILINE) for pattern in markdown_patterns)

    # 检查是否较长且多行
    is_long_and_multiline = len(content) > 200 and '\n' in content

    # 检查是否有代码块
    has_code_block = '```' in content

    return has_markdown or is_long_and_multiline or has_code_block


def _build_card_content(content: str, original_message: str = "") -> dict:
    """
    构建新版卡片消息内容 (JSON 2.0)
    支持完整 Markdown 语法：标题、代码块、列表等

    Args:
        content: Markdown 内容
        original_message: 用户原始消息（用于引用显示）

    Returns:
        卡片 JSON 2.0 结构
    """
    elements = []

    # 如果有原始消息，添加引用区域
    if original_message:
        # 截断过长的原始消息
        quoted_text = original_message[:200] + "..." if len(original_message) > 200 else original_message
        # 转义特殊字符
        quoted_text = quoted_text.replace("<", "&lt;").replace(">", "&gt;")
        # 添加引用格式
        quoted_content = f"> **你的问题：**\n> {quoted_text}"

        elements.append({
            "tag": "markdown",
            "content": quoted_content
        })
        # 添加分隔线
        elements.append({
            "tag": "hr"
        })

    # 添加回复内容
    elements.append({
        "tag": "markdown",
        "content": content
    })

    return {
        "schema": "2.0",
        "config": {
            "width_mode": "fill"
        },
        "body": {
            "elements": elements
        }
    }


def _send_text_sync(open_id: str, content: str):
    """
    同步发送文本消息（内部使用）
    智能选择消息类型，支持超长消息分条发送
    """
    use_card = _should_use_card(content)
    msg_type = "interactive" if use_card else "text"

    logger.info(f"[feishu_messenger] 消息类型: {msg_type}, 长度: {len(content)} 字")

    if use_card:
        # 卡片消息暂不支持分条，直接发送
        _send_single_message(open_id, content, 1, 1, use_card=True)
    else:
        # 纯文本支持分条
        chunks = _split_content(content, max_length=3500)
        logger.info(f"[feishu_messenger] 消息分条: 共 {len(chunks)} 条")

        for i, chunk in enumerate(chunks, 1):
            _send_single_message(open_id, chunk, i, len(chunks), use_card=False)


def _split_content(content: str, max_length: int = 3500) -> list[str]:
    """
    按段落切分长消息，尽量保持完整句子

    Args:
        content: 原始消息内容
        max_length: 每条消息最大长度

    Returns:
        切分后的消息列表
    """
    if len(content) <= max_length:
        return [content]

    chunks = []
    paragraphs = content.split('\n')
    current_chunk = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            for i in range(0, len(paragraph), max_length):
                chunks.append(paragraph[i:i + max_length])
            continue

        if len(current_chunk) + len(paragraph) + 1 <= max_length:
            current_chunk += "\n" + paragraph if current_chunk else paragraph
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = paragraph

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def _send_single_message(open_id: str, content: str, index: int, total: int, use_card: bool = False):
    """
    发送单条消息，带指数退避重试

    Args:
        open_id: 接收者 open_id
        content: 消息内容
        index: 当前是第几条
        total: 总共几条
        use_card: 是否使用卡片消息
    """
    max_retries = 3
    base_delay = 1

    for attempt in range(max_retries):
        try:
            logger.info(f"[feishu_messenger] 发送第 {index}/{total} 条 (尝试 {attempt + 1}/{max_retries}, 类型: {'card' if use_card else 'text'})")

            if use_card:
                # 卡片消息
                card_content = _build_card_content(content)
                request = CreateMessageRequest.builder() \
                    .receive_id_type("open_id") \
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(open_id)
                        .msg_type("interactive")
                        .content(json.dumps(card_content))
                        .build()
                    ) \
                    .build()
            else:
                # 纯文本消息
                request = CreateMessageRequest.builder() \
                    .receive_id_type("open_id") \
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(open_id)
                        .msg_type("text")
                        .content(json.dumps({"text": content}))
                        .build()
                    ) \
                    .build()

            response = _client.im.v1.message.create(request)

            if response.success():
                logger.info(f"[feishu_messenger] 第 {index}/{total} 条发送成功")
                return
            else:
                error_msg = f"飞书API错误: code={response.code}, msg={response.msg}"
                logger.error(f"[feishu_messenger] {error_msg}")
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(f"[feishu_messenger] 第 {index}/{total} 条发送失败 (尝试 {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.info(f"[feishu_messenger] 等待 {delay} 秒后重试...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"发送消息失败，已重试 {max_retries} 次: {e}")


def reply_message(open_id: str, reply_text: str, chat_type: str = "p2p", chat_id: str = "", original_message: str = "", message_id: str = ""):
    """
    回复飞书消息（MVP-4：将 LLM 回复发送给用户）

    根据聊天类型选择发送方式：
    - p2p：直接发送给用户
    - group：发送到群聊并 @ 提问者

    如果提供了 message_id，使用飞书的"回复"功能创建带引用线的消息

    Args:
        open_id: 用户 open_id
        reply_text: LLM 生成的回复内容
        chat_type: 聊天类型，p2p 或 group
        chat_id: 群聊 ID（群聊时使用）
        original_message: 用户原始消息（用于引用显示）
        message_id: 消息 ID（用于创建飞书"回复"）
    """
    if message_id:
        # 使用飞书"回复"功能创建带引用线的消息
        _send_reply_in_thread(message_id, reply_text)
        logger.info(f"[feishu_messenger] 已使用回复功能回复消息 {message_id}")
    elif chat_type == "p2p":
        # 私聊直接发送
        _send_reply_with_quote(open_id, reply_text, original_message)
        logger.info(f"[feishu_messenger] 已回复用户 {open_id}: {reply_text[:50]}...")
    elif chat_type == "group":
        # 群聊：发送到群并 @ 提问者
        if not chat_id:
            logger.warning(f"[feishu_messenger] 群聊回复失败: chat_id 为空")
            return
        _send_group_message(chat_id, open_id, reply_text, original_message)
        logger.info(f"[feishu_messenger] 已回复群 {chat_id}: {reply_text[:50]}...")
    else:
        logger.warning(f"[feishu_messenger] 未知的聊天类型: chat_type={chat_type}")


def _send_reply_with_quote(open_id: str, reply_text: str, original_message: str):
    """
    发送带引用原始消息的回复（私聊）

    Args:
        open_id: 用户 open_id
        reply_text: LLM 回复内容
        original_message: 用户原始消息
    """
    if not _client:
        raise RuntimeError("飞书客户端未初始化，请先调用 init()")

    thread = threading.Thread(
        target=_send_reply_with_quote_sync,
        args=(open_id, reply_text, original_message),
        daemon=True
    )
    thread.start()


def _send_reply_with_quote_sync(open_id: str, reply_text: str, original_message: str):
    """
    同步发送带引用的回复（内部使用）

    Args:
        open_id: 用户 open_id
        reply_text: LLM 回复内容
        original_message: 用户原始消息
    """
    max_retries = 3
    base_delay = 1

    for attempt in range(max_retries):
        try:
            logger.info(f"[feishu_messenger] 发送带引用回复到 {open_id} (尝试 {attempt + 1}/{max_retries})")

            # 构建带引用的卡片内容
            card_content = _build_card_content(reply_text, original_message)
            request = CreateMessageRequest.builder() \
                .receive_id_type("open_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(open_id)
                    .msg_type("interactive")
                    .content(json.dumps(card_content))
                    .build()
                ) \
                .build()

            response = _client.im.v1.message.create(request)

            if response.success():
                logger.info(f"[feishu_messenger] 带引用回复发送成功")
                return
            else:
                error_msg = f"飞书API错误: code={response.code}, msg={response.msg}"
                logger.error(f"[feishu_messenger] {error_msg}")
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(f"[feishu_messenger] 带引用回复发送失败 (尝试 {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.info(f"[feishu_messenger] 等待 {delay} 秒后重试...")
                time.sleep(delay)
            else:
                # 如果带引用的发送失败，回退到普通发送
                logger.warning(f"[feishu_messenger] 带引用发送失败，回退到普通发送")
                _send_text_sync(open_id, reply_text)


def _send_group_message(chat_id: str, at_open_id: str, content: str, original_message: str = ""):
    """
    发送群聊消息并 @ 指定用户

    Args:
        chat_id: 群聊 ID
        at_open_id: 要 @ 的用户 open_id
        content: 消息内容
        original_message: 用户原始消息（用于引用显示）
    """
    if not _client:
        raise RuntimeError("飞书客户端未初始化，请先调用 init()")

    thread = threading.Thread(
        target=_send_group_message_sync,
        args=(chat_id, at_open_id, content, original_message),
        daemon=True
    )
    thread.start()


def _send_group_message_sync(chat_id: str, at_open_id: str, content: str, original_message: str = ""):
    """
    同步发送群聊消息（内部使用）

    Args:
        chat_id: 群聊 ID
        at_open_id: 要 @ 的用户 open_id
        content: 消息内容
        original_message: 用户原始消息（用于引用显示）
    """
    max_retries = 3
    base_delay = 1

    # 在消息前添加 @ 用户
    at_text = f"<at user_id=\"{at_open_id}\"></at>\n\n{content}"

    for attempt in range(max_retries):
        try:
            logger.info(f"[feishu_messenger] 发送群消息到 {chat_id} (尝试 {attempt + 1}/{max_retries})")

            # 构建带引用的卡片内容（如果有原始消息）
            card_content = _build_card_content(at_text, original_message)
            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("interactive")
                    .content(json.dumps(card_content))
                    .build()
                ) \
                .build()

            response = _client.im.v1.message.create(request)

            if response.success():
                logger.info(f"[feishu_messenger] 群消息发送成功")
                return
            else:
                error_msg = f"飞书API错误: code={response.code}, msg={response.msg}"
                logger.error(f"[feishu_messenger] {error_msg}")
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(f"[feishu_messenger] 群消息发送失败 (尝试 {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.info(f"[feishu_messenger] 等待 {delay} 秒后重试...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"发送群消息失败，已重试 {max_retries} 次: {e}")


def _send_reply_in_thread(message_id: str, content: str):
    """
    使用飞书"回复"功能发送消息（创建带引用线的回复）

    Args:
        message_id: 要回复的消息 ID
        content: 回复内容
    """
    if not _client:
        raise RuntimeError("飞书客户端未初始化，请先调用 init()")

    thread = threading.Thread(
        target=_send_reply_in_thread_sync,
        args=(message_id, content),
        daemon=True
    )
    thread.start()


def _send_reply_in_thread_sync(message_id: str, content: str):
    """
    同步发送回复消息（内部使用）

    Args:
        message_id: 要回复的消息 ID
        content: 回复内容
    """
    max_retries = 3
    base_delay = 1

    for attempt in range(max_retries):
        try:
            logger.info(f"[feishu_messenger] 发送回复到消息 {message_id} (尝试 {attempt + 1}/{max_retries})")

            # 判断使用纯文本还是卡片
            use_card = _should_use_card(content)

            if use_card:
                # 卡片消息
                card_content = _build_card_content(content)
                request = ReplyMessageRequest.builder() \
                    .message_id(message_id) \
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(json.dumps(card_content))
                        .msg_type("interactive")
                        .build()
                    ) \
                    .build()
            else:
                # 纯文本消息
                request = ReplyMessageRequest.builder() \
                    .message_id(message_id) \
                    .request_body(
                        ReplyMessageRequestBody.builder()
                        .content(json.dumps({"text": content}))
                        .msg_type("text")
                        .build()
                    ) \
                    .build()

            response = _client.im.v1.message.reply(request)

            if response.success():
                logger.info(f"[feishu_messenger] 回复发送成功")
                return
            else:
                error_msg = f"飞书API错误: code={response.code}, msg={response.msg}"
                logger.error(f"[feishu_messenger] {error_msg}")
                raise RuntimeError(error_msg)

        except Exception as e:
            logger.error(f"[feishu_messenger] 回复发送失败 (尝试 {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.info(f"[feishu_messenger] 等待 {delay} 秒后重试...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"发送回复失败，已重试 {max_retries} 次: {e}")



