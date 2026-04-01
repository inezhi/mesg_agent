# 飞书（Feishu/Lark）集成实施计划

**版本**: v2.0  
**日期**: 2026-04-01  
**状态**: 规划中  

---

## 1. 实施原则

1. **MVP优先**：每个阶段都有可验证的产出
2. **小步快跑**：每个阶段代码量可控，便于Review
3. **统一格式**：Webhook和WebSocket使用相同的消息格式
4. **异常中断**：调用失败直接抛出异常，方便Debug
5. **详细日志**：所有关键节点都记录日志

---

## 2. 阶段规划

### MVP-0：适配飞书格式，Postman→Webhook→Console

#### 目标
修改现有代码，使Webhook能够接收完整的飞书事件格式，解析后输出到控制台。

#### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `core/feishu_handler.py` | 新增 | 飞书消息解析与处理入口 |
| `core/webhook_server.py` | 修改 | 接收飞书格式JSON，调用handler |
| `core/message.py` | 修改 | 使用logger输出到控制台 |

#### 核心逻辑
```
Postman ──POST /webhook──→ webhook_server.py
                                ↓
                        feishu_handler.parse_event() (解析飞书格式)
                                ↓
                        feishu_handler.handle_message() (提取open_id, text)
                                ↓
                        debounce → llm.chat()
                                ↓
                        message.send_text() → logger.info()
```

#### Postman测试请求
```json
POST http://localhost:8080/webhook
Content-Type: application/json

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
          "open_id": "ou_xxxxxxxxxxxxxxxx"
        },
        "sender_type": "user"
      }
    }
  }
}
```

#### 验证标准
- [ ] Postman发送后返回HTTP 200
- [ ] 控制台能看到解析后的open_id和text
- [ ] 能看到LLM生成的回复内容
- [ ] 异常时抛出明确错误信息

#### 配置需求
```yaml
message:
  platform: "feishu"
  feishu:
    my_open_id: "ou_xxxxxxxxxxxxxxxx"  # 用于验证消息来源
```

---

### MVP-1：Postman→Webhook→真实发送到飞书

#### 目标
在MVP-0基础上，实现真实发送消息到飞书。

#### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `core/feishu_messenger.py` | 新增 | 飞书Bot API发送模块 |
| `core/message.py` | 修改 | 调用feishu_messenger发送 |
| `config.yaml` | 修改 | 添加app_id和app_secret |

#### 核心逻辑
```
Postman ──POST /webhook──→ webhook_server.py
                                ↓
                        feishu_handler.parse_event()
                                ↓
                        feishu_handler.handle_message()
                                ↓
                        debounce → llm.chat()
                                ↓
                        message.send_text()
                                ↓
                        feishu_messenger.send_text() (真实发送)
                                ↓
                        飞书服务器 → 你的手机收到消息
```

#### 验证标准
- [ ] Postman发送测试消息
- [ ] 手机飞书收到AI回复
- [ ] 控制台能看到发送成功日志
- [ ] 发送失败时抛出异常

#### 配置需求
```yaml
message:
  platform: "feishu"
  feishu:
    app_id: "cli_xxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    my_open_id: "ou_xxxxxxxxxxxxxxxx"
```

#### 依赖安装
```bash
pip install lark-oapi
```

---

### MVP-2：飞书→WebSocket→Console

#### 目标
实现WebSocket长连接，接收真实飞书消息，输出到控制台。

#### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `core/feishu_ws_client.py` | 新增 | WebSocket客户端 |
| `main.py` | 修改 | 启动时初始化WebSocket连接 |
| `config.yaml` | 修改 | 确认配置完整 |

#### 核心逻辑
```
你(飞书) ──发送消息──→ 飞书服务器
                            ↓
                    WebSocket推送
                            ↓
                    feishu_ws_client (长连接)
                            ↓
                    feishu_handler.parse_event() (复用MVP-0)
                            ↓
                    feishu_handler.handle_message() (复用MVP-0)
                            ↓
                    debounce → llm.chat()
                            ↓
                    message.send_text() → logger.info() (仅控制台)
```

