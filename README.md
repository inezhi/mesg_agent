# mesg-agent-repo

A lightweight message-platform agent built with Python.

Language: English | [简体中文](README.zh-CN.md)

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#requirements)
[![Status](https://img.shields.io/badge/status-active-success)](#current-status)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](#license)

## Overview

mesg-agent-repo is a webhook-driven AI agent service. It receives incoming messages from a messaging platform, applies debounce/merge logic, sends requests to an OpenAI-compatible LLM API, and replies back through a message adapter.

Core capabilities:

- Threaded HTTP webhook server
- Debounced multi-message merge per user
- Session persistence on local JSON files
- Built-in scheduler for one-time and cron tasks
- Optional long-term memory bootstrap with LanceDB

## Architecture

```text
Webhook POST -> webhook_server -> debounce -> llm.chat
                                                    |
                                                    +-> session store (sys_sessions/*.json)
                                                    +-> scheduler context bridge
                                                    +-> memory module (init ready, retrieval hook reserved)
```

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

## Requirements

- Python 3.10+
- macOS / Linux / Windows

Install dependencies manually:

```bash
pip install loguru croniter lancedb numpy
```

## Quick Start

1. Configure your runtime config file (see Configuration section).
2. Optionally point AGENT_CONFIG to your config path.
3. Start the service.

```bash
export AGENT_CONFIG=./config-test.json
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

By default, the app reads config-test.json in the repository root.
You can override it using AGENT_CONFIG.

Example configuration:

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

Important fields:

- owner_ids: only these senders can trigger AI replies
- debounce_seconds: message merge window per sender
- models.default: active provider key in models.providers
- memory.enabled: toggle memory subsystem initialization

## Webhook Contract

Endpoint:

- POST /

Supported message branch in current code:

- cmd == 15000
- msgType in [0, 2] (text/reply-like text)

Sample payload:

```json
{
	"data": [
		{
			"cmd": 15000,
			"senderId": "user_1",
			"userId": "agent_1",
			"msgType": 0,
			"msgData": {
				"content": "hello"
			}
		}
	]
}
```

Heartbeat payload is accepted and ignored:

```json
{
	"testMsg": "heartbeat"
}
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

- Threaded webhook handling
- Debounce and message merge
- OpenAI-compatible LLM request flow
- Session save/load and truncation
- Scheduler boot/check/trigger
- Memory module initialization with LanceDB

Not fully implemented yet:

- Real outbound message API integration in message.py
- Production-ready tool implementations in tools.py
- Tool execution loop is reserved in llm.py (code path currently commented)
- Image input branch currently raises ValueError("暂不支持图片")
- mcp_client.py is currently empty

## Security Notes

- Do not commit real API keys into repository files.
- Prefer environment variables or secret managers for credentials.
- Rotate any leaked key immediately.

## Development Roadmap

1. Connect real message platform API in message adapter
2. Complete tool registry + execution loop
3. Enable memory retrieval injection in chat path
4. Add requirements.txt and basic tests

## Contributing

Issues and pull requests are welcome.

Suggested local workflow:

1. Create a feature branch
2. Make focused changes
3. Verify startup and webhook health endpoint
4. Open a pull request with context and test steps

## License

MIT (recommended). Add a LICENSE file if you want this to be explicit in repository metadata.
