"""仓储养护领域服务：监控入库环境参数，跟踪陈化周期与翻仓计划，关联包装批次。"""
from __future__ import annotations
from typing import Any
from app.services.base import BaseModuleService
from app.store import store

class StorageService(BaseModuleService):
    MODULE = "storage"
    ENTITY = "养护记录"
    OPERATION_TERM = "记录养护"
    LIST_FIELDS = ["入库温度", "入库湿度", "陈化周期", "翻仓日期", "班次", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["入库温度", "入库湿度"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"记录养护": "已确认", "提交确认": "待确认", "撤回记录": "已撤回"}
    NEGATIVE_ACTIONS = []

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        temp = store.parse_weight(values.get("入库温度", "0"))
        if temp < -5:
            errors.append("入库温度不宜低于-5℃")
        elif temp > 35:
            errors.append("入库温度不宜高于35℃（需冷藏保管的茶类请使用冷库）")
        humidity = store.parse_weight(values.get("入库湿度", "0"))
        if humidity <= 0 or humidity > 100:
            errors.append("入库湿度应在1-100%之间")
        # 校验关联的包装批次
        packing_id = values.get("packing_id")
        if packing_id is not None:
            packing = store.find("packing", int(packing_id))
            if packing is None:
                errors.append(f"包装批 {packing_id} 不存在")
            elif packing.get("status") != "已确认":
                errors.append(f"包装批 {packing_id} 未确认")
        return errors

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        if action == "记录养护":
            batch_no = entry.get("批次号", "")
            if batch_no:
                packing_id = entry.get("packing_id")
                if packing_id is not None:
                    packing = store.find("packing", int(packing_id))
                    if packing:
                        entry["packing_name"] = packing.get("登记编号", str(packing_id))
        return True, None

    def is_overdue_turning(self, entry: dict[str, Any]) -> bool:
        """判断是否超过翻仓期限。"""
        from datetime import datetime
        turning_date = entry.get("翻仓日期", "")
        if not turning_date:
            return False
        try:
            dt = datetime.strptime(str(turning_date)[:10], "%Y-%m-%d")
            return dt < datetime.now()
        except ValueError:
            return False

    def get_storage_status(self, batch_no: str) -> dict[str, Any] | None:
        """获取指定批次的最新仓储养护状态。"""
        rows = store.rows(self.MODULE)
        batch_rows = [r for r in rows if r.get("批次号") == batch_no]
        return batch_rows[-1] if batch_rows else None

    def get_storage_by_packing(self, packing_id: int) -> list[dict[str, Any]]:
        """获取关联到指定包装批的仓储养护记录。"""
        rows = store.rows(self.MODULE)
        return [r for r in rows if r.get("packing_id") == packing_id]