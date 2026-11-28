"""翻仓验收领域服务：同班次批量确认翻仓、翻仓验收回执、发运资格核验。

业务规则：
1. 批量确认翻仓仅限同一班次的待翻仓记录，一次提交生成一份翻仓验收回执。
2. 待翻仓记录只有关联的包装批仍是「已确认」时才具备验收资格；
   回执按记录区分「通过核验」（已记翻仓）与「已受理」（未通过校验，待后续处理）。
3. 重交同一份翻仓验收（相同 request_id）幂等返回原回执，不多记一次翻仓，
   也不替另一份待翻仓记录结案。
4. 包装批存在未完成的待翻仓记录时，发运交接不得把上一轮的回执当成本轮通过证明。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

# 回执与验收结果状态
RECEIPT_PASSED = "通过核验"
RECEIPT_ACCEPTED = "已受理"
RECEIPT_CLOSED = "已关闭"

# 养护记录的翻仓状态
TURN_PENDING = "待翻仓"
TURN_DONE = "已翻仓"


def _norm_packing_id(entry: dict[str, Any]) -> int | None:
    """从记录中解析包装批ID，空值/非法值一律视为未关联。"""
    pid = entry.get("packing_id")
    if pid is None or str(pid).strip() == "":
        return None
    try:
        return int(pid)
    except (TypeError, ValueError):
        return None


class TurningService:
    MODULE = "storage"
    ENTITY = "待翻仓记录"

    # ── 待翻仓判定 ──

    def is_pending_turning(self, entry: dict[str, Any] | None) -> bool:
        """有翻仓日期、未撤回且尚未记翻仓的养护记录即为待翻仓记录。"""
        if not entry:
            return False
        if entry.get("status") == "已撤回":
            return False
        if not str(entry.get("翻仓日期") or "").strip():
            return False
        return entry.get("翻仓状态") != TURN_DONE

    def pending_for_packing(self, packing_id: int) -> list[dict[str, Any]]:
        """指定包装批下仍未完成本轮验收的待翻仓记录。"""
        return [
            row for row in store.rows(self.MODULE)
            if _norm_packing_id(row) == int(packing_id) and self.is_pending_turning(row)
        ]

    # ── 验收资格 ──

    def qualify(self, entry: dict[str, Any]) -> tuple[bool, str]:
        """待翻仓记录只有关联包装批仍是「已确认」时才具备验收资格。"""
        pid = _norm_packing_id(entry)
        if pid is None:
            return False, "未关联包装批，不具备验收资格"
        packing = store.find("packing", pid)
        if packing is None:
            return False, f"关联包装批 {pid} 不存在"
        if packing.get("status") != "已确认":
            return False, f"包装批 {packing.get('登记编号', pid)} 当前状态「{packing.get('status')}」，不具备验收资格"
        return True, ""

    # ── 候选记录 ──

    def list_candidates(self) -> list[dict[str, Any]]:
        """全部待翻仓记录，附带包装批状态与验收资格，供工作台按班次勾选。"""
        result = [self._candidate_view(row) for row in store.rows(self.MODULE)
                  if self.is_pending_turning(row)]
        result.sort(key=lambda item: (str(item.get("班次") or ""), int(item.get("id", 0))))
        return result

    def _candidate_view(self, entry: dict[str, Any]) -> dict[str, Any]:
        view = dict(entry)
        view["班次"] = str(entry.get("班次") or "未分班")
        view["翻仓状态"] = entry.get("翻仓状态") or TURN_PENDING
        view["翻仓次数"] = int(entry.get("翻仓次数") or 0)
        qualified, reason = self.qualify(entry)
        view["qualified"] = qualified
        view["qualify_reason"] = reason
        pid = _norm_packing_id(entry)
        if pid is None:
            view["包装批"] = None
            view["包装批状态"] = None
        else:
            packing = store.find("packing", pid)
            view["包装批"] = packing.get("登记编号") if packing else str(pid)
            view["包装批状态"] = packing.get("status") if packing else "不存在"
        return view

    # ── 批量确认翻仓 ──

    def batch_confirm(self, entry_ids: list[int],
                      request_id: str = "") -> tuple[dict[str, Any] | None, str, bool]:
        """同班次批量确认翻仓，返回 (回执, 消息, 是否幂等重放)。"""
        cache_key = f"turning:{request_id}" if request_id else ""
        if cache_key:
            cached = store.check_idempotent(cache_key)
            if cached:
                receipt = cached.get("receipt") or {}
                return (dict(receipt),
                        f"幂等：回执 {receipt.get('回执编号')} 已提交过，本次不重复记录翻仓",
                        True)

        ids: list[int] = []
        for raw in entry_ids or []:
            try:
                iid = int(raw)
            except (TypeError, ValueError):
                return None, f"无效的记录ID：{raw}", False
            if iid not in ids:
                ids.append(iid)
        if not ids:
            return None, "未选择待翻仓记录", False

        entries: list[dict[str, Any]] = []
        for iid in ids:
            entry = store.find(self.MODULE, iid)
            if entry is None:
                return None, f"养护记录 {iid} 不存在或已归档", False
            entries.append(entry)

        shifts = {str(e.get("班次") or "未分班") for e in entries}
        if len(shifts) > 1:
            return None, "批量确认翻仓仅限同一班次的待翻仓记录，请按班次分别提交", False
        shift = shifts.pop()

        items: list[dict[str, Any]] = []
        attempted = 0
        for entry in entries:
            pid = _norm_packing_id(entry)
            packing = store.find("packing", pid) if pid is not None else None
            item = {
                "entry_id": int(entry["id"]),
                "登记编号": entry.get("登记编号", str(entry["id"])),
                "packing_id": pid,
                "包装批": (packing.get("登记编号") if packing
                           else (str(pid) if pid is not None else None)),
                "result": RECEIPT_ACCEPTED,
                "reason": "",
            }
            if not self.is_pending_turning(entry):
                # 已完成翻仓/已撤回的记录不重复计数，也不替其他记录结案
                item["reason"] = "该记录不在待翻仓状态，不重复记录翻仓"
            else:
                attempted += 1
                qualified, reason = self.qualify(entry)
                if not qualified:
                    item["reason"] = reason
                else:
                    entry["翻仓状态"] = TURN_DONE
                    entry["翻仓次数"] = int(entry.get("翻仓次数") or 0) + 1
                    item["result"] = RECEIPT_PASSED
                    store.log_event(self.MODULE, int(entry["id"]), "确认翻仓",
                                    {"班次": shift, "翻仓次数": entry["翻仓次数"],
                                     "packing_id": pid})
            items.append(item)

        if attempted == 0:
            return None, "所选记录均不在待翻仓状态，本次不重复记录翻仓", False

        passed = sum(1 for item in items if item["result"] == RECEIPT_PASSED)
        accepted = len(items) - passed

        # 涉及的包装批清单：任一所辖记录未通过核验则该包装批整体记为已受理
        packing_map: dict[str, dict[str, Any]] = {}
        for item in items:
            pid = item.get("packing_id")
            if pid is None:
                continue
            agg = packing_map.setdefault(str(pid), {
                "packing_id": pid,
                "登记编号": item.get("包装批") or str(pid),
                "result": RECEIPT_PASSED,
            })
            if item["result"] != RECEIPT_PASSED:
                agg["result"] = RECEIPT_ACCEPTED

        existing = store.turning_receipts()
        receipt = {
            "id": len(existing) + 1,
            "回执编号": f"TURN-{len(existing) + 1:04d}",
            "班次": shift,
            "status": RECEIPT_PASSED if accepted == 0 else RECEIPT_ACCEPTED,
            "request_id": request_id,
            "提交时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": items,
            "包装批清单": list(packing_map.values()),
            "通过数": passed,
            "受理数": accepted,
        }
        store.add_turning_receipt(receipt)

        # 通过核验的记录回写最近回执编号，供交接时对照
        for item in items:
            if item["result"] == RECEIPT_PASSED:
                entry = store.find(self.MODULE, int(item["entry_id"]))
                if entry is not None:
                    entry["最近验收回执"] = receipt["回执编号"]

        message = (f"翻仓验收回执 {receipt['回执编号']} 已生成："
                   f"通过核验 {passed} 条，已受理 {accepted} 条")
        if cache_key:
            store.record_idempotent(cache_key,
                                    {"receipt": receipt, "message": message})
        return receipt, message, False

    # ── 回执查询与关闭 ──

    def list_receipts(self) -> list[dict[str, Any]]:
        """全部翻仓验收回执，最新在前。"""
        return list(reversed(store.turning_receipts()))

    def get_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        return store.find_turning_receipt(receipt_id)

    def close_receipt(self, receipt_id: int) -> tuple[dict[str, Any] | None, str]:
        """仓管员关闭本次处理结果；回执内容保留供交接对照。"""
        receipt = store.find_turning_receipt(receipt_id)
        if receipt is None:
            return None, f"翻仓验收回执 {receipt_id} 不存在"
        if receipt.get("status") == RECEIPT_CLOSED:
            return receipt, f"回执 {receipt.get('回执编号')} 已关闭，无需重复操作"
        receipt["status"] = RECEIPT_CLOSED
        receipt["关闭时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        store.log_event(self.MODULE, 0, "关闭翻仓回执",
                        {"回执编号": receipt.get("回执编号")})
        return receipt, f"回执 {receipt.get('回执编号')} 本次处理结果已关闭"

    # ── 发运资格核验 ──

    def resolve_shipment_packing_ids(self, shipment: dict[str, Any]) -> list[int]:
        """发运单关联的包装批：优先取 packing_id，其次按批次号血缘解析。"""
        ids: list[int] = []
        pid = _norm_packing_id(shipment)
        if pid is not None:
            ids.append(pid)
        batch_no = shipment.get("批次号", "")
        if batch_no:
            for node in store.get_batch_lineage_nodes(batch_no):
                if node["module"] == "packing":
                    ids.append(int(node["entry_id"]))
        return list(dict.fromkeys(ids))

    def last_receipt_for_packing(self, packing_id: int) -> dict[str, Any] | None:
        """指定包装批最近一次出现在回执中的验收结果。"""
        for receipt in reversed(store.turning_receipts()):
            for item in receipt.get("items", []):
                if item.get("packing_id") is not None and \
                        str(item["packing_id"]) == str(packing_id):
                    return {
                        "id": receipt["id"],
                        "回执编号": receipt["回执编号"],
                        "result": item["result"],
                        "回执状态": receipt["status"],
                    }
        return None

    def shipment_qualification(self, shipment: dict[str, Any]) -> dict[str, Any]:
        """逐件核对发运单关联包装货物的发运资格。

        包装批仍有未完成待翻仓记录时不具备发运资格——
        上一轮的翻仓验收回执不能当成本轮的通过证明。
        """
        goods: list[dict[str, Any]] = []
        for pid in self.resolve_shipment_packing_ids(shipment):
            packing = store.find("packing", pid)
            pending = self.pending_for_packing(pid)
            goods.append({
                "packing_id": pid,
                "包装批": packing.get("登记编号", str(pid)) if packing else str(pid),
                "qualified": not pending,
                "reason": "" if not pending else f"{len(pending)} 条待翻仓记录未完成本轮验收",
                "pending_entry_ids": [int(p["id"]) for p in pending],
                "last_receipt": self.last_receipt_for_packing(pid),
            })
        return {
            "shipment_id": shipment.get("id"),
            "登记编号": shipment.get("登记编号", ""),
            "物流单号": shipment.get("物流单号", ""),
            "status": shipment.get("status", ""),
            "goods": goods,
            "all_qualified": all(g["qualified"] for g in goods),
        }

    def open_shipment_qualifications(self) -> list[dict[str, Any]]:
        """全部未发运发运单（装车草稿/待确认）的翻仓验收资格对照。"""
        return [
            self.shipment_qualification(row)
            for row in store.rows("shipment")
            if row.get("status") in ("草稿", "待确认")
        ]


turning_service = TurningService()
