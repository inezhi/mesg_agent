"""
LLM 调用 + 工具调用循环 + 会话管理

核心逻辑：用户消息 -> LLM -> 命中工具 -> 执行工具 -> 结果传回 LLM -> ... -> 最终回复
支持多模态：通过 base64 编码将图片发送给 LLM。
"""


from datetime import datetime, timedelta, timezone
from typing import Any
import base64
import json
import os
import threading
import urllib.error
import urllib.request

from loguru import logger

import core.memory as mem_mod
import core.tools as tools

# ============================================================
#  初始化 (由 agent_run.py 在启动时注入)
# ============================================================

_config = {}       # 模型配置
_workspace = ""    # 工作目录
_owner_id = ""     # 管理员 ID
_sessions_dir = "" # 会话存储目录
MAX_SESSION_MESSAGES = 40 # 每个会话保留的最大消息数
CST = timezone(timedelta(hours=8))



def init(models_config, workspace, owner_id, sessions_dir):
    global _config, _workspace, _owner_id, _sessions_dir
    
    _config = models_config
    _workspace = workspace
    _owner_id = owner_id
    _sessions_dir = sessions_dir
    logger.info(f"[llm] (2)LLM 组件已初始化")


# ============================================================
#  LLM API 请求
# ============================================================

def _get_provider():
    """获取配置文件中指定的默认模型供应商"""
    default_name = _config["default"]
    return _config["providers"][default_name]

    # "api_base": "https://openrouter.ai/api/v1",
    # "api_key": "sk-or-v1-6e8b2e9135833a27e5e9b49b0e",
    # "model": "xiaomi/mimo-v2-pro",
    # "max_tokens": 8192

def _call_llm(messages, tool_defs):
    """底层 API 调用：构造请求并发送至 OpenAI 兼容接口"""
    provider = _get_provider()
    url = provider["api_base"].rstrip("/") + "/chat/completions"

    body = {
        "model": provider["model"],
        "messages": messages,
        "tools": tool_defs,
        "max_tokens": provider.get("max_tokens", 8192),
    }
    # 注入额外的请求体参数
    extra = provider.get("extra_body", {})  # 比如temperature、top_p等
    body.update(extra)

    # 构造 HTTP 请求头
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider['api_key']}",
    }

    # 序列化请求体为 JSON 字节流
    # ensure_ascii=False 保证中文正常显示（虽然传输时会转为 UTF-8）
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    # 创建 HTTP 请求对象
    req = urllib.request.Request(url, data=data, headers=headers)
    timeout = provider.get("timeout", 120) # 获取超时设置（默认 120 秒）

    try:
        # 发送请求并等待响应
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 解析 JSON 响应并返回
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # 读取报错详情用于调试 400/422 等参数错误
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        logger.error("[llm] HTTP %d 错误: %s" % (e.code, body_text))
        raise e

# ============================================================
#  会话管理 (Session Management)
# ============================================================

def _load_session(session_key):
    """
    加载会话的历史消息记录，并进行智能截断和记忆压缩
    
    工作流程：
        1. 从文件中读取会话历史
        2. 如果消息数量超过上限，将超出的老消息压缩为长期记忆
        3. 清洗消息序列，确保首条消息符合 API 要求
        4. 返回处理后的消息列表
    
    Args:
        session_key (str): 会话的唯一标识符，用于定位对应的历史文件
        
    Returns:
        list: 处理后的消息列表，每条消息格式为 {"role": str, "content": str, ...}
              如果没有历史记录或读取失败，返回空列表 []
    
    消息上限处理：
        - 当消息数量 > MAX_SESSION_MESSAGES 时，将最旧的消息（前 N 条）移出
        - 移出的消息会异步调用 memory.compress_async() 压缩为长期记忆
        - 只保留最新的 MAX_SESSION_MESSAGES 条消息用于当前会话上下文
    
    序列清洗：
        某些 LLM 要求对话必须以 user 或 system 消息开头
        如果消息列表以 assistant、tool 等角色开头，会被依次移除
        确保返回的消息列表符合 API 格式要求
    
    异常处理：
        如果文件读取失败或 JSON 解析错误，返回空列表，不会中断程序
        
    示例：
        # 假设 MAX_SESSION_MESSAGES = 5
        # 历史有 8 条消息，则：
        # - 前 3 条被压缩到长期记忆
        # - 后 5 条返回用于对话
        # - 如果首条是 assistant，会被移除，直到首条是 user/system
    """
    path = _session_path(session_key) # 得到会话文件路径

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                messages = json.load(f)
            # 如果消息超过上限，将老消息移出并进行异步压缩（转存为长期记忆）
            if len(messages) > MAX_SESSION_MESSAGES:
                evicted = messages[:-MAX_SESSION_MESSAGES]
                messages = messages[-MAX_SESSION_MESSAGES:]
                try:
                    mem_mod.compress_async(evicted, session_key)
                except Exception as e:
                    logger.error("[session] 压缩老消息失败: %s" % e)
            
            # 序列清洗：确保第一条消息是 user 或 system，防止截断导致的 API 报错
            while messages and messages[0].get("role") not in ("user", "system"):
                messages.pop(0)
            return messages
        except Exception:
            return []
    return []

