"""
AI Agent - 入口模块 (Entry Point)

功能：启动 HTTP 服务器，接收来自社交/通讯平台的回调，触发插件工具调用循环。
模块结构说明：
  agent_run.py     - 入口点：负责配置加载、HTTP 服务、回调解析、消息防抖处理（本文件）
  llm.py           - 核心大脑：负责 LLM 接口调用 + 工具执行循环 + 会话上下文管理
  tools.py         - 工具箱：插件注册中心（所有新功能函数仅在此文件中添加）
  messaging.py     - 通讯封装：对接各大平台 API（支持 文本/图片/文件/视频/链接/CDN）
  scheduler.py     - 内置调度器：处理一次性任务和 Cron 定时任务

运行方式：python3 main.py
"""

# 标准库
import yaml
import os
import sys
from http.server import HTTPServer
from socketserver import ThreadingMixIn

# 第三方
from loguru import logger

# 本项目
import core.webhook_server as webhook_server
import core.llm as llm
import core.memory as mem_mod
import core.message as message
import core.scheduler as scheduler
import core.tools as tools
import core.utils as utils
import core.debounce as debounce
import core.mcp_client as mcp_client
import core.feishu_ws_client as feishu_ws_client


# from log.logger import print_config, print_start
# from core.debounce import Debounce

# ============================================================
#  日志配置 (Logging)
# ============================================================
logger.remove()  # 移除默认handler，自定义配置
# 终端输出：带颜色，简洁清晰
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <6}</level> | - <level>{message}</level>",
    level="DEBUG"
)
# 文件输出：记录完整信息，方便复盘
logger.add(
    "agent_debug.log",
    rotation="10 MB",  # 自动轮转
    retention="3 days",  # 保留3天
    format="{time} | {level} | {name}:{line} | {message}",
    level="DEBUG",
    enqueue=True  # 异步写入，不阻塞Agent主流程
)
utils.print_start()


# ============================================================
#  启动入口 (Main)
# ============================================================
def main():
    # ============================================================
    #  从yaml配置文件中读取配置并解析
    # ============================================================
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))  # 当前py脚本所在目录
    CONFIG_PATH = os.environ.get("AGENT_CONFIG", os.path.join(DATA_DIR, "config.yaml"))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG = yaml.safe_load(f)
    # utils.print_config(CONFIG)

    # 基本配置项解析
    OWNER_IDS = set(str(x) for x in CONFIG.get("owner_ids", []))        # 管理员 ID 列表，debounce判断是否回这个人的信息
    DEBOUNCE_SECONDS = CONFIG.get("debounce_seconds", 3.0)              # 消息防抖间隔（秒）
    WORKSPACE = os.path.abspath(CONFIG.get("workspace", "./workspace")) # 工作空间路径
    PORT = CONFIG.get("port", 8080)                                     # 监听端口

    # ============================================================
    #  必要目录准备
    # ============================================================
    SESSIONS_DIR = os.path.join(DATA_DIR, "_sys_sessions")  # 会话历史记录存储
    JOBS_FILE = os.path.join(DATA_DIR, "sys_jobs.json")    # 定时任务持久化文件
    _mem_db = os.path.join(DATA_DIR, '_sys_memory_db')      # 记忆数据库目录
    FILES_DIR = os.path.join(WORKSPACE, "_files")       # 接收到的媒体文件存储
    

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.makedirs(_mem_db, exist_ok=True)
    os.makedirs(FILES_DIR, exist_ok=True)

    # ============================================================
    #  子模块初始化 (Initialize Modules)
    # ============================================================

    # 1、消息组件初始化（飞书消息平台）
    message.init(CONFIG["message"])

    # 2、初始化 LLM 逻辑层
    owner_id = next(iter(OWNER_IDS), "")
    llm.init(CONFIG["models"], WORKSPACE, owner_id, SESSIONS_DIR)

    # 3、初始化调度器并注入聊天函数，使任务能触发对话
    scheduler.init(JOBS_FILE, llm.chat)

    # 4、初始化额外工具
    tools.init_extra(CONFIG)

    # 5、初始化记忆系统（LanceDB 向量库）
    mem_mod.init(CONFIG, CONFIG.get('models', {}), _mem_db)

    # 6、初始化debounce模块
    debounce.init(DEBOUNCE_SECONDS, OWNER_IDS)

    # 7、初始化飞书 WebSocket 客户端（MVP-2：接收飞书消息）
    try:
        feishu_config = CONFIG.get("message", {}).get("feishu", {})
        if feishu_config.get("app_id") and feishu_config.get("app_secret"):
            app_id, app_secret = feishu_ws_client.init(feishu_config)
            feishu_ws_client.start(app_id, app_secret)
        else:
            logger.warning("[main] 飞书配置不完整，跳过 WebSocket 初始化")
    except Exception as e:
        logger.error(f"[main] 飞书 WebSocket 初始化失败: {e}")


    # ============================================================
    #  启动循环
    # ============================================================
    scheduler.start() # 启动定时任务引擎
    logger.info(f"[agent] starting on port {PORT}")
    logger.info(f"[agent] workspace={WORKSPACE}")
    logger.info(f"[agent] owners={OWNER_IDS}")
    logger.info(f"[agent] model={CONFIG['models']['default']}")
    logger.info(f"[agent] files_dir={FILES_DIR}")

    # 创建多线程 HTTP 服务器：每个请求在独立线程中处理，避免阻塞主线程
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        # 继承了 HTTPServer 的所有HTTP协议处理能力
        # 继承了 ThreadingMixIn 的多线程处理能力
        daemon_threads = True  # 守护线程：主程序退出时自动终止，无需等待

    server = ThreadedHTTPServer(("0.0.0.0", PORT), webhook_server.Handler)

    try:
        # 启动 HTTP 服务器，监听指定端口
        # 启动服务器，永久运行，阻塞当前线程
        logger.info(f"[agent] 服务已启动, Serving on 0.0.0.0:{PORT}")
        server.serve_forever()
    except KeyboardInterrupt:
        # 捕获 Ctrl+C 信号，优雅关闭服务器和 MCP 客户端
        logger.info("[agent] Shutting down, goodbye!")




if __name__ == "__main__":
    main()