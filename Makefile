# 常用开发命令。CI 与本地用同一套，避免「本地过了线上挂」。

.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help install test lint typecheck typecheck-web check frontend run clean

help: ## 显示本帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## 安装 Python 与前端依赖
	$(UV) sync --extra dev
	cd frontend && pnpm install

test: ## 跑测试
	$(UV) run pytest

lint: ## 静态检查（ruff）
	$(UV) run ruff check src tests scripts

typecheck: ## 类型检查（mypy）
	$(UV) run mypy

typecheck-web: ## 前端类型检查（tsc）
	cd frontend && pnpm typecheck

check: lint typecheck typecheck-web test ## 提交前跑这个

frontend: ## 构建前端
	cd frontend && pnpm build

run: frontend ## 构建前端并启动 Web 管理台
	$(UV) run job web

clean: ## 清理缓存与构建产物
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find src tests scripts -name __pycache__ -type d -exec rm -rf {} +
	rm -rf frontend/dist