def _session_path(session_key):
    """根据 session_key 生成合法的文件路径"""
    safe = session_key.replace("/", "_").replace(":", "_").replace("\\", "_")
    return os.path.join(_sessions_dir, f"{safe}.json")

def _serialize_assistant_msg(msg_data):
    """
    格式化 AI 响应消息，确保存储格式符合对话历史的要求
    
    该方法将 LLM API 返回的原始消息转换为标准化的存储格式，主要处理：
        1. 普通文本回复（content）
        2. 推理/思考过程（reasoning_content）- 部分模型支持（如 DeepSeek-R1、OpenAI o1）
        3. 工具调用指令（tool_calls）
    
    为什么需要这个方法：
        - API 返回的消息结构可能与存储格式不完全一致
        - 某些模型（如 DeepSeek-R1）会返回 reasoning_content 字段，需要保留
        - 工具调用需要保持特定的嵌套结构，便于后续解析和执行
        - 某些模型要求有 tool_calls 时 content 不能为空，需要兼容处理
    
    Args:
        msg_data (dict): LLM API 返回的原始消息，结构示例：
            {
                "role": "assistant",
                "content": "我来帮你查询天气",  # 可能为 None
                "reasoning_content": "用户询问天气，需要调用天气工具...",  # 可选，推理过程
                "tool_calls": [  # 可选，工具调用列表
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": "{\"city\": \"北京\"}"
                        }
                    }
                ]
            }
    
    Returns:
        dict: 格式化后的消息，适合存储到会话历史文件，结构：
            {
                "role": "assistant",
                "content": "我来帮你查询天气",  # 可能为 None
                "reasoning_content": "用户询问天气，需要调用天气工具...",  # 可选
                "tool_calls": [  # 可选
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": "{\"city\": \"北京\"}"
                        }
                    }
                ]
            }
    
    处理逻辑：
        1. 基础字段：始终包含 role="assistant" 和 content（若为空则设为 None）
        2. 推理内容：如果存在 reasoning_content，原样保留（用于模型调试和思考链追踪）
        3. 工具调用：如果有 tool_calls，则：
           - 确保存在 reasoning_content（某些模型校验要求）
           - 如果没有，自动添加 "reasoning_content": "ok" 作为占位
           - 转换 tool_calls 为标准格式，只保留必要字段
    
    兼容性说明：
        - DeepSeek-R1: 返回 reasoning_content，需要保留供后续分析或展示
        - OpenAI: 不返回 reasoning_content，仅返回 content 和 tool_calls
        - 某些本地模型: 要求有 tool_calls 时必须同时有 content，所以添加占位
    
    存储考虑：
        格式化后的消息会通过 _save_session() 保存到 JSON 文件
        因此需要保证结构简洁且可 JSON 序列化
    """

    # 构建基础消息结构
    result:dict[str, Any] = {"role": "assistant"}  
    # 处理 content 字段：若为 None 或空，转为 None（JSON 中会存为 null）
    result["content"] = msg_data.get("content") or None

    # 处理推理/思考内容（部分模型如 DeepSeek-R1 返回此字段）
    # 保留 reasoning_content 有助于：
    #   - 调试模型思考过程
    #   - 在 UI 中展示思考链
    #   - 后续对话中提供上下文
    reasoning = msg_data.get("reasoning_content")
    if reasoning:
        result["reasoning_content"] = reasoning

    # 处理工具调用
    tool_calls = msg_data.get("tool_calls")
    if tool_calls:
        # 某些 API 要求：当存在 tool_calls 时，必须同时有 content 或 reasoning_content
        # 如果都没有，添加一个占位值以满足格式要求
        if "reasoning_content" not in result:
            result["reasoning_content"] = "ok"
        result["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in tool_calls
        ]
    return result

