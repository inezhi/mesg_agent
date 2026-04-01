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
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
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


def _build_card_content(content: str) -> dict:
    """
    构建新版卡片消息内容 (JSON 2.0)
    支持完整 Markdown 语法：标题、代码块、列表等

    Args:
        content: Markdown 内容

    Returns:
        卡片 JSON 2.0 结构
    """
    return {
        "schema": "2.0",
        "config": {
            "width_mode": "fill"
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": content
                }
            ]
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


def reply_message(open_id: str, reply_text: str, chat_type: str = "p2p"):
    """
    回复飞书消息（MVP-4：将 LLM 回复发送给用户）

    根据聊天类型选择发送方式：
    - p2p：直接发送给用户
    - group：@用户后发送（暂不实现群聊）

    Args:
        open_id: 用户 open_id
        reply_text: LLM 生成的回复内容
        chat_type: 聊天类型，p2p 或 group
    """
    if chat_type == "p2p":
        # 私聊直接发送
        send_text(open_id, reply_text)
        logger.info(f"[feishu_messenger] 已回复用户 {open_id}: {reply_text[:50]}...")
    else:
        # 群聊暂不实现
        logger.warning(f"[feishu_messenger] 群聊回复暂未实现: chat_type={chat_type}")



