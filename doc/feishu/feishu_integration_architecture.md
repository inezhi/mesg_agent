# 飞书（Feishu/Lark）集成架构设计方案

**版本**: v2.0  
**日期**: 2026-04-01  
**状态**: 设计阶段  

---

## 1. 项目背景与目标

### 1.1 当前系统现状

本项目是一个基于 Python 的 AI Agent 服务，当前架构如下：

```
用户消息 → HTTP Webhook POST → webhook_server.py → debounce.py → llm.chat() → message.send_text()
                                    ↓
                              本地JSON会话存储 + 可选的LanceDB记忆
```

**核心组件**:
- `main.py`: 入口，初始化所有组件，启动HTTP服务器
- `webhook_server.py`: HTTP请求处理器，接收消息回调
- `debounce.py`: 消息防抖合并，管理owner白名单
- `llm.py`: LLM调用、工具循环、会话管理
- `message.py`: 消息发送接口（目前只是打印日志）
- `tools.py`: 工具注册中心
- `scheduler.py`: 定时任务引擎

### 1.2 集成目标

将当前系统接入飞书（Feishu/Lark）企业自建应用，同时**保留原有Webhook能力用于调试**，实现：

1. **双模式接收消息**:
   - Webhook模式：通过HTTP POST接收消息（用于Postman调试）
   - WebSocket模式：通过长连接接收飞书消息（用于生产环境）

2. **统一发送消息**：Agent调用大模型处理完毕后，将回复发送到飞书用户聊天界面

3. **灵活配置**：支持多种模式组合，方便开发和调试

### 1.3 关键约束

- **无公网IP**：WebSocket模式无需公网IP，Webhook模式用于本地调试
- **双模式并存**：同时支持Webhook和WebSocket两种接收方式
- **最小代码量**：以最小的改动实现需求
- **保留HTTP端口**：需要保留HTTP端口用于健康检查、Webhook接收和调试

---

## 2. 技术方案选型

### 2.1 双模式架构对比

| 特性 | Webhook (调试模式) | WebSocket (生产模式) |
|------|-------------------|---------------------|
| **连接方向** | 外部 → 你的服务器（被动接收） | 你的服务器 → 飞书（主动连接） |
| **网络要求** | 本地即可（Postman/内网） | 只需要能访问外网（出向） |
| **使用场景** | 本地调试、Postman测试 | 飞书真实接入 |
| **实时性** | 实时（HTTP POST） | 实时（双向推送） |
| **复杂度** | 简单（HTTP服务器） | 稍复杂（长连接维护） |

### 2.2 为什么选择双模式

```
开发调试阶段                    生产运行阶段
────────────────               ────────────────

Postman ──POST /webhook──→    用户飞书 ──→ 飞书服务器
                              
    你的本地服务器              ──WebSocket──→ 你的服务器
         │                           │
         ↓                           ↓
    控制台查看日志              真实消息流转
    快速验证逻辑                无需公网IP
```

**双模式的优势**:
1. **开发友好**：Webhook模式便于本地调试，无需配置飞书应用
2. **生产就绪**：WebSocket模式支持无公网IP部署
3. **平滑过渡**：调试通过后，直接切换到WebSocket模式即可上线
4. **灵活组合**：支持同时开启两种模式，方便对比验证

### 2.3 SDK选择

选择 **`lark-oapi`** 官方Python SDK，原因如下：

| 方案 | 优点 | 缺点 |
|------|------|------|
| **lark-oapi官方SDK** | 封装完整，自动处理token刷新、重连、事件解析 | 引入外部依赖 |
| **手写WebSocket连接** | 轻量，完全可控 | 需要自己处理鉴权、心跳、重连 |

**决策**: 使用官方SDK，减少开发和维护成本。

---