def _strip_images_for_storage(messages):
    """持久化存储前，将图片数据 URI 替换为文本占位符。
    
    原因：图片 base64 极大，且很多模型不支持在历史消息中重复发送图片。
    """
    cleaned = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            text_parts = []
            for item in msg["content"]:
                if item.get("type") == "text":
                    text_parts.append(item["text"])
                elif item.get("type") == "image_url":
                    text_parts.append("[图片]")
            cleaned.append({"role": "user", "content": "\n".join(text_parts)})
        else:
            cleaned.append(msg)
    return cleaned
    
def _save_session(session_key, messages):
    """保存会话，包含溢出检查和图片清洗"""
    logger.info(f"[llm] 当前消息数: {len(messages)}")
    if len(messages) > MAX_SESSION_MESSAGES:
        evicted = messages[:-MAX_SESSION_MESSAGES]
        messages = messages[-MAX_SESSION_MESSAGES:]

        try:
            from . import memory as mem_mod
            mem_mod.compress_async(evicted, session_key)
            logger.info(f"[llm] 压缩 {len(evicted)} 条消息")
        except Exception as e:
            logger.error(f"[llm] 长期记忆压缩错误: %s" % e)
            
    messages = _strip_images_for_storage(messages)
    path = _session_path(session_key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=None)
    except Exception as e:
        logger.error(f"[llm] 保存失败: {e}")
# ============================================================
#  消息构造
# ============================================================

def _build_user_message(text, images=None):
    """构造用户消息，支持纯文本或图文混排"""
    if not images:
        return {"role": "user", "content": text}
    else:
        raise ValueError("暂不支持图片")

    # content = []
    # if text:
    #     content.append({"type": "text", "text": text})
    # for img_path in images:
    #     if os.path.exists(img_path):
    #         try:
    #             data_url = _image_to_base64_url(img_path)
    #             content.append({
    #                 "type": "image_url",
    #                 "image_url": {"url": data_url}
    #             })
    #         except Exception as e:
    #             logger.error(f"[vision] 图片编码失败 {img_path}: {e}")
    #             content.append({"type": "text", "text": f"[图片加载失败: {img_path}]"})
    # return {"role": "user", "content": content}

# ============================================================
#  系统提示词 (System Prompt)
# ============================================================
def _build_system_prompt():
    """
    构建系统提示词（System Prompt），整合时间信息与人设文件
    
    系统提示词是 LLM 的顶层指令，定义了 AI 助手的身份、行为准则和知识背景。
    该方法通过组合固定模板、动态时间戳和用户自定义的人设文件，生成完整的系统提示。
    
    组成结构（按顺序）：
        1. 角色定义 + 当前时间（动态注入，确保 LLM 知道实时时间）
        2. 可选的人设文件（按顺序拼接）：
           - SOUL.md: 核心人格、价值观、性格特征
           - AGENT.md: 行为规范、能力边界、交互风格
           - USER.md: 用户偏好、个人习惯、特殊要求
    
    文件处理：
        - 文件存在则读取全部内容，不存在则跳过
        - 文件读取失败时静默跳过（不中断流程）
        - 多个文件之间用分隔线 "---" 隔开，保持清晰的结构层次
    
    时间注入：
        使用 CST（中国标准时间，UTC+8）作为当前时区
        格式示例：2025-01-15 14:30:25 CST
        作用：让 LLM 能够理解"今天"、"早上"、"现在几点"等时间相关表达
    
    Returns:
        str: 完整的系统提示词，用于作为 LLM 对话的 system 角色消息
        
    示例输出：
        "你是用户的私人 AI 助手。
        当前系统时间: 2025-01-15 14:30:25 CST
        
        ---
        
        [SOUL.md 内容：我是一个温暖、耐心的助手...]
        
        ---
        
        [AGENT.md 内容：我会用通俗易懂的语言解释问题...]
        
        ---
        
        [USER.md 内容：用户偏好简洁回答，使用中文...]"
    
    注意事项：
        - 如果没有任何人设文件，仍会返回基础的角色定义和时间信息
        - 人设文件的顺序会影响 LLM 的权重分配（后出现的可能覆盖前者的部分设定）
        - 建议保持文件内容简洁，过长的系统提示会消耗 token 并可能分散 LLM 注意力
    """
    now_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")
    parts = [f"你是用户的私人 AI 助手。\n当前系统时间: {now_str}\n\n重要：回复的内容会作为消息发送到用户的IM即时通信平台，所以请尽量简洁，控制在500字以内。\n"]
    for filename in ["SOUL.md", "AGENT.md", "USER.md"]:
        fpath = os.path.join(_workspace, filename)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    parts.append(f.read())
            except Exception: pass
    return "\n\n---\n\n".join(parts)

