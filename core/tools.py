"""
Tool Registry - All LLM-callable tool definitions + implementations

本模块是 Agent 的工具注册中心，负责定义和管理所有 LLM 可调用的工具函数。
工具（Tools）是 Agent 扩展能力的核心机制，允许 LLM 执行外部操作，如：
发送消息、读写文件、执行命令、网络请求等。

设计原则：
    - 集中管理：所有工具集中在此文件，便于维护和审查
    - 声明式注册：通过 @tool 装饰器声明工具的名称、描述、参数和必需字段
    - 无侵入扩展：新增工具只需编写函数并添加装饰器，无需修改其他文件
    - 统一接口：所有工具接收 (args, ctx) 两个参数，返回字符串结果

工具调用流程：
    1. LLM 根据用户输入和工具定义，决定调用哪个工具
    2. LLM 生成符合参数 schema 的 JSON 参数
    3. Agent 框架根据工具名称查找对应的实现函数
    4. 执行工具函数，传入参数和上下文
    5. 工具返回字符串结果（或错误信息）
    6. 结果作为 tool 消息返回给 LLM，继续对话

Adding a new tool:
    1. 在本文件底部编写工具函数
    2. 使用 @tool 装饰器注册
    3. 实现具体功能逻辑
    4. 返回字符串结果（成功或错误信息）

Decorator usage:
    @tool("tool_name", "description", {parameter_schema}, ["required_params"])
    def my_tool(args, ctx):
        return "result string"

    Args:
        tool_name (str): 工具唯一标识符，LLM 通过此名称调用工具
        description (str): 工具功能描述，帮助 LLM 理解何时使用此工具
        parameters (dict): JSON Schema 格式的参数定义
        required (list): 必需参数名称列表（可选）
        
        args (dict): LLM 根据 schema 生成的参数字典
        ctx (dict): 运行时上下文，包含：
            - owner_id: 用户/所有者标识
            - workspace: 工作目录路径
            - session_key: 当前会话标识

示例工具定义：
    @tool(
        "web_search",
        "搜索互联网获取实时信息，当用户询问最新消息、新闻、事实时使用",
        {
            "query": {"type": "string", "description": "搜索关键词"}
        },
        ["query"]
    )
    def web_search(args, ctx):
        query = args["query"]
        # 执行搜索逻辑...
        return f"搜索结果: ..."

注意事项：
    - 工具函数必须返回字符串，即使是错误信息也要转为字符串返回
    - 工具内部应做好异常处理，避免抛出异常导致 Agent 崩溃
    - 耗时操作应考虑超时控制，避免阻塞 Agent 响应
    - 敏感操作（如执行命令、写文件）应有权限校验
"""

import os
from loguru import logger



# ============================================================
#  Tool Registry
# ============================================================

_registry = {}  # name -> {"fn", "definition"}


def get_definitions():
    """Return all tool definitions in OpenAI function calling format"""
    return [entry["definition"] for entry in _registry.values()]




# ============================================================
#  Extra Tools：给工具模块注入外部配置和扩展能力
# ============================================================
_extra_config = {}  # 从外部传入 API 密钥等敏感信息

# 插件目录：位于 tools.py 同级目录下的 plugins 文件夹
_plugins_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")


def init_extra(config):

    """Called by xiaowang.py to pass extra config (search API keys, etc.)"""

    global _extra_config
    _extra_config = config

    # _load_plugins()   # 扫描 plugins/ 目录，自动加载所有插件
    # _load_mcp_servers(config)   # 加载 MCP 协议服务器
    logger.info("[tools] (4)额外工具初始化完成")