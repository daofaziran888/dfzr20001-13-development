"""翻仓验收路由：同班次批量确认翻仓、验收回执查询与关闭、发运资格对照。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.turning import turning_service
from app.store import store

router = APIRouter(prefix="/api/turning", tags=["翻仓验收"])


class BatchConfirmPayload(BaseModel):
    entry_ids: list[int]
    request_id: str = ""


@router.get("/candidates")
def list_candidates() -> dict[str, Any]:
    """待翻仓记录清单：含班次、包装批状态与验收资格，供工作台勾选。"""
    items = turning_service.list_candidates()
    return {"items": items, "total": len(items)}


@router.post("/batch-confirm")
def batch_confirm(payload: BatchConfirmPayload) -> dict[str, Any]:
    """同班次批量确认翻仓，生成翻仓验收回执；相同 request_id 幂等重放。"""
    receipt, message, idempotent = turning_service.batch_confirm(
        payload.entry_ids, payload.request_id.strip())
    if receipt is None:
        return {"ok": False, "message": message}
    return {"ok": True, "message": message, "receipt": receipt, "idempotent": idempotent}


@router.get("/receipts")
def list_receipts() -> dict[str, Any]:
    """翻仓验收回执列表，最新在前。"""
    items = turning_service.list_receipts()
    return {"items": items, "total": len(items)}


@router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: int) -> dict[str, Any]:
    """单份翻仓验收回执详情。"""
    receipt = turning_service.get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail=f"翻仓验收回执 {receipt_id} 不存在")
    return receipt


@router.post("/receipts/{receipt_id}/close")
def close_receipt(receipt_id: int) -> dict[str, Any]:
    """仓管员关闭本次处理结果。"""
    receipt, message = turning_service.close_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail=message)
    return {"ok": True, "message": message, "receipt": receipt}


@router.get("/shipment-qualifications")
def shipment_qualifications() -> dict[str, Any]:
    """全部未发运发运单的翻仓验收资格对照：哪些货物已具备发运资格，哪些仍待本轮验收。"""
    return {"items": turning_service.open_shipment_qualifications()}


@router.get("/shipment/{shipment_id}/qualification")
def shipment_qualification(shipment_id: int) -> dict[str, Any]:
    """单张发运单的翻仓验收资格对照。"""
    shipment = store.find("shipment", shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"发运单 {shipment_id} 不存在或已归档")
    return turning_service.shipment_qualification(shipment)
