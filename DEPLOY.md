# StockStream v2.0 部署手册

## 环境要求

### Jetson Xavier NX
- JetPack 5.0+
- Docker + nvidia-docker2
- 8GB LPDDR4x
- 推荐 SD卡/SSD 64GB+

### Linux x86_64
- Docker 20.10+
- Docker Compose 2.0+
- 推荐 4GB+ RAM

---

## 快速部署

### 1. 克隆仓库
```bash
git clone https://github.com/stockstream/stockStream.git
cd stockStream
```

### 2. 配置
```bash
cp config/.env.example config/.env
# 编辑 .env 填入 API 密钥等敏感信息
```

### 3. 一键启动
```bash
# 标准部署
docker compose up -d

# Jetson 部署
docker compose -f docker-compose.jetson.yml up -d
```

### 4. 验证
```bash
curl http://localhost:8000/health
```

---

## Systemd 部署 (开机启动)

```bash
# 复制项目到 /opt/stockstream
sudo cp -r . /opt/stockstream
sudo chown -R stockstream:stockstream /opt/stockstream

# 安装服务
cd /opt/stockstream
sudo bash services/install.sh

# 启动
sudo systemctl start ai-live

# 查看日志
sudo journalctl -u ai-live -f
```

---

## PostreSQL 部署

```bash
# docker-compose.override.yml
version: '3.8'
services:
  app:
    environment:
      - STOCKSTREAM_DATABASE__URL=postgresql+asyncpg://stockstream:password@postgres:5432/stockstream
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: stockstream
      POSTGRES_PASSWORD: password
      POSTGRES_DB: stockstream
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

---

## 配置热更新

修改 `config/base.yaml` 后发送 SIGHUP:
```bash
docker compose kill -s SIGHUP app
```

或在 Web API 中:
```bash
curl -X POST http://localhost:8000/api/v1/config/reload
```
