# mesg-agent-repo

一个基于 Python 的轻量消息平台 Agent。

语言: [English](README.md) | 简体中文

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#环境要求)
[![Status](https://img.shields.io/badge/status-active-success)](#当前状态)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](#许可证)

## 项目简介

mesg-agent-repo 是一个由 Webhook 驱动的 AI Agent 服务：

- 接收消息平台回调
- 对同一用户短时间内的多条消息进行防抖合并
- 调用 OpenAI 兼容接口进行对话
- 通过消息适配层回发结果
- 提供会话持久化、调度任务与记忆系统扩展点

## 架构概览

```text
Webhook POST -> webhook_server -> debounce -> llm.chat
                                                |
                                                +-> 会话存储 (sys_sessions/*.json)
                                                +-> 调度会话上下文桥接
                                                +-> 记忆模块 (已初始化，检索注入预留)
```

启动初始化顺序：

1. message
2. llm
3. scheduler
4. tools
5. memory
6. debounce

## 目录结构

```text
.
├── main.py
├── config-test.json
├── core/
│   ├── webhook_server.py
│   ├── debounce.py
│   ├── llm.py
│   ├── scheduler.py
│   ├── message.py
│   ├── memory.py
│   ├── tools.py
│   ├── utils.py
│   └── mcp_client.py
├── sys_sessions/
├── sys_memory_db/
└── workspace/
    └── files/
```

## 环境要求

- Python 3.10+
- macOS / Linux / Windows

建议安装依赖：

```bash
pip install loguru croniter lancedb numpy
```

## 快速开始

1. 准备配置文件（参考下文配置说明）。
2. 可选：通过环境变量指定配置路径。
3. 启动服务。

```bash
export AGENT_CONFIG=./config-test.json
python main.py
```

健康检查：

```bash
curl http://127.0.0.1:8080/
```

预期返回：

```json
{"status":"ok"}
```

## 配置说明

默认读取仓库根目录下的 config-test.json。
可通过 AGENT_CONFIG 覆盖。

示例配置：

```json
{
  "owner_ids": ["user_0", "user_1"],
  "workspace": "./workspace",
  "port": 8080,
  "debounce_seconds": 3.0,
  "message": {
    "token": "YOUR_TOKEN",
    "guid": "YOUR_GUID",
    "api_url": "https://example.com/api/send"
  },
  "models": {
    "default": "openrouter-xiaomi",
    "providers": {
      "openrouter-xiaomi": {
        "api_base": "https://openrouter.ai/api/v1",
        "api_key": "YOUR_API_KEY",
        "model": "stepfun/step-3.5-flash:free",
        "max_tokens": 8192,
        "timeout": 120,
        "extra_body": {}
      }
    }
  },
  "memory": {
    "enabled": true,
    "embedding_api": {
      "api_base": "https://api.siliconflow.cn/v1/embeddings",
      "api_key": "YOUR_EMBEDDING_API_KEY",
      "model": "Qwen/Qwen3-Embedding-8B",
      "dimension": 1024
    },
    "retrieve_top_k": 5,
    "similarity_threshold": 0.92
  }
}
```

关键字段：

- owner_ids: 只有这些用户会触发 AI 自动回复
- debounce_seconds: 防抖窗口时长（秒）
- models.default: 当前启用的模型提供方
- memory.enabled: 是否启用记忆系统初始化

## Webhook 协议

接口：

- POST /

当前已处理分支：

- cmd == 15000
- msgType in [0, 2]（文本类）

示例请求体：

```json
{
  "data": [
    {
      "cmd": 15000,
      "senderId": "user_1",
      "userId": "agent_1",
      "msgType": 0,
      "msgData": {
        "content": "你好"
      }
    }
  ]
}
```

心跳包会被识别并忽略：

```json
{
  "testMsg": "heartbeat"
}
```

## 数据落盘

- 会话文件: sys_sessions/dm_<sender_id>.json
- 调度会话: sys_sessions/scheduler.json（由 session_key 推导）
- 记忆数据库目录: sys_memory_db/
- 工作区文件目录: workspace/files/

会话窗口上限（llm.py）：

- MAX_SESSION_MESSAGES = 40

## 调度器

后台每 10 秒执行一次任务检查。

支持任务类型：

- once
- cron
- once_cron（代码分支存在，策略仍在演进）

任务触发调用：

- chat_fn(job["message"], "scheduler")

## 当前状态

已实现：

- 多线程 Webhook 处理
- 文本消息防抖与合并
- OpenAI 兼容 LLM 调用流程
- 会话加载、裁剪与持久化
- 调度器初始化/检查/触发
- 记忆模块 LanceDB 初始化

尚未完善：

- message.py 目前为日志模拟发送，未接入真实消息平台 API
- tools.py 仅保留注册框架，缺少实际工具实现
- llm.py 的工具执行循环代码路径当前注释
- llm.py 的图片输入分支当前会抛出 ValueError("暂不支持图片")
- mcp_client.py 目前为空

## 安全建议

- 不要将真实 API Key 提交到仓库。
- 建议使用环境变量或密钥管理系统。
- 如发生泄露，请立即在平台侧轮换密钥。

## 开发路线

1. 接入真实消息发送 API
2. 完成工具定义与执行闭环
3. 打通记忆检索注入链路
4. 增加 requirements.txt 与基础测试

## 贡献指南

欢迎提 Issue 和 PR。

建议流程：

1. 创建功能分支
2. 提交最小且聚焦的改动
3. 本地验证启动与健康检查
4. 在 PR 中说明变更动机与验证步骤

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE)。