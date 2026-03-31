"""Webhook 服务器"""

import json
import threading

from loguru import logger
from http.server import BaseHTTPRequestHandler


import core.debounce as debounce



class Handler(BaseHTTPRequestHandler):
    """
    HTTP 请求处理器：处理 GET 健康检查和 POST 消息回调
    处理两种 HTTP 请求：
    ├── GET  /      → 健康检查（返回服务状态）
    └── POST /      → 处理消息回调（企业微信等平台）
    └── POST /test  → 测试接口（直接调用 LLM）
    
    """

    def do_GET(self):
        """健康检查"""
        logger.info("[http] GET {} from {}", self.path, self.client_address)
        self.send_response(200)  # HTTP 状态码 200 表示成功
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def do_POST(self):
        """处理 Webhook 推送数据"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)  # 读取请求体

        # 三行合并成一行，表示"原子操作"
        # 请求成功 + 响应头发送完毕 + 发送内容
        self.send_response(200); self.end_headers(); self.wfile.write(b"")

        try:
            # 尝试解析 JSON 请求体
            data = json.loads(body.decode("utf-8"))
            logger.info("[http] POST {} from {}", self.path, self.client_address)
        except Exception: 
            logger.error("[http] POST {} from {} with invalid JSON body", self.path, self.client_address)
            return

        # 开启异步线程处理业务，防止 Webhook 响应超时
        threading.Thread(target=handle_callback, args=(data, ), daemon=True).start()

    def log_message(self, format, *args): 
        pass # 屏蔽控制台访问日志



def handle_callback(data):
    """Webhook 回调总入口：解析原始 JSON 数据并进行业务分流"""

    logger.info(f"[callback] 收到原始数据: {data}")

    # 过滤非字典格式或测试心跳
    if isinstance(data, dict) and "testMsg" in data:
        logger.info(f"[callback] 收到测试心跳: {data['testMsg']}")
        return
    if not isinstance(data, dict): 
        logger.error("[callback] 收到非字典格式数据: {}", data)
        return

    logger.info("数据格式合法")

    # 提取消息列表（兼容单条和多条格式）
    messages = data.get("data", [])

    # 单条字典，包装成列表
    if isinstance(messages, dict): 
        messages = [messages]
        logger.info(f"[callback] 收到单条消息: {messages[0]}")
    elif not isinstance(messages, list): 
        logger.error("[callback] 收到非列表格式数据: {}", messages)
        return

    for msg in messages:
        if not isinstance(msg, dict): continue

        cmd = msg.get("cmd")              # 指令码
        sender_id = msg.get("senderId")   # 发送者 ID
        msg_type = msg.get("msgType")     # 消息类型码
        msg_data = msg.get("msgData", {}) # 详细负载内容

        # 过滤掉 Agent 自己发出的消息，防止无限递归（自言自语）
        # 在群聊中，的确会收到agent发出去的东西
        if str(sender_id) == str(msg.get("userId")): 
            logger.info(f"[callback] 过滤掉Agent自己发出的消息: {sender_id}")
            continue

        # cmd 15000: 标准聊天消息指令
        if cmd == 15000:
            logger.info(f"[callback] 收到标准聊天消息: {msg}")
            # 文本消息 (0: 普通文本, 2: 引用/回复)
            if msg_type in (0, 2):
                content = msg_data.get("content", "")
                if content:
                    logger.info(f"[callback] 收到文本来自 {sender_id}: {content[:50]}...")
                    debounce.debounce_message(sender_id, content)
            
            # # 图片类消息 (7, 14, 101)
            # elif msg_type in (7, 14, 101):
            #     log.info(f"[callback] 收到图片来自 {sender_id}")
            #     _handle_media_message(sender_id, msg_data, "image")
            
            # # 视频类消息 (22, 23, 103)
            # elif msg_type in (22, 23, 103):
            #     log.info(f"[callback] 收到视频来自 {sender_id}")
            #     _handle_media_message(sender_id, msg_data, "video")
            
            # # 文件类消息 (15: 通用文件, 20/102: 办公文档)
            # elif msg_type in (15, 20, 102):
            #     filename = msg_data.get("filename", msg_data.get("fileName", "unknown"))
            #     log.info(f"[callback] 收到文件来自 {sender_id}: {filename}")
            #     _handle_media_message(sender_id, msg_data, "file", filename)
            
            # # 动态表情 (GIF)
            # elif msg_type in (29, 104):
            #     _handle_media_message(sender_id, msg_data, "GIF")
            
            # # 语音消息
            # elif msg_type == 16:
            #     log.info(f"[callback] 收到语音来自 {sender_id}")
            #     _handle_voice_message(sender_id, msg_data)
            
            # # 链接卡片 (13)
            # elif msg_type == 13:
            #     title = msg_data.get("title", "")
            #     url = msg_data.get("linkUrl", msg_data.get("url", ""))
            #     debounce_message(sender_id, f"[用户分享了链接]\n标题: {title}\nURL: {url}")
            
            # # 位置消息 (6)
            # elif msg_type == 6:
            #     label = msg_data.get("label", msg_data.get("poiname", ""))
            #     debounce_message(sender_id, f"[用户发送了位置: {label}]")
                
            else:
                logger.info(f"[callback] 收到未处理的消息类型 msgType={msg_type}")
        
        # cmd 15500: 系统指令/通知
        elif cmd == 15500:
            logger.info(f"[callback] 系统通知 cmd=15500 类型={msg_type}")
        
        # cmd 11016: 账号状态变更（如掉线/登录）
        elif cmd == 11016:
            logger.info(f"[callback] 账号状态报告: {msg_data.get('code', 0)}")

        else:
            logger.info(f"[callback] 收到未处理的指令 cmd={cmd}")