def _get_recent_scheduler_context():
    """
    跨会话上下文桥接：让主对话 Session 能够感知定时任务的历史输出
    
    问题背景：
        系统可能存在两种对话渠道：
        1. 定时任务会话（scheduler）：主动向用户推送消息（如提醒、报告）
        2. 主对话会话（DM/普通聊天）：用户主动发起的对话
        
    用户看到定时任务推送后，可能会在主对话中回复相关内容：
        "刚才那条提醒是怎么回事？"
        "报告里说的那个数据能再解释一下吗？"
    
    但由于两个会话的历史记录是隔离的，主对话的 LLM 看不到定时任务发送的内容，
    会导致无法理解用户的引用性提问。此函数通过读取定时任务会话的最近输出，
    并将其注入到主对话的系统提示中，实现跨会话的记忆桥接。
    
    工作流程：
        1. 定位定时任务会话文件（session_key="scheduler"）
        2. 检查文件新鲜度（2小时内修改过的才有效）
        3. 逆向遍历消息，找到最新的通过 tool call 发送的消息内容
        4. 截取前800字符（避免提示词过长），返回格式化上下文
        
    关键设计：
        - 只读取 tool call 中名为 "message" 的工具调用
        - 因为定时任务通过 message 工具实际发送消息给用户
        - 直接提取 content 参数，获取真正发送给用户的内容
        
    Returns:
        str: 格式化后的上下文信息，供注入到系统提示词
             如果没有有效的定时任务输出，返回空字符串
             
    返回示例：
        "[系统最近通过定时任务发送了以下内容，用户可能在回复它]:
         【每日报告】今天股票市场上涨2.3%..."
    
    注意事项：
        - 2小时过期机制避免注入过时的信息
        - 800字符截断防止 token 浪费
        - 静默处理所有异常，不影响主对话流程
    """

    sched_path = _session_path("scheduler") # 定时任务会话文件路径
    if not os.path.exists(sched_path): return ""  # 不存在则直接返回空字符串

    # 检查文件修改时间，只使用最近 2 小时内的内容
    # 7200 秒 = 2 小时，避免注入陈旧信息误导 LLM
    mtime = os.path.getmtime(sched_path)
    if datetime.now(CST).timestamp() - mtime > 7200: return ""

    try:
        # 读取定时任务会话的历史消息
        with open(sched_path, "r", encoding="utf-8") as f:
            msgs = json.load(f)
    except Exception: return ""


    # 从最新的消息开始逆向查找，找到最后一条通过 message 工具发送的内容
    sent_content = None
    for msg in reversed(msgs):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("function", {}).get("name") == "message":
                    try:
                        args = json.loads(tc["function"]["arguments"])
                        sent_content = args.get("content", "")
                    except: pass
                    if sent_content: break
        if sent_content: break

    if not sent_content: return ""
    return f"[系统最近通过定时任务发送了以下内容，用户可能在回复它]:\n{sent_content[:800]}"


# ============================================================
#  工具调用循环 (核心逻辑)
# ============================================================

_chat_locks = {}  # 存储每个会话的锁 {session_key: Lock对象}
_chat_locks_lock = threading.Lock()  # 保护 _chat_locks 字典本身的锁

def chat(user_msg, session_key, images=None):
    """对话入口（线程安全）"""
    lock = _get_chat_lock(session_key)   # 获取这个会话的锁
    with lock:  # 加锁，确保同一会话的代码串行执行
        return _chat_inner(user_msg, session_key, images)  # 执行真正的对话逻辑

