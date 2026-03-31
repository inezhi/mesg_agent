"""
Memory System - Three-Stage Pipeline

记忆系统 - 三阶段流水线架构

这是一个为 Agent 设计的长期记忆系统，将对话中的有价值信息提取、去重、存储和检索，
让 Agent 能够在不同会话之间记住用户偏好、重要事实和决策。

核心设计理念：
    - 异步处理：压缩和存储不阻塞主对话流程
    - 向量检索：基于语义相似度召回相关记忆
    - 智能去重：避免存储重复或相似度过高的记忆
    - 零延迟缓存：为硬件/语音通道提供预计算上下文

三阶段工作流程：
    1. 压缩 (Compress)：对话历史 → LLM 提取结构化记忆
       输入：被挤出窗口的旧消息
       输出：JSON 格式的记忆条目（事实、关键词、人物、时间、主题）
    
    2. 去重 (Deduplicate)：新记忆 vs 现有记忆 → 余弦相似度判断
       输入：新提取的记忆 + 向量
       逻辑：相似度 > 阈值（默认0.92）则跳过，否则存储
    
    3. 检索 (Retrieve)：用户消息 → 向量化 → LanceDB 搜索 → 返回相关记忆
       输入：当前用户输入
       输出：格式化的记忆文本块，注入到系统提示词

存储方案：
    - LanceDB：嵌入式向量数据库，无需独立服务，数据存储在文件级
    - 向量维度：1024（可配置，匹配 embedding 模型）
    - 支持字段：id, fact, keywords, persons, timestamp, topic, session_key, created_at, vector

向量化：
    - 使用 OpenAI 兼容的 Embedding API
    - 支持任何提供 /embeddings 端点的服务（如 OpenAI、智谱、本地部署）
"""
import json
import logging
import os
import threading
import time
import urllib.request
import uuid

from loguru import logger

# ============================================================
#  Module State (模块全局状态)
# ============================================================

_config = {}        # memory 配置段（包含 embedding_api、阈值等）
_llm_config = {}    # models 配置（用于在压缩时调用 LLM）
_db = None          # LanceDB 数据库连接实例
_table = None       # LanceDB memories 表实例
_enabled = False    # 记忆系统是否启用
_context_cache = {} # 会话级记忆摘要缓存（session_key -> str），为零延迟硬件通道提供预计算结果

# ============================================================
#  Public API (4 functions) - 对外暴露的 4 个核心接口
# ============================================================



def init(config, llm_config, db_path):
    """
    初始化记忆系统：连接 LanceDB + 配置 Embedding
    
    只在 Agent 启动时调用一次，负责：
        1. 检查 memory 是否启用
        2. 验证 embedding API 配置
        3. 连接或创建 LanceDB 数据库和表
        4. 设置全局状态
    
    Args:
        config (dict): 主配置字典，从中读取 memory 配置段
        llm_config (dict): LLM 模型配置，用于压缩时调用 LLM
        db_path (str): LanceDB 数据库文件路径
    
    配置示例（config.json）：
        {
            "memory": {
                "enabled": true,
                "retrieve_top_k": 5,
                "similarity_threshold": 0.92,
                "embedding_api": {
                    "api_base": "https://api.openai.com/v1",
                    "api_key": "sk-xxx",
                    "model": "text-embedding-3-small",
                    "dimension": 1024
                }
            }
        }
    
    注意事项：
        - 如果 embedding_api 缺少 api_key，记忆系统自动禁用
        - LanceDB 表不存在时会自动创建，并插入一条 seed 数据建立 schema
        - 所有初始化错误都会被捕获并记录，不会导致 Agent 崩溃
    """
    global _config, _llm_config, _db, _table, _enabled
    # 获取 memory 配置段
    mem_cfg = config.get("memory", {})
    
    # 检查是否启用
    if not mem_cfg.get("enabled", False):
        logger.info("[memory] Disabled in config")
        return

    # 检查 embedding API 配置
    embedding_cfg = mem_cfg.get("embedding_api", {})
    if not embedding_cfg.get("api_key"):
        logger.error("[memory] No embedding API key, disabled")
        return

    # 存储配置
    _config = mem_cfg
    _llm_config = llm_config

    try:
        import lancedb
        _db = lancedb.connect(db_path)  # 连接数据库（文件不存在时会自动创建目录）
        
        # 打开或创建 memories 表
        try:
            _table = _db.open_table("memories")
            count = _table.count_rows()
            logger.info("[memory] Opened table, {} memories", count)
        except Exception:
            # 表不存在，创建新表并插入 seed 数据以建立 schema
            import numpy as np
            seed = [{
                "id": "seed",
                "fact": "System initialized",
                "keywords": "[]",
                "persons": "[]",
                "timestamp": "",
                "topic": "system",
                "session_key": "init",
                "created_at": time.time(),
                "vector": np.zeros(1024).tolist(),  # 占位向量
            }]
            _table = _db.create_table("memories", seed)
            logger.info("[memory] Created new table")

        _enabled = True
        logger.info("[memory] (5)Memory system initialized, db_path={}", db_path)
    except Exception as e:
        logger.error("[memory] init failed: {}", e, exc_info=True)
