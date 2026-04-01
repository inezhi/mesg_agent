"""
测试 feishu_handler 模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core import feishu_handler


class TestParseEvent:
    """测试 parse_event 函数，主要是针对接收到的json格式进行处理"""

    def test_parse_valid_text_message(self):
        """测试解析有效的文本消息"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_id": "test_001",
                "event_type": "im.message.receive_v1",
                "create_time": "1234567890"
            },
            "event": {
                "message": {
                    "message_id": "om_test_001",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text": "你好"}',
                    "sender": {
                        "sender_id": {
                            "open_id": "ou_xxxxxxxxxxxxxxxx"
                        },
                        "sender_type": "user"
                    }
                }
            }
        }

        open_id, text, chat_type = feishu_handler.parse_event(event_json)

        assert open_id == "ou_xxxxxxxxxxxxxxxx"
        assert text == "你好"
        assert chat_type == "p2p"

    def test_parse_group_message(self):
        """测试解析群聊消息"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.receive_v1"
            },
            "event": {
                "message": {
                    "chat_type": "group",
                    "message_type": "text",
                    "content": '{"text": "群消息"}',
                    "sender": {
                        "sender_id": {
                            "open_id": "ou_group_user"
                        },
                        "sender_type": "user"
                    }
                }
            }
        }

        open_id, text, chat_type = feishu_handler.parse_event(event_json)

        assert chat_type == "group"
        assert text == "群消息"

    def test_filter_self_message(self):
        """测试过滤自己发送的消息"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.receive_v1"
            },
            "event": {
                "message": {
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text": "自己发的"}',
                    "sender": {
                        "sender_id": {
                            "open_id": "ou_self"
                        },
                        "sender_type": "app"  # 自己发的
                    }
                }
            }
        }

        with pytest.raises(ValueError, match="过滤自己发送的消息"):
            feishu_handler.parse_event(event_json)

    def test_unsupported_event_type(self):
        """测试不支持的事件类型"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.recalled_v1"  # 不支持的事件
            },
            "event": {}
        }

        with pytest.raises(ValueError, match="不支持的事件类型"):
            feishu_handler.parse_event(event_json)

    def test_unsupported_message_type(self):
        """测试不支持的消息类型"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.receive_v1"
            },
            "event": {
                "message": {
                    "chat_type": "p2p",
                    "message_type": "image",  # 图片消息
                    "content": '{}',
                    "sender": {
                        "sender_id": {
                            "open_id": "ou_user"
                        },
                        "sender_type": "user"
                    }
                }
            }
        }

        with pytest.raises(ValueError, match="不支持的消息类型"):
            feishu_handler.parse_event(event_json)

    def test_empty_content(self):
        """测试空消息内容"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.receive_v1"
            },
            "event": {
                "message": {
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text": ""}',  # 空内容
                    "sender": {
                        "sender_id": {
                            "open_id": "ou_user"
                        },
                        "sender_type": "user"
                    }
                }
            }
        }

        with pytest.raises(ValueError, match="消息内容为空"):
            feishu_handler.parse_event(event_json)

    def test_missing_open_id(self):
        """测试缺少 open_id"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.receive_v1"
            },
            "event": {
                "message": {
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": '{"text": "你好"}',
                    "sender": {
                        "sender_id": {},  # 缺少 open_id
                        "sender_type": "user"
                    }
                }
            }
        }

        with pytest.raises(ValueError, match="无法获取发送者 open_id"):
            feishu_handler.parse_event(event_json)

    def test_invalid_json_content(self):
        """测试无效的 JSON 内容"""
        event_json = {
            "schema": "2.0",
            "header": {
                "event_type": "im.message.receive_v1"
            },
            "event": {
                "message": {
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": "不是有效的JSON",
                    "sender": {
                        "sender_id": {
                            "open_id": "ou_user"
                        },
                        "sender_type": "user"
                    }
                }
            }
        }

        with pytest.raises(ValueError, match="消息内容JSON解析失败"):
            feishu_handler.parse_event(event_json)


