from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.core import RealtimeBroker, settings
from app.db import init_db
from app.feishu import FeishuBridgeService
from app.runtime import EventService, RunManager, sync_builtin_tools


def configure_logging() -> None:
    """初始化应用日志。

    - 文件日志用于保留后端运行记录，方便排查问题
    - 控制台日志用于开发阶段实时观察启动与请求情况
    - 通过 `_configured` 标记避免重复初始化造成重复输出
    """
    root_logger = logging.getLogger()
    if getattr(configure_logging, "_configured", False):
        return

    log_dir = Path(__file__).resolve().parents[1]
    log_file = log_dir / "backend-app.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    configure_logging._configured = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """在 FastAPI 生命周期内完成基础设施初始化。

    当前启动顺序为：
    1. 初始化数据库与索引
    2. 同步内置工具定义到数据库
    3. 创建实时事件总线与运行控制器
    4. 绑定飞书桥接服务，用于接收运行事件并向外转发
    """
    await init_db()
    await sync_builtin_tools()
    broker = RealtimeBroker()
    event_service = EventService(broker)
    feishu_bridge = FeishuBridgeService()
    run_manager = RunManager(event_service)
    feishu_bridge.bind_run_manager(run_manager)
    event_service.register_listener(feishu_bridge.handle_run_event)
    app.state.broker = broker
    app.state.event_service = event_service
    app.state.run_manager = run_manager
    app.state.feishu_bridge = feishu_bridge
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
configure_logging()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")


@app.get("/healthz")
async def healthz():
    """用于探活和部署检查的健康检查接口。"""
    return {"status": "ok"}