## 3. 架构设计

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AI Agent 服务                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        消息接收层 (双模式)                           │   │
│  │  ┌──────────────────────┐        ┌──────────────────────────────┐  │   │
│  │  │   Webhook Server     │        │   Feishu WebSocket Client    │  │   │
│  │  │   (Postman/调试)      │        │   (飞书真实接入)              │  │   │
│  │  │                      │        │                              │  │   │
│  │  │   POST /webhook      │        │   长连接接收 im.message      │  │   │
│  │  │   → handle_callback  │        │   → handle_feishu_event      │  │   │
│  │  └──────────┬───────────┘        └──────────────┬───────────────┘  │   │
│  │             │                                    │                  │   │
│  │             └──────────────┬─────────────────────┘                  │   │
│  │                            ↓                                        │   │
│  │                   ┌─────────────────┐                                │   │
│  │                   │   debounce      │                                │   │
│  │                   │   防抖合并       │                                │   │
│  │                   └────────┬────────┘                                │   │
│  │                            ↓                                        │   │
│  │                   ┌─────────────────┐                                │   │
│  │                   │   llm.chat()    │                                │   │
│  │                   │   AI 处理       │                                │   │
│  │                   └────────┬────────┘                                │   │
│  │                            ↓                                        │   │
│  │                   ┌─────────────────┐                                │   │
│  │                   │ message.send()  │                                │   │
│  │                   │   路由层         │                                │   │
│  │                   └────────┬────────┘                                │   │
│  │                            ↓                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│  ┌───────────────────────────┴───────────────────────────────────────┐     │
│  │                      消息发送层 (统一接口)                          │     │
│  │  ┌─────────────────────────────────────────────────────────────┐  │     │
│  │  │              feishu_messenger.send_text()                   │  │     │
│  │  │                                                             │  │     │
│  │  │   根据配置自动选择发送目标：                                  │  │     │
│  │  │   - Webhook 模式 → 打印日志/回写到 webhook 响应               │  │     │
│  │  │   - WebSocket 模式 → 调用飞书 Bot API 真实发送               │  │     │
│  │  └─────────────────────────────────────────────────────────────┘  │     │
│  └───────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 模块职责划分

| 模块 | 职责 | 状态 |
|------|------|------|
| `webhook_server.py` | HTTP服务器，接收Webhook消息（用于调试） | 保留并增强 |
| `feishu_ws_client.py` | WebSocket客户端，接收飞书消息（用于生产） | 新增 |
| `feishu_messenger.py` | 发送消息到飞书 | 新增 |
| `message.py` | 消息发送路由层 | 修改 |
| `main.py` | 初始化流程调整，支持双模式启动 | 修改 |

### 3.3 消息流转时序图

#### 场景1: Webhook调试模式
```
Postman             webhook_server          debounce          llm          message
   │                      │                    │              │              │
   │──POST /webhook──────>│                    │              │              │
   │  {senderId, msg}     │                    │              │              │
   │                      │──handle_callback──>│              │              │
   │                      │                    │──debounce───>│              │
   │                      │                    │              │───chat()────>│
   │                      │                    │              │              │
   │                      │                    │              │<───reply─────│
   │                      │                    │              │              │
   │                      │                    │              │──send_text──>│
   │                      │                    │              │              │──→ 打印日志
   │<──HTTP 200───────────│                    │              │              │
```

#### 场景2: WebSocket生产模式
```
用户飞书          飞书服务器          feishu_ws_client      debounce          llm          feishu_messenger
   │                    │                    │                 │              │                  │
   │──Send message─────>│                    │                 │              │                  │
   │                    │──WebSocket push ──>│                 │              │                  │
   │                    │  im.message        │                 │              │                  │
   │                    │                    │──handle_event──>│              │                  │
   │                    │                    │                 │──debounce───>│                  │
   │                    │                    │                 │              │──chat()─────────>│
   │                    │                    │                 │              │                  │
   │                    │                    │                 │              │<──reply──────────│
   │                    │                    │                 │              │                  │
   │                    │                    │                 │              │──send_text──────>│
   │                    │<───────────────────────────────────────────────────────────────────────│
   │                    │  HTTP POST Send    │                 │              │                  │
   │<──Receive──────────│                    │                 │              │                  │
```

---

## 4. 详细设计

### 4.1 配置文件结构

```yaml
# AI Agent 配置文件 - 双模式飞书集成版

# ========== 管理员配置 ==========
owner_ids:
  - "ou_xxxxxxxxxxxxxxxx"  # 你的飞书 open_id

# ========== 工作空间 ==========
workspace: "./workspace"
port: 8080  # HTTP服务端口（Webhook + 健康检查）
debounce_seconds: 3.0

# ========== 接收模式配置 ==========
# 可选: "webhook" | "websocket" | "both"
receive_mode: "both"

# Webhook 配置（用于Postman调试）
webhook:
  enabled: true
  path: "/webhook"  # 接收端点

# WebSocket 配置（飞书真实接入）
websocket:
  enabled: true
  platform: "feishu"  # "feishu"(国内) 或 "lark"(国际版)
  app_id: "cli_xxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# ========== 发送模式配置 ==========
# 可选: "console" | "feishu" | "both"
send_mode: "both"

# 消息发送配置
message:
  # 控制台输出（调试用）
  console:
    enabled: true
  
  # 飞书发送（真实发送）
  feishu:
    enabled: true
    app_id: "cli_xxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# ========== 模型配置（保持不变） ==========
models:
  default: "your_provider"
  providers:
    your_provider:
      api_base: "https://api.example.com/v1"
      api_key: "sk-xxx"
      model: "gpt-4"
      max_tokens: 8192
      timeout: 120

# ========== 记忆系统配置（保持不变） ==========
memory:
  enabled: true
  # ...
```

