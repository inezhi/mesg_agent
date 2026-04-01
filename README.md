# mesg-agent-repo

A lightweight message-platform agent built with Python, supporting Feishu (Lark) integration.

Language: English | [简体中文](README.zh-CN.md)

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#requirements)
[![Status](https://img.shields.io/badge/status-active-success)](#current-status)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](#license)

## Overview

mesg-agent-repo is a webhook-driven AI agent service. It receives incoming messages from messaging platforms (Feishu/Lark, Webhook), applies debounce/merge logic, sends requests to an OpenAI-compatible LLM API, and replies back through a message adapter.

Core capabilities:

- **Feishu/Lark Integration**: Full support for Feishu messaging platform via WebSocket and Webhook
- Threaded HTTP webhook server
- Debounced multi-message merge per user
- Session persistence on local JSON files
- Built-in scheduler for one-time and cron tasks
- Optional long-term memory bootstrap with LanceDB

## Architecture

### General Flow

```text
Webhook POST -> webhook_server -> debounce -> llm.chat
                                                    |
                                                    +-> session store (sys_sessions/*.json)
                                                    +-> scheduler context bridge
                                                    +-> memory module (init ready, retrieval hook reserved)
```

### Feishu Integration Flow

```text
Feishu Platform
       |
       +-- WebSocket --> feishu_ws_client --> feishu_handler --> debounce --> llm.chat
       |                                                              |
       +-- Webhook  --> webhook_server --> feishu_handler ------------>|
                                                                            |
       feishu_messenger <--------------------------------------------------+
       |
       +--> Send reply back to Feishu
```

**Feishu Components:**
- `feishu_ws_client.py` - WebSocket client for real-time message receiving
- `feishu_handler.py` - Event parsing and message handling
- `feishu_messenger.py` - Message sending with reply thread support

Initialization order in startup:

1. message
2. llm
3. scheduler
4. tools
5. memory
6. debounce

## Repository Layout

```text
.
├── main.py
├── config.yaml
├── core/
│   ├── webhook_server.py    # HTTP webhook handler
│   ├── debounce.py          # Message debounce/merge logic
│   ├── llm.py               # LLM chat interface
│   ├── scheduler.py         # Background task scheduler
│   ├── message.py           # Message platform adapter (Feishu supported)
│   ├── memory.py            # Long-term memory with LanceDB
│   ├── tools.py             # Tool registry and execution
│   ├── utils.py             # Utility functions
│   ├── mcp_client.py        # MCP client (reserved)
│   ├── feishu_ws_client.py  # Feishu WebSocket client
│   ├── feishu_handler.py    # Feishu event handler
│   └── feishu_messenger.py  # Feishu message sender
├── doc/
│   └── feishu/              # Feishu integration documentation
├── sys_sessions/            # Session storage
├── sys_memory_db/           # Memory database
└── workspace/
    └── files/               # Workspace files
```

## Requirements

- Python 3.10+
- macOS / Linux / Windows

Install dependencies:

```bash
pip install -r requirements.txt
```

## Quick Start

1. Copy the example config file and fill in your actual values:

```bash
cp config-example.yaml config.yaml
# Edit config.yaml and replace all YOUR_XXX placeholders with actual values
```

2. Optionally point AGENT_CONFIG to your config path.
3. Start the service.

```bash
export AGENT_CONFIG=./config.yaml
python main.py
```

Health check:

```bash
curl http://127.0.0.1:8080/
```

Expected response:

```json
{"status":"ok"}
```

## Configuration

By default, the app reads config.yaml in the repository root.
You can override it using AGENT_CONFIG.

Example configuration:

```yaml
# AI Agent configuration file
# Used to configure messaging platform connection, model parameters, memory system, etc.

# Admin ID list, debounce determines whether to reply to these users
owner_ids:
  - "user_0"
  - "user_1"

# Workspace path
workspace: "./workspace"

# Listening port
port: 8080

# Message debounce interval (seconds)
debounce_seconds: 3.0

# Messaging platform configuration
message:
  platform: "feishu"
  feishu:
    app_id: "cli_xxxxxxxxxxxxxxxx"
    app_secret: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    my_open_id: "ou_xxxxxxxxxxxxxxxx"

# Model configuration
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

# Memory system configuration
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

Important fields:

- owner_ids: only these senders can trigger AI replies
- debounce_seconds: message merge window per sender
- models.default: active provider key in models.providers
- memory.enabled: toggle memory subsystem initialization
- message.platform: message platform type, currently supports "feishu"
- message.feishu.app_id: Feishu app ID (get from https://open.feishu.cn/app)
- message.feishu.app_secret: Feishu app secret
- message.feishu.my_open_id: Bot's own open_id (get from https://open.feishu.cn/document/faq/trouble-shooting/how-to-obtain-openid)

## Webhook Contract

Endpoint:

- POST /

Supported event type:

- `im.message.receive_v1` - Receive message event

Sample payload (Feishu format):

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
      "content": "{\"text\":\"hello\"}",
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

Field description:

- `event_type`: Event type, currently supports `im.message.receive_v1`
- `chat_type`: Chat type, `p2p` (private) or `group` (group chat)
- `message_type`: Message type, currently supports `text`
- `content`: Message content in JSON string format
- `open_id`: Unique identifier of the sender
```

## Data Persistence

- Sessions: sys_sessions/dm_<sender_id>.json
- Scheduler session: sys_sessions/scheduler.json (derived from session key)
- Memory DB: sys_memory_db/
- Workspace files: workspace/files/

Session window limit in llm.py:

- MAX_SESSION_MESSAGES = 40

## Scheduler

Background loop checks jobs every 10 seconds.

Supported job types:

- once
- cron
- once_cron (branch exists, behavior still evolving)

Trigger call:

- chat_fn(job["message"], "scheduler")

## Current Status

Implemented:

- **Feishu (Lark) Integration**: Full support via WebSocket and Webhook
  - Real-time message receiving via WebSocket
  - Message sending with reply thread support
  - Event handling and parsing
  - Async message processing with deduplication
- Threaded webhook handling
- Debounce and message merge
- OpenAI-compatible LLM request flow
- Session save/load and truncation
- Scheduler boot/check/trigger
- Memory module initialization with LanceDB

Not fully implemented yet:

- Production-ready tool implementations in tools.py
- Tool execution loop is reserved in llm.py (code path currently commented)
- Image input branch currently raises ValueError("Image not supported yet")
- mcp_client.py is currently empty

## Security Notes

- Do not commit real API keys into repository files.
- Prefer environment variables or secret managers for credentials.
- Rotate any leaked key immediately.

## Development Roadmap

1. ~~Connect real message platform API in message adapter~~ ✅ Feishu integration completed
2. Complete tool registry + execution loop
3. Enable memory retrieval injection in chat path
4. Add requirements.txt and basic tests
5. Support Feishu image messages
6. Support Feishu group @ mentions

## Contributing

Issues and pull requests are welcome.

Suggested local workflow:

1. Create a feature branch
2. Make focused changes
3. Verify startup and webhook health endpoint
4. Open a pull request with context and test steps

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
