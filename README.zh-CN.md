# mesg-agent-repo

一个基于 Python 的轻量消息平台 Agent，支持飞书（Feishu/Lark）集成。

语言: [English](README.md) | 简体中文

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#环境要求)
[![Status](https://img.shields.io/badge/status-active-success)](#当前状态)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](#许可证)

## 项目简介

mesg-agent-repo 是一个由 Webhook 驱动的 AI Agent 服务：

- 接收消息平台回调（支持飞书、Webhook）
- 对同一用户短时间内的多条消息进行防抖合并
- 调用 OpenAI 兼容接口进行对话
- 通过消息适配层回发结果
- 提供会话持久化、调度任务与记忆系统扩展点
- **完整支持飞书平台**：WebSocket 实时接收、消息回复引用、异步处理

## 架构概览

### 通用流程

```text
Webhook POST -> webhook_server -> debounce -> llm.chat
                                                |
                                                +-> 会话存储 (sys_sessions/*.json)
                                                +-> 调度会话上下文桥接
                                                +-> 记忆模块 (已初始化，检索注入预留)
```

### 飞书集成流程

```text
飞书平台
    |
    +-- WebSocket --> feishu_ws_client --> feishu_handler --> debounce --> llm.chat
    |                                                              |
    +-- Webhook  --> webhook_server --> feishu_handler ------------>|
                                                                         |
    feishu_messenger <--------------------------------------------------+
    |
    +--> 发送回复到飞书
```

**飞书组件：**
- `feishu_ws_client.py` - WebSocket 客户端，实时接收消息
- `feishu_handler.py` - 事件解析和消息处理
- `feishu_messenger.py` - 消息发送，支持回复引用

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
├── config.yaml
├── core/
│   ├── webhook_server.py    # HTTP Webhook 处理器
│   ├── debounce.py          # 消息防抖/合并逻辑
│   ├── llm.py               # LLM 对话接口
│   ├── scheduler.py         # 后台任务调度器
│   ├── message.py           # 消息平台适配器（支持飞书）
│   ├── memory.py            # 基于 LanceDB 的长期记忆
│   ├── tools.py             # 工具注册和执行
│   ├── utils.py             # 工具函数
│   ├── mcp_client.py        # MCP 客户端（预留）
│   ├── feishu_ws_client.py  # 飞书 WebSocket 客户端
│   ├── feishu_handler.py    # 飞书事件处理器
│   └── feishu_messenger.py  # 飞书消息发送器
├── doc/
│   └── feishu/              # 飞书集成文档
├── sys_sessions/            # 会话存储
├── sys_memory_db/           # 记忆数据库
└── workspace/
    └── files/               # 工作空间文件
```

## 环境要求

- Python 3.10+
- macOS / Linux / Windows

建议安装依赖：

```bash
pip install -r requirements.txt
```

## 快速开始

1. 复制示例配置文件并填写实际配置值：

```bash
cp config-example.yaml config.yaml
# 编辑 config.yaml，将所有 YOUR_XXX 替换为实际值
```

2. 可选：通过环境变量指定配置路径。
3. 启动服务。

```bash
export AGENT_CONFIG=./config.yaml
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

默认读取仓库根目录下的 config.yaml。
可通过 AGENT_CONFIG 覆盖。

示例配置：

```yaml
# AI Agent 配置文件
# 用于配置消息平台连接、模型参数、记忆系统等

# 管理员 ID 列表，debounce判断是否回这个人的信息
owner_ids:
  - "user_0"
  - "user_1"

# 工作空间路径
workspace: "./workspace"

# 监听端口
port: 8080

# 消息防抖间隔（秒）
debounce_seconds: 3.0

# 消息平台配置
message:
  platform: "feishu"
  feishu:
    app_id: "cli_xxxxxxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    my_open_id: "ou_xxxxxxxxxxxxxxxx"

# 模型配置
models:
  default: "openrouter-free"
  providers:
    openrouter-free:
      api_base: "https://openrouter.ai/api/v1"
      api_key: "YOUR_API_KEY"
      model: "stepfun/step-3.5-flash:free"
      max_tokens: 8192
      timeout: 120
      extra_body: {}

# 记忆系统配置
memory:
  enabled: true
  embedding_api:
    api_base: "https://api.siliconflow.cn/v1/embeddings"
    api_key: "YOUR_EMBEDDING_API_KEY"
    model: "Qwen/Qwen3-Embedding-8B"
    dimension: 1024
  retrieve_top_k: 5
  similarity_threshold: 0.92
```

关键字段：

- owner_ids: 只有这些用户会触发 AI 自动回复
- debounce_seconds: 防抖窗口时长（秒）
- models.default: 当前启用的模型提供方
- memory.enabled: 是否启用记忆系统初始化
- message.platform: 消息平台类型，目前支持 "feishu"
- message.feishu.app_id: 飞书应用 ID（从 https://open.feishu.cn/app 获取）
- message.feishu.app_secret: 飞书应用密钥
- message.feishu.my_open_id: 机器人自身的 open_id（从 https://open.feishu.cn/document/faq/trouble-shooting/how-to-obtain-openid 获取）

## Webhook 协议

接口：

- POST /

支持的事件类型：

- `im.message.receive_v1` - 接收消息事件

示例请求体（飞书格式）：

```json
{
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
      "content": "{\"text\":\"你好\"}",
      "sender": {
        "sender_id": {
          "open_id": "ou_0XXXXXXXXXXXX"
        },
        "sender_type": "user"
      }
    }
  }
}
```

字段说明：

- `event_type`: 事件类型，目前支持 `im.message.receive_v1`
- `chat_type`: 聊天类型，`p2p`（私聊）或 `group`（群聊）
- `message_type`: 消息类型，目前支持 `text`
- `content`: 消息内容，JSON 字符串格式
- `open_id`: 发送者的唯一标识
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

- **飞书（Feishu/Lark）集成**：完整支持 WebSocket 和 Webhook
  - WebSocket 实时接收消息
  - 消息发送支持回复引用
  - 事件处理和解析
  - 异步消息处理与去重
- 多线程 Webhook 处理
- 文本消息防抖与合并
- OpenAI 兼容 LLM 调用流程
- 会话加载、裁剪与持久化
- 调度器初始化/检查/触发
- 记忆模块 LanceDB 初始化

尚未完善：

- tools.py 仅保留注册框架，缺少实际工具实现
- llm.py 的工具执行循环代码路径当前注释
- llm.py 的图片输入分支当前会抛出 ValueError("暂不支持图片")
- mcp_client.py 目前为空

## 安全建议

- 不要将真实 API Key 提交到仓库。
- 建议使用环境变量或密钥管理系统。
- 如发生泄露，请立即在平台侧轮换密钥。

## 开发路线

1. ~~接入真实消息发送 API~~ ✅ 飞书集成已完成
2. 完成工具定义与执行闭环
3. 打通记忆检索注入链路
4. 增加 requirements.txt 与基础测试
5. 支持飞书图片消息
6. 支持飞书群聊 @ 功能

## 贡献指南

欢迎提 Issue 和 PR。

建议流程：

1. 创建功能分支
2. 提交最小且聚焦的改动
3. 本地验证启动与健康检查
4. 在 PR 中说明变更动机与验证步骤

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE)。