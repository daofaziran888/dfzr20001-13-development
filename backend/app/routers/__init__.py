"""业务路由汇总：所有模块共用一套资源路由，流水线路由独立注册。

注册顺序注意：翻仓验收等固定前缀路由必须先于通用资源路由（/api/{module}/{entry_id}）
注册，否则 /api/turning/candidates 这类两段路径会被通用路由按 entry_id 抢占解析。
"""
from __future__ import annotations

from app.routers import resource, pipeline_routes, turning

ROUTERS = [turning, resource, pipeline_routes]
