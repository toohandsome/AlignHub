from typing import Any

from fastapi import Request

from app.feishu import FeishuBridgeService


def get_run_manager(request: Request) -> Any:
    return request.app.state.run_manager


def get_feishu_bridge(request: Request) -> FeishuBridgeService:
    return request.app.state.feishu_bridge
