"""
Messaging module - 消息平台对接模块

用于发送文本、图片、文件、视频、链接等消息到消息平台（如飞书）。
支持控制台日志输出和真实消息发送。
"""

from loguru import logger

import core.feishu_messenger as feishu_messenger


_feishu_enabled = False


def init(config):
    """
    初始化 messaging 模块

    Args:
        config: message 配置块（已包含 platform、feishu 等）
    """
    global _feishu_enabled

    platform = config.get("platform")

    if platform == "feishu":
        feishu_config = config.get("feishu", {})
        if feishu_config.get("app_id") and feishu_config.get("app_secret"):
            try:
                feishu_messenger.init(feishu_config)
                _feishu_enabled = True
                logger.info("[message] 飞书消息发送已启用")
            except Exception as e:
                logger.error(f"[message] 飞书初始化失败: {e}")
                raise
        else:
            logger.info("[message] 飞书配置不完整，仅启用控制台输出")
    else:
        logger.info(f"[message] 未知平台: {platform}，仅启用控制台输出")


def send_text(to_id, content):
    """
    发送文本消息

    Args:
        to_id: 接收者ID
        content: 消息内容

    Returns:
        bool: 是否发送成功

    Raises:
        RuntimeError: 发送失败时抛出异常
    """
    logger.info(f"[message] 发送文本消息给 {to_id}: {content[:100]}...")

    # 如果飞书已启用，真实发送
    if _feishu_enabled:
        try:
            feishu_messenger.send_text(to_id, content)
            logger.info(f"[message] 消息已提交发送: {to_id}")
        except Exception as e:
            logger.error(f"[message] 发送失败: {e}")
            raise

    return True
