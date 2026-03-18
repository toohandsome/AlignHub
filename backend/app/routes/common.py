from fastapi import Request

from app.feishu import FeishuBridgeService
from app.runtime import RunManager


def get_run_manager(request: Request) -> RunManager:
    return request.app.state.run_manager


def get_feishu_bridge(request: Request) -> FeishuBridgeService:
    return request.app.state.feishu_bridge
