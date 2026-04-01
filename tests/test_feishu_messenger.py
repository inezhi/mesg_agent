"""
测试 feishu_messenger 模块
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from core import feishu_messenger


class TestSplitContent:
    """测试 _split_content 函数"""

    def test_short_content_no_split(self):
        """测试短内容不需要切分"""
        content = "这是一条短消息"
        chunks = feishu_messenger._split_content(content, max_length=3500)

        assert len(chunks) == 1
        assert chunks[0] == content

    def test_long_content_split_by_paragraph(self):
        """测试长内容按段落切分"""
        # 创建超过 3500 字的内容
        paragraph1 = "段落1。" * 500  # 约 2500 字
        paragraph2 = "段落2。" * 500  # 约 2500 字
        content = f"{paragraph1}\n{paragraph2}"

        chunks = feishu_messenger._split_content(content, max_length=3500)

        assert len(chunks) == 2
        assert "段落1" in chunks[0]
        assert "段落2" in chunks[1]

    def test_very_long_paragraph_force_split(self):
        """测试超长段落强制切分"""
        # 单个段落超过 3500 字
        long_paragraph = "A" * 4000
        content = long_paragraph

        chunks = feishu_messenger._split_content(content, max_length=3500)

        assert len(chunks) >= 2
        # 确保每个 chunk 不超过限制
        for chunk in chunks:
            assert len(chunk) <= 3500

    def test_multiple_paragraphs_smart_grouping(self):
        """测试多个短段落智能分组"""
        # 创建多个短段落
        paragraphs = [f"这是第{i}个段落的内容。" * 10 for i in range(10)]
        content = "\n".join(paragraphs)

        chunks = feishu_messenger._split_content(content, max_length=3500)

        # 应该被合并成较少的 chunk
        assert len(chunks) < len(paragraphs)
        # 确保内容完整
        full_content = "".join(chunks)
        assert "第0个段落" in full_content
        assert "第9个段落" in full_content


class TestInit:
    """测试 init 函数"""

    @patch("core.feishu_messenger.Client")
    def test_init_success(self, mock_client_class):
        """测试初始化成功"""
        mock_builder = Mock()  # 代替了真实的 Client 类
        mock_builder.app_id.return_value = mock_builder
        mock_builder.app_secret.return_value = mock_builder
        mock_builder.build.return_value = Mock()
        mock_client_class.builder.return_value = mock_builder

        config = {
            "app_id": "cli_test123",
            "app_secret": "test_secret"
        }

        feishu_messenger.init(config)

        assert feishu_messenger._client is not None
        assert feishu_messenger._app_id == "cli_test123"

    def test_init_missing_config(self):
        """测试缺少配置"""
        config = {"app_id": "cli_test123"}  # 缺少 app_secret

        with pytest.raises(ValueError, match="飞书配置缺少"):
            feishu_messenger.init(config)

    @patch("core.feishu_messenger.LARK_SDK_AVAILABLE", False)
    def test_init_sdk_not_installed(self):
        """测试 SDK 未安装"""
        config = {
            "app_id": "cli_test123",
            "app_secret": "test_secret"
        }

        with pytest.raises(RuntimeError, match="lark-oapi SDK 未安装"):
            feishu_messenger.init(config)


class TestSendSingleMessage:
    """测试 _send_single_message 函数"""

    def setup_method(self):
        """每个测试前重置状态"""
        feishu_messenger._client = None

    @patch("core.feishu_messenger.Client")
    @patch("time.sleep")
    def test_send_success(self, mock_sleep, mock_client_class):
        """测试发送成功"""
        # Mock 成功的响应
        mock_response = Mock()
        mock_response.success.return_value = True

        mock_client = Mock()
        mock_client.im.v1.message.create.return_value = mock_response

        mock_builder = Mock()
        mock_builder.app_id.return_value = mock_builder
        mock_builder.app_secret.return_value = mock_builder
        mock_builder.build.return_value = mock_client
        mock_client_class.builder.return_value = mock_builder

        # 初始化
        feishu_messenger.init({"app_id": "cli_test", "app_secret": "secret"})

        # 应该成功返回，不抛出异常
        feishu_messenger._send_single_message("ou_user", "测试消息", 1, 1)

    @patch("core.feishu_messenger.Client")
    @patch("time.sleep")
    def test_send_retry_then_success(self, mock_sleep, mock_client_class):
        """测试重试后成功"""
        # 第一次失败，第二次成功
        mock_response_fail = Mock()
        mock_response_fail.success.return_value = False
        mock_response_fail.code = 500
        mock_response_fail.msg = "Server Error"

        mock_response_success = Mock()
        mock_response_success.success.return_value = True

        mock_client = Mock()
        mock_client.im.v1.message.create.side_effect = [
            mock_response_fail,
            mock_response_success
        ]

        mock_builder = Mock()
        mock_builder.app_id.return_value = mock_builder
        mock_builder.app_secret.return_value = mock_builder
        mock_builder.build.return_value = mock_client
        mock_client_class.builder.return_value = mock_builder

        feishu_messenger.init({"app_id": "cli_test", "app_secret": "secret"})

        # 应该成功（第二次尝试）
        feishu_messenger._send_single_message("ou_user", "测试消息", 1, 1)

        # 验证 sleep 被调用（指数退避）
        mock_sleep.assert_called_once()

    @patch("core.feishu_messenger.Client")
    @patch("time.sleep")
    def test_send_all_retries_failed(self, mock_sleep, mock_client_class):
        """测试所有重试都失败"""
        mock_response = Mock()
        mock_response.success.return_value = False
        mock_response.code = 500
        mock_response.msg = "Server Error"

        mock_client = Mock()
        mock_client.im.v1.message.create.return_value = mock_response

        mock_builder = Mock()
        mock_builder.app_id.return_value = mock_builder
        mock_builder.app_secret.return_value = mock_builder
        mock_builder.build.return_value = mock_client
        mock_client_class.builder.return_value = mock_builder

        feishu_messenger.init({"app_id": "cli_test", "app_secret": "secret"})

        # 应该抛出异常
        with pytest.raises(RuntimeError, match="发送消息失败"):
            feishu_messenger._send_single_message("ou_user", "测试消息", 1, 1)

        # 验证重试了 3 次
        assert mock_client.im.v1.message.create.call_count == 3
        # 验证 sleep 被调用了 2 次（1s, 2s）
        assert mock_sleep.call_count == 2


class TestSendTextSync:
    """测试 _send_text_sync 函数"""

    @patch("core.feishu_messenger.Client")
    def test_send_short_message_single_chunk(self, mock_client_class):
        """测试发送短消息（单条）"""
        mock_response = Mock()
        mock_response.success.return_value = True

        mock_client = Mock()
        mock_client.im.v1.message.create.return_value = mock_response

        mock_builder = Mock()
        mock_builder.app_id.return_value = mock_builder
        mock_builder.app_secret.return_value = mock_builder
        mock_builder.build.return_value = mock_client
        mock_client_class.builder.return_value = mock_builder

        feishu_messenger.init({"app_id": "cli_test", "app_secret": "secret"})

        feishu_messenger._send_text_sync("ou_user", "短消息")

        # 验证只调用了一次发送
        assert mock_client.im.v1.message.create.call_count == 1

    @patch("core.feishu_messenger.Client")
    def test_send_long_message_multiple_chunks(self, mock_client_class):
        """测试发送长消息（分多条）"""
        mock_response = Mock()
        mock_response.success.return_value = True

        mock_client = Mock()
        mock_client.im.v1.message.create.return_value = mock_response

        mock_builder = Mock()
        mock_builder.app_id.return_value = mock_builder
        mock_builder.app_secret.return_value = mock_builder
        mock_builder.build.return_value = mock_client
        mock_client_class.builder.return_value = mock_builder

        feishu_messenger.init({"app_id": "cli_test", "app_secret": "secret"})

        # 创建超过 3500 字的消息
        long_content = "A" * 4000

        feishu_messenger._send_text_sync("ou_user", long_content)

        # 验证调用了多次发送
        assert mock_client.im.v1.message.create.call_count >= 2


class TestSendText:
    """测试 send_text 函数（异步入口）"""

    def setup_method(self):
        """每个测试前重置状态"""
        feishu_messenger._client = None

    def test_send_text_without_init(self):
        """测试未初始化就发送"""
        with pytest.raises(RuntimeError, match="飞书客户端未初始化"):
            feishu_messenger.send_text("ou_user", "消息")

    @patch("threading.Thread")
    @patch("core.feishu_messenger.Client")
    def test_send_text_starts_thread(self, mock_client_class, mock_thread):
        """测试发送启动后台线程"""
        mock_response = Mock()
        mock_response.success.return_value = True

        mock_client = Mock()
        mock_client.im.v1.message.create.return_value = mock_response

        mock_builder = Mock()
        mock_builder.app_id.return_value = mock_builder
        mock_builder.app_secret.return_value = mock_builder
        mock_builder.build.return_value = mock_client
        mock_client_class.builder.return_value = mock_builder

        feishu_messenger.init({"app_id": "cli_test", "app_secret": "secret"})

        feishu_messenger.send_text("ou_user", "消息")

        # 验证启动了线程
        mock_thread.assert_called_once()
        assert mock_thread.call_args.kwargs['daemon'] is True