### 4.2 模式组合说明

| receive_mode | send_mode | 使用场景 |
|-------------|-----------|---------|
| `webhook` | `console` | 纯本地调试，Postman发送，控制台查看 |
| `webhook` | `feishu` | Postman发送，真实发送到飞书（测试发送功能） |
| `webhook` | `both` | Postman发送，同时控制台输出+真实发送 |
| `websocket` | `console` | 飞书接收，控制台查看（不发送回去） |
| `websocket` | `feishu` | **生产模式**：飞书接收，真实回复 |
| `websocket` | `both` | 飞书接收，控制台输出+真实回复 |
| `both` | `both` | **开发模式**：同时支持Postman和飞书，都输出到控制台和真实发送 |

### 4.3 核心模块设计

#### 4.3.1 webhook_server.py（保留并增强）

**职责**:
1. 保留现有HTTP服务器功能
2. 接收POST /webhook消息
3. 解析消息格式，调用debounce处理
4. 返回HTTP 200响应

**关键设计点**:
- 保持与现有代码兼容
- 支持通过配置启用/禁用

#### 4.3.2 feishu_ws_client.py（WebSocket客户端）

**职责**:
1. 使用lark-oapi SDK建立WebSocket长连接
2. 接收`im.message.receive_v1`事件
3. 解析消息，提取sender_id和content
4. 过滤自己发送的消息（避免循环）
5. 群聊只处理@机器人的消息
6. 调用`debounce.debounce_message()`触发AI处理

**关键设计点**:
- 在后台线程运行，不阻塞主流程
- 自动重连机制由SDK处理
- 只处理文本消息类型

#### 4.3.3 feishu_messenger.py（消息发送器）

**职责**:
1. 根据send_mode配置决定发送目标
2. 支持控制台输出（调试）
3. 支持飞书Bot API真实发送
4. 异步发送，避免阻塞主流程

**关键设计点**:
- 统一接口，上层无需关心发送目标
- 支持多目标同时发送（console + feishu）

#### 4.3.4 message.py（路由层）

**职责**:
1. 初始化时根据配置设置发送模式
2. 保持`send_text()`接口不变
3. 内部调用feishu_messenger

#### 4.3.5 main.py（入口调整）

**职责**:
1. 根据receive_mode配置启动对应服务
2. 初始化feishu_messenger
3. 如启用webhook：启动HTTP服务器
4. 如启用websocket：启动WebSocket客户端
5. 支持graceful shutdown

**启动流程**:
```
1. 加载配置
2. 初始化各子模块（llm、scheduler、tools、memory、debounce）
3. 初始化feishu_messenger（根据send_mode）
4. 根据receive_mode:
   - webhook: 启动HTTP服务器（主线程）
   - websocket: 启动WebSocket客户端（后台线程）
   - both: 同时启动两者
5. 捕获Ctrl+C，优雅关闭所有服务
```

### 4.4 消息处理逻辑

#### 4.4.1 Webhook接收消息处理流程

```
POST /webhook
    ↓
解析JSON: {senderId, msgType, msgData}
    ↓
提取sender_id和content
    ↓
调用debounce.debounce_message(sender_id, content)
    ↓
返回HTTP 200
```

#### 4.4.2 WebSocket接收消息处理流程

```
im.message.receive_v1事件
    ↓
提取sender.sender_id.open_id → sender_id
    ↓
检查sender.sender_type:
  - "app" → 过滤（自己发送的消息）
  - "user" → 继续处理
    ↓
检查message.chat_type:
  - "p2p"（私聊）→ 继续处理
  - "group"（群聊）→ 检查message.mentions是否包含机器人
    ↓
检查message.message_type:
  - "text" → 解析content.text
  - 其他类型 → 忽略
    ↓
调用debounce.debounce_message(sender_id, text)
```

#### 4.4.3 发送消息处理流程

```
llm.chat()返回reply
    ↓
调用message.send_text(to_id, reply)
    ↓
feishu_messenger.send_text(to_id, reply)
    ↓
根据send_mode:
  - console: 打印日志
  - feishu: 调用飞书API发送
  - both: 同时执行以上两者
```

---

## 5. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/webhook_server.py` | 保留/增强 | HTTP服务器，接收Webhook消息（用于调试） |
| `core/feishu_ws_client.py` | 新增 | WebSocket客户端，接收飞书消息（用于生产） |
| `core/feishu_messenger.py` | 新增 | 消息发送器，支持console和feishu双目标 |
| `core/message.py` | 修改 | 适配新的发送器接口 |
| `main.py` | 修改 | 支持双模式启动配置 |
| `requirements.txt` | 修改 | 添加`lark-oapi`依赖 |
| `config-example.yaml` | 修改 | 添加双模式配置示例 |

---

## 6. 依赖管理

### 6.1 新增依赖

