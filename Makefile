# StockStream V3.0 — Makefile (Docker 快捷命令)

.PHONY: help build up down logs shell clean test ps health prod dev jetson

help: ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Build ──────────────────────────────────────────────────────────
build: ## 构建生产镜像
	docker compose build
	@echo "[OK] Image built: stockstream:latest"

build-jetson: ## 构建 Jetson 镜像
	docker compose -f docker-compose.jetson.yml build
	@echo "[OK] Image built: stockstream:jetson-latest"

build-dev: ## 构建开发镜像
	docker compose -f docker-compose.yml -f docker-compose.dev.yml build
	@echo "[OK] Image built: stockstream:dev"

# ── Run ────────────────────────────────────────────────────────────
up: ## 启动核心应用 (默认)
	docker compose up -d
	@echo "[OK] StockStream running on http://localhost:8080"

up-full: ## 启动全栈 (PostgreSQL + Prometheus + Grafana)
	docker compose --profile full up -d
	@echo "[OK] StockStream full stack: http://localhost:8080"
	@echo "  Grafana: http://localhost:3000 (admin/admin)"

down: ## 停止所有服务
	docker compose --profile full down

restart: down up ## 重启

logs: ## 查看应用日志 (实时)
	docker compose logs -f stockstream

logs-all: ## 查看所有服务日志
	docker compose logs -f

# ── Dev ────────────────────────────────────────────────────────────
dev: ## 启动开发模式 (热重载 + debug)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
	@echo "[OK] Dev mode: http://localhost:8080 (debug: 5678)"

dev-logs: ## 查看开发模式日志
	docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f

dev-down: ## 停止开发模式
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down

# ── Jetson ─────────────────────────────────────────────────────────
jetson: ## 启动 Jetson 模式
	docker compose -f docker-compose.jetson.yml up -d
	@echo "[OK] Jetson mode: http://localhost:8080"

jetson-down: ## 停止 Jetson 模式
	docker compose -f docker-compose.jetson.yml down

jetson-logs: ## 查看 Jetson 日志
	docker compose -f docker-compose.jetson.yml logs -f stockstream

# ── Ops ────────────────────────────────────────────────────────────
shell: ## 进入运行中的容器
	docker compose exec stockstream bash

health: ## 健康检查
	@curl -s http://localhost:8080/health | python -m json.tool || echo "Service not running"

ps: ## 显示容器状态
	docker compose ps

clean: down ## 清理所有资源 (警告: 删除数据卷!)
	@read -p "This will DELETE all volumes (data/logs/cache). Continue? [y/N] " yn; \
	case $$yn in [Yy]*) docker compose down -v;; esac

test: ## 运行容器内测试
	docker compose exec stockstream python -m pytest tests/ -v

# ── Monitoring ─────────────────────────────────────────────────────
metrics: ## 抓取 Prometheus 指标
	@curl -s http://localhost:8080/metrics | head -20

prometheus-up: ## 启动监控栈
	docker compose --profile monitoring up -d

prometheus-down: ## 停止监控栈
	docker compose --profile monitoring down
