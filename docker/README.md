# StockStream V4.0 Enterprise — Docker 部署指南

## 一套代码，四个发布版本

| 版本 | 目录 | 平台 | 用途 |
|------|------|------|------|
| **dev-desktop** | `docker/desktop/` | x86_64 + RTX GPU | 开发调试 |
| **demo** | `docker/demo/` | x86_64 CPU | 客户演示 |
| **production-desktop** | `docker/desktop/` | x86_64 + RTX GPU | 生产部署 |
| **production-jetson** | `docker/jetson/` | ARM64 + Xavier NX | 边缘推理 |

## 文件结构

```
docker/
├── README.md
├── entrypoint.sh                  ← 通用容器入口脚本
├── desktop/
│   ├── Dockerfile                 ← RTX GPU, CUDA 12
│   ├── docker-compose.yml
│   └── entrypoint.sh
├── demo/
│   ├── Dockerfile                 ← 纯 CPU 模拟
│   ├── docker-compose.yml
│   └── entrypoint.sh
└── jetson/
    ├── Dockerfile                 ← Jetson ARM64, TensorRT 8
    ├── docker-compose.yml
    └── entrypoint.sh
```

## 快速开始

### 1. 配置环境变量

```bash
cp configs/.env.example .env
# 编辑 .env, 填入你的 API Key 等配置
```

### 2. 选择版本启动

```bash
# Demo 演示 (纯 CPU, 模拟数据, 零依赖)
docker compose -f docker/demo/docker-compose.yml up -d

# 桌面开发版 (RTX GPU, 热重载)
docker compose -f docker/desktop/docker-compose.yml up -d

# Jetson 生产版 (ARM64 Xavier NX)
docker compose -f docker/jetson/docker-compose.yml up -d
```

### 3. 验证

```bash
curl http://localhost:8080/health               # 健康检查
curl http://localhost:8080/monitor              # 监控仪表盘
curl http://localhost:8080/monitor/api/metrics  # JSON 指标
curl http://localhost:8080/docs                 # API 文档 (Swagger)
```

## 镜像构建选项

```bash
# 桌面生产镜像 (x86_64, CUDA 12)
docker build -f docker/desktop/Dockerfile -t stockstream-desktop:4.0.0 .

# Demo 演示镜像 (纯 CPU)
docker build -f docker/demo/Dockerfile -t stockstream-demo:4.0.0 .

# Jetson ARM64 镜像 (TensorRT 8)
docker build -f docker/jetson/Dockerfile -t stockstream-jetson:4.0.0 .
```

## 端口映射

| 容器端口 | 宿主机 | 用途 |
|---------|--------|------|
| 8080 | 8080 | API + 直播页 + 监控仪表盘 |
| 9090 | 9090 | Metrics (Prometheus compatible) |

## 数据持久化

| Docker Volume | 宿主机路径 | 内容 |
|--------------|-----------|------|
| stockstream-data | data/ | 数据库 + 运行时数据 |
| stockstream-logs | logs/ | 日志文件 |
| stockstream-cache | cache/ | 缓存文件 |
| stockstream-models | models/ | ONNX 模型 |

## 健康检查

所有 Compose 均已配置 Docker HEALTHCHECK:

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -fsS http://localhost:8080/health || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 45s   # desktop/demo
  start_period: 90s   # jetson (ARM64 慢启动)
```

## Jetson 特别说明

- 内存限制: 容器默认 6GB, Xavier NX 共 8GB
- TensorRT 引擎缓存路径: `/data/tensorrt_cache`
- 运行 `docker/jetson/entrypoint.sh` 前确保 `nvcr.io` 镜像可访问
- 支持硬件看门狗自动重启
