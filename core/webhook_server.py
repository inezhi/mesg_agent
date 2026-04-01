"""Webhook 服务器"""

import json
import threading

from loguru import logger
from http.server import BaseHTTPRequestHandler


class Handler(BaseHTTPRequestHandler):
    """
    HTTP 请求处理器：处理 GET 健康检查和 POST 消息回调
    处理两种 HTTP 请求：
    ├── GET  /      → 健康检查（返回服务状态）
    └── POST /      → 处理飞书消息回调

    """

    def do_GET(self):
        """健康检查"""
        logger.info("[http] GET {} from {}", self.path, self.client_address)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def do_POST(self):
        """处理 Webhook 推送数据（飞书格式）"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # 立即返回 200，避免 Webhook 超时重试
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"")

        try:
            data = json.loads(body.decode("utf-8"))
            logger.info("[http] POST {} from {}", self.path, self.client_address)
        except Exception:
            logger.error("[http] POST {} from {} with invalid JSON body", self.path, self.client_address)
            raise

        # 开启异步线程处理业务
        threading.Thread(target=handle_callback, args=(data, ), daemon=True).start()

    def log_message(self, format, *args):
        pass


def handle_callback(data):
    """Webhook 回调总入口：解析飞书格式 JSON 并处理"""

    import core.feishu_handler as feishu_handler

    logger.info(f"[callback] 收到原始数据: {data}")

    # 解析飞书事件（失败会抛出 ValueError）
    open_id, text, chat_type = feishu_handler.parse_event(data)

    # 处理消息（失败会抛出异常）
    feishu_handler.handle_message(open_id, text, chat_type)