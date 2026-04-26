# Google AI to OpenAI Protocol Proxy

将 Google AI API (Gemma/Gemini) 转换为 OpenAI 协议格式的代理服务，支持直接与 OpenAI 客户端/SDK 无缝对接。

## 功能特性

- **OpenAI 协议兼容** - 完全兼容 OpenAI Chat Completions API 格式
- **模型列表** - 自动从 Google AI API 获取可用模型
- **上下文获取** - 直接从原生接口获取模型的 context_window
- **流式响应** - 支持 SSE 流式输出
- **跨域支持** - 默认允许所有来源 CORS
- **健康检查** - 提供 `/health` 接口用于监控
- **自动重试** - 请求失败时自动重试
- **无需依赖** - 使用 Python 内置库，无额外依赖

## 快速开始

### 方式一：直接运行
```bash
python3 server.py
```
 
### 方式二：使用部署脚本
```bash
# 启动服务
./start.sh

# 停止服务
./stop.sh

# 重启服务
./restart.sh

# 查看状态
./status.sh
```

### 方式三：Docker 容器化部署（推荐）

#### 快速启动
```bash
# 1. 配置环境变量
cp .env.example .env
nano .env  # 设置 GOOGLE_API_KEY

# 2. 一键部署（推荐）
./docker-start.sh

# 或使用 Docker Compose
docker-compose up -d
```

#### Docker 管理命令
```bash
# 查看容器状态
docker-compose ps

# 查看实时日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose down
```

#### 使用 Makefile
```bash
# 查看所有命令
make help

# 构建并运行
make build && make run

# 查看状态
make status

# 运行测试
make test

# 完全清理
make clean
```

#### 开发模式
```bash
# 使用覆盖配置，支持热重载
docker-compose -f docker-compose.yml -f docker-compose.override.yml up
```

详细的 Docker 部署指南请参考 [DOCKER_DEPLOY.md](DOCKER_DEPLOY.md)。

## API 接口
### 方式三：Docker 容器化部署（推荐）
 
#### 使用 Docker Compose（一键部署）
 
```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，设置 GOOGLE_API_KEY
 
# 2. 启动服务
docker-compose up -d
 
# 3. 查看日志
docker-compose logs -f
 
# 4. 停止服务
docker-compose down
```
 
#### 使用一键部署脚本
 
```bash
# 自动检查环境、配置和启动服务
./docker-start.sh
```
 
#### Docker 常用命令
 
```bash
# 查看容器状态
docker-compose ps
 
# 重启服务
docker-compose restart
 
# 重建并启动
docker-compose up -d --build
 
# 查看最后 100 条日志
docker-compose logs --tail=100
```

## API 接口

### 聊天补全 `POST /v1/chat/completions`

```bash
curl http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-31b-it",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": false
  }'
```

### 模型列表 `GET /v1/models`

```bash
curl http://localhost:8787/v1/models
```

### 健康检查 `GET /health`

```bash
curl http://localhost:8787/health
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `8787` | 服务端口 |
| `GOOGLE_API_KEY` | **必须设置** | Google AI API Key |
| `DEFAULT_MODEL` | `gemma-4-31b-it` | 默认模型 |
| `CACHE_DURATION` | `300` | 模型缓存时间（秒）|
| `REQUEST_TIMEOUT` | `120` | 请求超时（秒）|
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_FILE` | `/tmp/openai_proxy.log` | 日志文件路径 |
| `CORS_ORIGINS` | `*` | CORS 允许的来源 |
| `MAX_RETRIES` | `3` | 最大重试次数 |
| `SKIP_SSL_VERIFY` | `true` | 跳过 SSL 验证 |

### 设置 API Key

API Key 支持三种配置方式（按优先级排序）：

**方式一：请求体传递（推荐）**
```bash
curl -X POST http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-31b-it",
    "api_key": "你的Google AI API密钥",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

**方式二：Header 传递**
```bash
curl -X POST http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 你的Google AI API密钥" \
  -d '{
    "model": "gemma-4-31b-it",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

**方式三：环境变量**
```bash
export GOOGLE_API_KEY=你的Google AI API密钥
python3 server.py
```

> ⚠️ **重要**: API Key 支持多种配置方式（见下文），请勿将密钥硬编码在代码中！

## 使用示例

### Python

```python
from openai import OpenAI

client = OpenAI(
    api_key="any-key",
    base_url="http://localhost:8787/v1"
)

response = client.chat.completions.create(
    model="gemma-4-31b-it",
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)
print(response.choices[0].message.content)
```

### JavaScript/Node.js

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  apiKey: 'any-key',
  baseURL: 'http://localhost:8787/v1'
});

const response = await client.chat.completions.create({
  model: 'gemma-4-31b-it',
  messages: [
    { role: 'user', content: 'Hello!' }
  ]
});

console.log(response.choices[0].message.content);
```

### LM Studio / LocalAI

将 base URL 设置为 `http://localhost:8787/v1` 即可使用。

## 项目结构

```
Toopenapi/
├── server.py      # 主服务文件
├── start.sh      # 启动脚本
├── stop.sh       # 停止脚本
├── restart.sh    # 重启脚本
├── status.sh     # 状态检查脚本
├── requirements.txt  # 依赖（可选）
└── logs/         # 日志目录
```

## License

MIT
