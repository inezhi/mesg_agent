"""
测试 message 模块
"""

import pytest
from unittest.mock import Mock, patch
from core import message


class TestInit:
    """测试 init 函数"""

    def setup_method(self):
        """每个测试前重置状态"""
        message._feishu_enabled = False

    @patch("core.message.feishu_messenger")
    def test_init_feishu_enabled(self, mock_messenger):
        """测试飞书初始化成功"""
        config = {
            "message": {
                "platform": "feishu",
                "feishu": {
                    "app_id": "cli_test123",
                    "app_secret": "test_secret"
                }
            }
        }

        message.init(config)

        assert message._feishu_enabled is True
        mock_messenger.init.assert_called_once_with(config["message"]["feishu"])

    @patch("core.message.feishu_messenger")
    def test_init_feishu_disabled_incomplete_config(self, mock_messenger):
        """测试飞书配置不完整"""
        config = {
            "message": {
                "platform": "feishu",
                "feishu": {
                    "app_id": "cli_test123"
                    # 缺少 app_secret
                }
            }
        }

        message.init(config)

        assert message._feishu_enabled is False
        mock_messenger.init.assert_not_called()

    @patch("core.message.feishu_messenger")
    def test_init_feishu_init_failure(self, mock_messenger):
        """测试飞书初始化失败"""
        mock_messenger.init.side_effect = RuntimeError("初始化失败")

        config = {
            "message": {
                "platform": "feishu",
                "feishu": {
                    "app_id": "cli_test123",
                    "app_secret": "test_secret"
                }
            }
        }

        with pytest.raises(RuntimeError, match="初始化失败"):
            message.init(config)

    @patch("core.message.feishu_messenger")
    def test_init_unknown_platform(self, mock_messenger):
        """测试未知平台"""
        config = {
            "message": {
                "platform": "wechat"
            }
        }

        message.init(config)

        assert message._feishu_enabled is False
        mock_messenger.init.assert_not_called()

    @patch("core.message.feishu_messenger")
    def test_init_no_platform(self, mock_messenger):
        """测试没有平台配置"""
        config = {"message": {}}

        message.init(config)

        assert message._feishu_enabled is False


class TestSendText:
    """测试 send_text 函数"""

    def setup_method(self):
        """每个测试前重置状态"""
        message._feishu_enabled = False

    @patch("core.message.feishu_messenger")
    def test_send_text_with_feishu_enabled(self, mock_messenger):
        """测试飞书启用时发送"""
        message._feishu_enabled = True

        result = message.send_text("ou_user", "测试消息")

        assert result is True
        mock_messenger.send_text.assert_called_once_with("ou_user", "测试消息")

    @patch("core.message.feishu_messenger")
    def test_send_text_with_feishu_disabled(self, mock_messenger):
        """测试飞书禁用时只记录日志"""
        message._feishu_enabled = False

        result = message.send_text("ou_user", "测试消息")

        assert result is True
        mock_messenger.send_text.assert_not_called()

    @patch("core.message.feishu_messenger")
    def test_send_text_failure_raises_exception(self, mock_messenger):
        """测试发送失败抛出异常"""
        message._feishu_enabled = True
        mock_messenger.send_text.side_effect = RuntimeError("发送失败")

        with pytest.raises(RuntimeError, match="发送失败"):
            message.send_text("ou_user", "测试消息")

    @patch("core.message.feishu_messenger")
    def test_send_text_long_content_truncated_in_log(self, mock_messenger):
        """测试长内容在日志中被截断"""
        message._feishu_enabled = True

        long_content = "A" * 200
        message.send_text("ou_user", long_content)

        # 验证 feishu_messenger 收到完整内容
        call_args = mock_messenger.send_text.call_args
        assert call_args[0][1] == long_content  # 完整内容

    @patch("core.message.feishu_messenger")
    def test_send_text_empty_content(self, mock_messenger):
        """测试发送空内容"""
        message._feishu_enabled = True

        result = message.send_text("ou_user", "")

        assert result is True
        mock_messenger.send_text.assert_called_once_with("ou_user", "")