#### 飞书应用配置
1. 访问 [飞书开放平台](https://open.feishu.cn/app)
2. 创建企业自建应用
3. 开启机器人能力
4. 权限管理开通：
   - `im:message`
   - `im:message.p2p_msg:readonly`
   - `im:message.group_at_msg:readonly`
5. 事件订阅选择"使用长连接接收事件"
6. 添加事件：`im.message.receive_v1`
7. 发布应用

#### 验证标准
- [ ] 启动服务后WebSocket连接成功
- [ ] 在飞书向机器人发送消息
- [ ] 控制台能看到接收到的消息
- [ ] 能看到LLM生成的回复（仅控制台，不发送）

---

### MVP-3：飞书→WebSocket→真实回复到飞书

#### 目标
在MVP-2基础上，实现真实回复到飞书。

#### 涉及文件
| 文件 | 操作 | 说明 |
|------|------|------|
| `core/message.py` | 修改 | 启用真实发送（复用MVP-1的feishu_messenger） |
| `config.yaml` | 可选修改 | 如有需要调整配置 |

#### 核心逻辑
```
你(飞书) ──发送消息──→ 飞书服务器
                            ↓
                    WebSocket推送
                            ↓
                    feishu_ws_client
                            ↓
                    feishu_handler.parse_event()
                            ↓
                    feishu_handler.handle_message()
                            ↓
                    debounce → llm.chat()
                            ↓
                    message.send_text()
                            ↓
                    feishu_messenger.send_text() (真实发送)
                            ↓
                    飞书服务器 → 你收到AI回复
```

#### 验证标准
- [ ] 在飞书向机器人发送消息
- [ ] 飞书收到AI回复
- [ ] 控制台能看到完整流程日志
- [ ] 异常时抛出明确错误

---

## 3. 文件变更总览

| 阶段 | 新增文件 | 修改文件 |
|------|---------|---------|
| MVP-0 | `core/feishu_handler.py` | `core/webhook_server.py`<br>`core/message.py` |
| MVP-1 | `core/feishu_messenger.py` | `core/message.py`<br>`config.yaml` |
| MVP-2 | `core/feishu_ws_client.py` | `main.py`<br>`config.yaml` |
| MVP-3 | - | `core/message.py` |

---

## 4. 配置演进

### MVP-0 配置
```yaml
message:
  platform: "feishu"
  feishu:
    my_open_id: "ou_xxxxxxxxxxxxxxxx"
```

### MVP-1 配置
```yaml
message:
  platform: "feishu"
  feishu:
    app_id: "cli_xxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    my_open_id: "ou_xxxxxxxxxxxxxxxx"
```

### MVP-2/3 配置
与MVP-1相同，无需新增配置。

---

## 5. 关键模块职责

### feishu_handler.py
```python
def parse_event(event_json: dict) -> tuple[str, str, str]:
    """
    解析飞书事件JSON
    
    Returns:
        (open_id, text, chat_type)
    """

def handle_message(open_id: str, text: str, chat_type: str = "p2p"):
    """
    处理飞书消息的统一入口
    调用debounce → llm → message.send_text
    """
```

### feishu_messenger.py
```python
def init(config: dict):
    """初始化飞书客户端"""

def send_text(open_id: str, content: str) -> bool:
    """
    发送文本消息到飞书用户
    失败时抛出异常
    """
```

### feishu_ws_client.py
```python
def init(config: dict, message_handler: callable):
    """
    初始化WebSocket连接
    
    Args:
        config: 飞书配置
        message_handler: 消息处理回调函数
    """

def start():
    """在后台线程启动WebSocket连接"""

def stop():
    """优雅关闭WebSocket连接"""
```

---

## 6. 测试策略

### 单元测试
每个模块提供独立的单元测试：
- `tests/test_feishu_handler.py` - 解析逻辑测试
- `tests/test_feishu_messenger.py` - 发送逻辑测试（Mock）
- `tests/test_feishu_ws_client.py` - 连接逻辑测试

### 集成测试
- MVP-0/1：使用Postman发送请求验证
- MVP-2/3：使用真实飞书应用验证

### 日志检查
所有阶段都需要验证日志输出：
```
[时间] [模块名] 关键信息
[时间] [模块名] 关键信息
...
```

---

## 7. 风险与应对

| 风险 | 应对 |
|------|------|
| WebSocket连接不稳定 | SDK自动重连，日志记录 |
| 飞书API限流 | 异常抛出，人工处理 |
| 消息格式解析失败 | 详细日志，快速定位 |
| 配置错误 | 启动时校验，明确报错 |

---

## 8. 后续扩展（可选）

- 支持群聊@消息
- 支持图片/文件消息
- 支持消息卡片
- 支持多平台（钉钉、企业微信）

---

**文档结束**
