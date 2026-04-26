# Google AI to OpenAI Proxy - Docker 部署指南

本指南详细介绍如何使用 Docker 容器化部署 Google AI 到 OpenAI 协议的代理服务。

## 目录

- [部署要求](#部署要求)
- [快速开始](#快速开始)
- [环境变量配置](#环境变量配置)
- [部署方式](#部署方式)
- [验证部署](#验证部署)
- [生产环境部署](#生产环境部署)
- [监控与维护](#监控与维护)
- [故障排查](#故障排查)
- [高级配置](#高级配置)
- [安全建议](#安全建议)

## 部署要求

- Docker Engine 20.10+
- Docker Compose 2.0+ (可选，推荐)
- Google AI API Key (必需)

## 快速开始

### 1. 获取代码

```bash
git clone <your-repo-url>
cd Toopenapi
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入 GOOGLE_API_KEY
nano .env
```

在 `.env` 文件中填入你的 Google AI API Key：

```
GOOGLE_API_KEY=AIzaSyB4eT...
```

### 3. 启动服务

#### 方式一：使用 Docker Compose (推荐)

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

#### 方式二：使用 Docker Run

```bash
# 构建镜像
docker build -t google-ai-openai-proxy .

# 运行容器
docker run -d \
  --name google-ai-openai-proxy \
  -p 8787:8787 \
  -e GOOGLE_API_KEY=your_api_key_here \
  --restart unless-stopped \
  google-ai-openai-proxy
```

## 环境变量配置

| 变量 | 默认值 | 说明 | 是否必需 |
|------|--------|------|----------|
| `GOOGLE_API_KEY` | - | Google AI API Key | **是** |
| `PORT` | `8787` | 服务端口 | 否 |
| `DEFAULT_MODEL` | `gemma-4-31b-it` | 默认模型 | 否 |
| `CACHE_DURATION` | `300` | 模型缓存时间(秒) | 否 |
| `REQUEST_TIMEOUT` | `120` | 请求超时(秒) | 否 |
| `LOG_LEVEL` | `INFO` | 日志级别 | 否 |
| `CORS_ORIGINS` | `*` | CORS 允许的来源 | 否 |
| `MAX_RETRIES` | `3` | 最大重试次数 | 否 |
| `SKIP_SSL_VERIFY` | `true` | 跳过 SSL 验证 | 否 |

### 环境变量示例

```
# 必需配置
GOOGLE_API_KEY=AIzaSyB4eT...

# 基础配置
PORT=8787
DEFAULT_MODEL=gemma-4-31b-it
LOG_LEVEL=INFO

# 高级配置
CACHE_DURATION=300
REQUEST_TIMEOUT=120
CORS_ORIGINS=*
MAX_RETRIES=3
SKIP_SSL_VERIFY=true
```

## 验证部署

### 1. 检查容器状态

```bash
docker-compose ps
```

或

```bash
docker ps | grep google-ai-openai-proxy
```

### 2. 健康检查

```bash
curl http://localhost:8787/health
```

预期响应：
```json
{"status": "ok", "timestamp": "2024-01-01T00:00:00"}
```

### 3. 获取模型列表

```bash
curl http://localhost:8787/v1/models
```

### 4. 测试聊天接口

```bash
curl http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-31b-it",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

## 生产环境部署

### 1. 使用专属网络

```yaml
# docker-compose.yml 中已配置
networks:
  google-ai-openai-proxy-net:
    driver: bridge
```

### 2. 配置反向代理

#### Nginx 配置

```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

#### 启用 HTTPS

```bash
# 使用 Let's Encrypt
certbot --nginx -d your-domain.com
```

### 3. 资源限制

在 `docker-compose.yml` 中已配置资源限制：

```yaml
deploy:
  resources:
    limits:
      memory: 512M
    reservations:
      memory: 128M
```

可根据实际需求调整。

### 4. 日志管理

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

### 5. 监控

```bash
# 查看容器资源使用
docker stats google-ai-openai-proxy

# 查看实时日志
docker-compose logs -f --tail=100
```

## 监控与维护

### 查看日志

```bash
# 实时日志
docker-compose logs -f

# 查看最后 100 行
docker-compose logs --tail=100

# 查看特定时间段的日志
docker-compose logs --since="2024-01-01T00:00:00" --until="2024-01-01T12:00:00"
```

### 更新服务

```bash
# 拉取最新代码
git pull

# 重新构建镜像并重启服务
docker-compose up -d --build

# 清理旧镜像
docker image prune -f
```

### 备份配置

```bash
# 备份环境变量
cp .env .env.backup.$(date +%Y%m%d)

# 备份 docker-compose.yml
cp docker-compose.yml docker-compose.yml.backup.$(date +%Y%m%d)
```

## 故障排查

### 容器无法启动

```bash
# 查看容器状态
docker-compose ps

# 查看日志
docker-compose logs

# 进入容器排查
docker exec -it google-ai-openai-proxy /bin/bash

# 在容器内测试
curl http://localhost:8787/health
```

### API 请求失败

```bash
# 检查环境变量
docker-compose config

# 验证 API Key
docker-compose logs | grep GOOGLE_API_KEY

# 测试 Google AI API 直连
curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_API_KEY"
```

### 端口冲突

```bash
# 查看端口占用
lsof -i :8787

# 或使用自定义端口
PORT=8888 docker-compose up -d
```

### 内存不足

```bash
# 查看内存使用
docker stats

# 调整内存限制
# 编辑 docker-compose.yml 中的 resources.limits.memory
```

### 网络问题

```bash
# 重启容器
docker-compose restart

# 重建网络
docker-compose down
docker network prune -f
docker-compose up -d
```

## 高级配置

### 1. 自定义端口

```bash
# 方式一：修改 .env 文件
PORT=8888

# 方式二：运行时指定
PORT=8888 docker-compose up -d

# 方式三：修改 docker-compose.yml
ports:
  - "8888:8787"
```

### 2. 多实例部署

```yaml
# docker-compose.override.yml
version: '3.8'

services:
  google-ai-openai-proxy-1:
    extends:
      service: google-ai-openai-proxy
    container_name: google-ai-openai-proxy-1
    ports:
      - "8787:8787"

  google-ai-openai-proxy-2:
    extends:
      service: google-ai-openai-proxy
    container_name: google-ai-openai-proxy-2
    ports:
      - "8788:8787"
```

启动：
```bash
docker-compose -f docker-compose.yml -f docker-compose.override.yml up -d
```

### 3. 集成到现有网络

```yaml
# docker-compose.yml
networks:
  default:
    external:
      name: your-existing-network
```

### 4. 使用自定义镜像仓库

```bash
# 构建并推送
docker build -t your-registry.com/google-ai-openai-proxy:latest .
docker push your-registry.com/google-ai-openai-proxy:latest

# 修改 docker-compose.yml
image: your-registry.com/google-ai-openai-proxy:latest
```

### 5. 配置 Swap

```bash
# 启用 swap
docker run -d \
  --memory="512m" \
  --memory-swap="1g" \
  ...
```

## 安全建议

### 1. 保护 API Key

```bash
# 设置文件权限
chmod 600 .env

# 不要在日志中暴露
docker run -d \
  -e GOOGLE_API_KEY \
  ...
```

### 2. 使用只读文件系统

```yaml
services:
  google-ai-openai-proxy:
    read_only: true
    tmpfs:
      - /tmp
```

### 3. 限制容器权限

```yaml
services:
  google-ai-openai-proxy:
    security_opt:
      - no-new-privileges:true
```

### 4. 定期更新

```bash
# 定期检查更新
docker-compose pull
docker-compose up -d --no-deps --build google-ai-openai-proxy
```

### 5. 网络安全

```yaml
# 使用内部网络
networks:
  proxy-network:
    internal: true
```

## FAQ

### Q: 如何查看支持的模型列表？
A: 使用 `GET /v1/models` 接口或查看日志。

### Q: 如何修改日志级别？
A: 在 `.env` 文件中设置 `LOG_LEVEL=DEBUG`。

### Q: 容器占用太多磁盘空间？
A: 清理旧镜像：`docker image prune -a`

### Q: 如何持久化日志？
A: 挂载卷：`./logs:/app/logs`

### Q: 支持哪些 Google AI 模型？
A: 所有 Gemini 和 Gemma 系列模型。

## 版本历史

- v1.0.0: 初始 Docker 版本
  - 支持 Docker Compose 部署
  - 支持 Docker Run 部署
  - 健康检查
  - 日志管理

## 技术支持

如有问题，请：
1. 查看 [故障排查](#故障排查) 章节
2. 检查容器日志
3. 提交 Issue

## 许可证

MIT License