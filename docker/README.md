# StockStream V3.0 — Docker 部署指南

## 文件结构

```
docker/
├── README.md              ← 本文件
├── entrypoint.sh           ← 容器启动初始化脚本
└── (可扩展 docker-compose fragments)
```

## 快速开始

### 1. 配置环境变量

```bash
cp config/.env.example .env
# 编辑 .env, 填入你的 API Key 等配置
```

### 2. 启动

```bash
# 核心应用 (SQLite + Redis 缓存)
docker compose up -d

# 全栈生产环境 (含 PostgreSQL + Prometheus + Grafana)
docker compose --profile full up -d

# Jetson Xavier NX
docker compose -f docker-compose.jetson.yml up -d
```

### 3. 验证

```bash
curl http://localhost:8080/health          # 健康检查
curl http://localhost:8080/monitor         # 监控仪表盘
curl http://localhost:8080/live            # 直播页面
curl http://localhost:8080/docs            # API 文档 (Swagger)
```

## Compose Profile 说明

| Profile | 包含服务 | 命令 |
|---------|---------|------|
| (默认) | stockstream + redis | `docker compose up -d` |
| full | stockstream + redis + postgres + prometheus + grafana | `docker compose --profile full up -d` |
| monitoring | prometheus + grafana | `docker compose --profile monitoring up -d` |
| postgres | postgres | `docker compose --profile postgres up -d` |

## 开发模式

```bash
# 源码挂载 + uvicorn --reload + debugpy 5678
make dev
# 或
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

## 常用命令

```bash
make             # 查看所有命令
make build       # 构建镜像
make up          # 启动
make logs        # 查看日志
make shell       # 进入容器
make health      # 健康检查
make clean       # 清理
```

## 镜像构建选项

```bash
# x86_64 生产镜像
docker build -t stockstream:3.0.0 .

# Jetson ARM64 镜像
docker build -f Dockerfile.jetson -t stockstream:jetson-3.0.0 .

# 开发镜像 (含 debugpy)
docker build --target dev -t stockstream:dev .
```

## 端口映射

| 容器端口 | 宿主机 | 用途 |
|---------|--------|------|
| 8080 | 8080 | API + 直播页 + 监控仪表盘 |
| 9090 | 9090 | Prometheus metrics (可关闭) |
| 3000 | 3000 | Grafana (monitoring profile) |
| 5432 | 5432 | PostgreSQL (full profile) |
| 6379 | - | Redis (仅内部网络) |
| 5678 | 5678 | debugpy (dev profile) |

## 数据持久化

| Docker Volume | 宿主机路径 | 内容 |
|--------------|-----------|------|
| stockstream-data | data/ | 数据库 + 运行时数据 |
| stockstream-logs | logs/ | 日志文件 |
| stockstream-cache | cache/ | 缓存文件 |
| stockstream-backups | backups/ | 数据库备份 |

## 健康检查

所有 Compose 均已配置 Docker HEALTHCHECK:

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -fsS http://localhost:8080/health || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 45s  # 普通, 90s for Jetson
```

结果查看: `docker compose ps` 中 STATUS 列显示 `(healthy)` 或 `(unhealthy)`。