```
lark-oapi>=1.0.0
```

### 6.2 完整依赖列表

```
# 原有依赖
PyYAML>=6.0
loguru>=0.7.0
lancedb>=0.5.0
pyarrow>=14.0.0
numpy>=1.24.0

# 新增：飞书官方SDK
lark-oapi>=1.0.0
```

---

## 7. 飞书应用配置指南

### 7.1 创建飞书应用

1. 访问[飞书开放平台](https://open.feishu.cn/app)
2. 点击"创建企业自建应用"
3. 填写应用名称和描述
4. 在"凭证与基础信息"页面复制App ID和App Secret

### 7.2 配置权限

在"权限管理"页面，开通以下权限：

```json
{
  "scopes": {
    "tenant": [
      "im:message",
      "im:message:readonly",
      "im:message:send_as_bot",
      "im:message.p2p_msg:readonly",
      "im:message.group_at_msg:readonly",
      "im:chat.members:bot_access",
      "contact:user.employee_id:readonly"
    ]
  }
}
```

### 7.3 启用机器人能力

在"应用能力" → "机器人"页面：
1. 启用机器人能力
2. 设置机器人名称

### 7.4 配置事件订阅

在"事件订阅"页面：
1. 选择"使用长连接接收事件（WebSocket）"
2. 添加事件：`im.message.receive_v1`

⚠️ **注意**: 配置事件订阅前，确保Agent服务已启动，否则长连接无法建立。

### 7.5 发布应用

在"版本管理与发布"页面：
1. 创建版本
2. 提交审核并发布
3. 等待管理员审批（企业自建应用通常自动通过）

---

## 8. 使用示例

### 8.1 纯Webhook调试模式

```yaml
# config.yaml
receive_mode: "webhook"
send_mode: "console"

webhook:
  enabled: true
  path: "/webhook"
```

**测试**:
```bash
# 启动服务
python main.py

# 使用Postman发送测试消息
curl -X POST http://localhost:8080/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "data": [{
      "cmd": 15000,
      "senderId": "test_user",
      "msgType": 0,
      "msgData": {"content": "你好"}
    }]
  }'
```

### 8.2 WebSocket生产模式

```yaml
# config.yaml
receive_mode: "websocket"
send_mode: "feishu"

websocket:
  enabled: true
  platform: "feishu"
  app_id: "cli_xxxxxxxxxxxx"
  app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

message:
  feishu:
    enabled: true
    app_id: "cli_xxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

**使用**:
1. 启动服务
2. 在飞书中向机器人发送消息
3. 机器人自动回复

### 8.3 双模式开发模式

```yaml
# config.yaml
receive_mode: "both"
send_mode: "both"

# 同时配置webhook和websocket
```

**使用**:
- 既可以用Postman测试
- 也可以用飞书真实接入
- 所有消息都会输出到控制台和真实发送

---

## 9. 关键设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 接收模式 | Webhook + WebSocket | 调试和生产兼顾 |
| 发送模式 | Console + Feishu | 调试和真实发送兼顾 |
| SDK | `lark-oapi` | 官方维护，功能完整 |
| 架构 | 单进程多线程 | 改动最小，易于理解 |
| ID标识 | `open_id` | 全局唯一，永久不变 |

---

## 10. 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| WebSocket连接断开 | 无法接收飞书消息 | SDK自动重连，日志记录 |
| 飞书API限流 | 消息发送失败 | 实现重试机制，指数退避 |
| 配置错误 | 无法连接飞书 | 启动时校验配置，给出明确错误提示 |
| 双模式冲突 | 消息重复处理 | 通过sender_id区分来源，统一处理逻辑 |

---

## 11. 后续扩展建议

1. **支持更多消息类型**: 图片、文件、富文本等
2. **群聊增强**: 支持无需@的群聊模式配置
3. **多账号支持**: 同时接入多个飞书应用
4. **消息加密**: 支持飞书的消息加密功能
5. **交互卡片**: 支持飞书的卡片消息格式

---

## 12. 附录

### 12.1 术语表

| 术语 | 说明 |
|------|------|
| `open_id` | 飞书用户的唯一标识符，格式为`ou_`开头 |
| `app_id` | 飞书应用的唯一标识符，格式为`cli_`开头 |
| `app_secret` | 飞书应用的密钥，用于API鉴权 |
| `im.message.receive_v1` | 飞书消息接收事件类型 |
| WebSocket | 一种在单个TCP连接上进行全双工通信的协议 |
| Webhook | 一种HTTP回调机制，服务器主动推送数据到客户端 |

### 12.2 参考文档

- [飞书开放平台文档](https://open.feishu.cn/document/home/index)
- [lark-oapi Python SDK](https://github.com/larksuite/oapi-sdk-python)

---

**文档结束**
