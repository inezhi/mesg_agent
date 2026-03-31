"""
Messaging module - 消息平台对接模块

用于发送文本、图片、文件、视频、链接等消息到消息平台（如企业微信）。
当前为简化版本，仅打印日志，不实际发送消息。
"""

from loguru import logger


def init(config):
    """
    初始化 messaging 模块
    
    Args:
        config: 包含 token, guid, api_url 的配置字典
    """
    logger.info(f"[message] (1)消息组件已初始化，API: {config.get('api_url', '未配置')}")


def send_text(to_id, content):
    """
    发送文本消息
    
    Args:
        to_id: 接收者ID
        content: 消息内容
    
    Returns:
        bool: 是否发送成功
    """
    # 限制日志长度，避免输出过长
    content_preview = content
    logger.info(f"[message] 发送文本消息给 {to_id}: {content_preview}")
    # 这里可以接入真实的消息平台API


    logger.info(f"[message] 消息发送成功，ID: {to_id}, 内容: {content_preview}")
    return True