def _get_chat_lock(session_key):
    with _chat_locks_lock:  # 先锁住字典（防止多线程同时创建锁）
        if session_key not in _chat_locks:
            _chat_locks[session_key] = threading.Lock()  # 每个会话创建一个独立的锁
        return _chat_locks[session_key]  # 返回这个会话的锁

def _chat_inner(user_msg, session_key, images=None):
    """
    对话核心逻辑，包含用户消息处理、工具调用循环、记忆检索、跨会话上下文注入等。
    """
    import time as _time
    t0 = _time.monotonic() 

    # 1. 加载历史记录
    messages = _load_session(session_key)
    messages.append(_build_user_message(user_msg, images))
    logger.info(f"[llm] session_key: {session_key} 历史记录加载完毕: {messages}")

    # 2. 构造基础系统提示词
    system_prompt = _build_system_prompt()
    logger.info(f"[llm] session_key: {session_key} 系统提示词加载完毕: {system_prompt}")

    # 3. 语义搜索：检索相关长期记忆并注入 Prompt

    # try:
    #     from . import memory as mem_mod
    #     query_text = user_msg if isinstance(user_msg, str) else ""
    #     mem_context = mem_mod.retrieve(query_text, session_key)
    #     if mem_context:
    #         system_prompt += "\n\n---\n\n" + mem_context
    # except Exception as e:
    #     logger.error("[chat] 记忆检索失败: %s" % e)
    logger.info(f"[llm] 跳过记忆检索")


    # 4. 注入跨会话上下文
    if session_key != "scheduler":
        sched_ctx = _get_recent_scheduler_context()
        if sched_ctx:
            system_prompt += "\n\n---\n\n" + sched_ctx
    logger.info(f"[llm] 完成跨会话上下文注入")

    t_prep = (_time.monotonic() - t0) * 1000

    # 5. 工具调用循环 (最多迭代 20 次)
    tool_defs = tools.get_definitions()
    ctx = {"owner_id": _owner_id, "workspace": _workspace, "session_key": session_key}
    max_iterations = 20
    t_llm_total = 0
    tool_count = 0

    logger.info(f"[llm] session_key: {session_key} 开始工具调用循环")


    # 回复问题
    for _ in range(max_iterations):
        api_messages = [{"role": "system", "content": system_prompt}] + messages
        # [
        #     {"role": "system", "content": "你是助手"},  
        #     {"role": "user", "content": "你好"},        
        # ]
        logger.info(f"[llm] session_key: {session_key} 发送消息 ==>\n {api_messages}")

        try:
            t_llm_s = _time.monotonic()  # 记录 LLM 调用开始时间
            response = _call_llm(api_messages, tool_defs)
            t_llm_total += (_time.monotonic() - t_llm_s) * 1000
            logger.info(f"[llm] session_key: {session_key} LLM 响应 ==>\n {response}")

        except Exception as e:
            logger.error(f"[chat] LLM 接口调用失败: {e}", exc_info=True)
            _save_session(session_key, messages)
            return f"抱歉，AI 服务暂时不可用: {e}"

        msg = response["choices"][0]["message"]
        messages.append(_serialize_assistant_msg(msg)) # 保存助手回复

        # 如果没有工具调用需求，说明思考结束，返回内容
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            logger.info(f"[llm] session_key: {session_key} 没有工具调用需求，直接返回内容")
            _save_session(session_key, messages)
            logger.info("[性能统计] sync | Preprocess = {:.0f}ms | LLM_Call = {:.0f}s | Tools_Call = {} | Total = {:.0f}ms",
                     t_prep, t_llm_total/1000, tool_count, (_time.monotonic() - t0) * 1000)

            logger.info(f"[llm] session_key: {session_key} ,返回内容成功")
            return msg.get("content", "")

        # 执行工具
        # for tc in tool_calls:
        #     tool_count += 1
        #     try:
        #         func_args = json.loads(tc["function"]["arguments"])
        #         result = tools.execute(tc["function"]["name"], func_args, ctx)
        #     except Exception as e:
        #         logger.error("[chat] 工具 %s 执行崩溃: %s" % (tc["function"]["name"], e), exc_info=True)
        #         result = f"[错误] 工具执行失败: {e}"
        #     messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})

    _save_session(session_key, messages)
    return "处理超时，请稍后重试（达到最大工具迭代次数）。"