"""发运交接领域服务：确认发运信息，校验收货方与物流信息完整性，关联溯源码段。"""
from __future__ import annotations
from typing import Any
from app.services.base import BaseModuleService
from app.store import store

class ShipmentService(BaseModuleService):
    MODULE = "shipment"
    ENTITY = "发运单"
    OPERATION_TERM = "确认发运"
    LIST_FIELDS = ["收货方", "物流单号", "发运日期", "承运单位", "登记编号", "负责人", "生效版本", "备注说明"]
    REQUIRED_FIELDS = ["收货方", "物流单号", "发运日期", "承运单位"]
    STATUS_ORDER = ["草稿", "待确认", "已确认", "已撤回"]
    ACTION_RULES = {"确认发运": "已确认", "提交确认": "待确认", "撤回记录": "已撤回"}
    NEGATIVE_ACTIONS = []

    def validate_entry(self, values: dict[str, Any]) -> list[str]:
        errors = []
        tracking_no = str(values.get("物流单号", "")).strip()
        if tracking_no:
            existing = [r for r in store.rows(self.MODULE)
                        if r.get("物流单号") == tracking_no and r.get("status") == "已确认"]
            if existing:
                errors.append(f"物流单号 {tracking_no} 已有已确认发运记录")
        return errors

    def on_confirm(self, entry: dict[str, Any], action: str) -> tuple[bool, str | None]:
        """发运确认前必须经过门禁。"""
        if action == "确认发运":
            batch_no = entry.get("批次号", "")
            if batch_no:
                # 检测报告门禁
                all_testing = [r for r in store.rows("testing") if r.get("status") == "已确认"]
                if not all_testing:
                    return False, "缺少已签收的检测报告，不允许确认发运"

                # 认证资质门禁（有效期检查）
                from datetime import datetime
                all_cert = [r for r in store.rows("certification") if r.get("status") == "已确认"]
                valid_cert = False
                for c in all_cert:
                    try:
                        expiry = str(c.get("有效期至", ""))[:10]
                        if datetime.strptime(expiry, "%Y-%m-%d") >= datetime.now():
                            valid_cert = True
                            break
                    except ValueError:
                        continue
                if not valid_cert:
                    return False, "缺少有效期内的认证资质证书，不允许确认发运"

                # 溯源码段已激活
                trace_codes = [r for r in store.rows("trace_code") if r.get("status") == "已确认"]
                if not trace_codes:
                    return False, "缺少已激活的溯源码段，不允许确认发运"

                # 包装已确认
                lineage = store.get_batch_lineage_nodes(batch_no)
                for n in lineage:
                    if n["module"] == "packing":
                        pack_entry = store.find("packing", n["entry_id"])
                        if pack_entry and pack_entry.get("status") != "已确认":
                            return False, "该批次的包装规格尚未确认，请先确认包装后再发运"

                # 冻结检查
                for n in lineage:
                    if store.is_frozen(n["module"], n["entry_id"]):
                        reason = store.get_frozen_reason(n["module"], n["entry_id"])
                        return False, f"批次中存在冻结记录（{reason}），不允许发运"

            # 翻仓验收门禁：关联包装批仍有未完成待翻仓记录时禁止发运，
            # 上一轮的翻仓验收回执不能当成本轮的通过证明
            from app.services.turning import turning_service
            for pid in turning_service.resolve_shipment_packing_ids(entry):
                pending = turning_service.pending_for_packing(pid)
                if pending:
                    packing = store.find("packing", pid)
                    pack_no = packing.get("登记编号", str(pid)) if packing else str(pid)
                    return False, (f"包装批 {pack_no} 还有 {len(pending)} 条待翻仓记录"
                                   f"未完成本轮验收，不允许确认发运")
        return True, None

    def get_shipped_batches(self) -> list[dict[str, Any]]:
        """获取已发运的批次清单。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "已确认"]

    def get_trace_codes_for_shipment(self, shipment_entry_id: int) -> list[dict[str, Any]]:
        """获取关联到发运单的溯源码段。"""
        return [r for r in store.rows("trace_code") if r.get("shipment_id") == shipment_entry_id]

    def get_shipment_lineage(self, shipment_entry_id: int) -> list[dict[str, Any]]:
        """获取发运单关联的完整批次追溯链。"""
        entry = store.find(self.MODULE, shipment_entry_id)
        if entry is None:
            return []
        batch_no = entry.get("批次号", "")
        if not batch_no:
            return []
        lineage = store.get_lineage(batch_no)
        result = []
        for node in lineage:
            row = store.find(node["module"], node["entry_id"])
            if row:
                result.append({
                    "module": node["module"],
                    "entry_id": node["entry_id"],
                    "status": row.get("status", ""),
                    "data": dict(row),
                })
        return result