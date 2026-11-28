"""翻仓验收业务测试：同班次批量确认翻仓、回执幂等、发运门禁联动。

场景还原：
1. 同一班次三条待翻仓记录一起提交，包装组把其中一件重新送审 → 一条校验失败；
2. 回执区分「通过核验」与「已受理」，并写入涉及的包装批；
3. 重交同一份翻仓验收不多记一次翻仓，也不替另一份待翻仓记录结案；
4. 包装批的待翻仓记录未完成时，发运交接不得把上一轮回执当成本轮通过证明；
5. 重新送审的包装确认后，仓管员继续处理没办完的记录，发运员可逐件看到资格变化。
"""
from __future__ import annotations

import unittest

from app.services import service_for
from app.services.turning import turning_service
from app.store import store


def _make_packing(no: str) -> dict:
    svc = service_for("packing")
    entry, errors = svc.create_entry({
        "包装形式": "袋装",
        "净含量": "250",
        "标签文案": "翻仓测试",
        "封口方式": "热封",
        "登记编号": no,
        "负责人": "包装组",
        "生效版本": "v1",
        "备注说明": "",
    })
    assert entry is not None, errors
    entry["status"] = "已确认"
    entry["pending"] = False
    return entry


def _make_storage(no: str, shift: str, packing_id: int) -> dict:
    svc = service_for("storage")
    entry, errors = svc.create_entry({
        "入库温度": "20",
        "入库湿度": "60",
        "陈化周期": "6个月",
        "翻仓日期": "2026-11-27",
        "班次": shift,
        "登记编号": no,
        "负责人": "仓管员",
        "生效版本": "v1",
        "备注说明": "",
        "packing_id": packing_id,
    })
    assert entry is not None, errors
    return entry


def _make_shipment(no: str, packing_id: int) -> dict:
    svc = service_for("shipment")
    entry, errors = svc.create_entry({
        "收货方": "测试收货方",
        "物流单号": no,
        "发运日期": "2026-11-28",
        "承运单位": "测试物流",
        "登记编号": no,
        "负责人": "发运员",
        "生效版本": "v1",
        "备注说明": "",
        "packing_id": packing_id,
    })
    assert entry is not None, errors
    return entry


class TestBatchTurningFlow(unittest.TestCase):
    """同班次三条待翻仓记录批量验收的完整场景。"""

    def setUp(self):
        self.suffix = f"{id(self)}-{len(store.rows('storage'))}"
        self.shift = f"测试早班-{self.suffix}"
        self.packs = [_make_packing(f"PACK-T{self.suffix}-{i}") for i in range(3)]
        self.records = [
            _make_storage(f"STOR-T{self.suffix}-{i}", self.shift, int(self.packs[i]["id"]))
            for i in range(3)
        ]
        self.shipments = [
            _make_shipment(f"SHIP-T{self.suffix}-{i}", int(self.packs[i]["id"]))
            for i in range(3)
        ]
        self.packing_svc = service_for("packing")
        self.shipment_svc = service_for("shipment")

    def _resubmit_one_for_review(self):
        """包装组把第二件包装重新送审：已确认 -> 待确认。"""
        entry, msg = self.packing_svc.run_action(int(self.packs[1]["id"]), "提交确认")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(self.packs[1]["status"], "待确认")

    def _submit_three(self, tag: str):
        ids = [int(r["id"]) for r in self.records]
        return turning_service.batch_confirm(ids, request_id=f"req-{self.suffix}-{tag}")

    def test_batch_confirm_partial_failure_writes_receipt(self):
        """三条同班次记录一起提交：两条通过核验，一条因包装重新送审仅已受理。"""
        self._resubmit_one_for_review()
        receipt, msg, idem = self._submit_three("partial")
        self.assertIsNotNone(receipt, msg)
        self.assertFalse(idem)
        # 回执整体状态：存在未通过核验的记录 -> 已受理
        self.assertEqual(receipt["status"], "已受理")
        self.assertEqual(receipt["班次"], self.shift)
        self.assertEqual(receipt["通过数"], 2)
        self.assertEqual(receipt["受理数"], 1)
        # 逐条结果
        results = {item["entry_id"]: item for item in receipt["items"]}
        r0, r1, r2 = (results[int(r["id"])] for r in self.records)
        self.assertEqual(r0["result"], "通过核验")
        self.assertEqual(r1["result"], "已受理")
        self.assertIn("不具备验收资格", r1["reason"])
        self.assertEqual(r2["result"], "通过核验")
        # 翻仓只记一次，失败记录仍是待翻仓
        self.assertEqual(self.records[0]["翻仓次数"], 1)
        self.assertEqual(self.records[0]["翻仓状态"], "已翻仓")
        self.assertNotEqual(self.records[1].get("翻仓状态"), "已翻仓")
        self.assertTrue(turning_service.is_pending_turning(self.records[1]))
        self.assertEqual(self.records[2]["翻仓次数"], 1)
        # 回执写入涉及的包装批
        pack_nos = {p["登记编号"] for p in receipt["包装批清单"]}
        self.assertEqual(pack_nos, {p["登记编号"] for p in self.packs})
        agg = {p["登记编号"]: p["result"] for p in receipt["包装批清单"]}
        self.assertEqual(agg[self.packs[0]["登记编号"]], "通过核验")
        self.assertEqual(agg[self.packs[1]["登记编号"]], "已受理")

    def test_resubmit_same_acceptance_is_idempotent(self):
        """重交同一份翻仓验收：不多记一次翻仓，也不替另一份待翻仓记录结案。"""
        self._resubmit_one_for_review()
        rid = f"req-{self.suffix}-idem"
        ids = [int(r["id"]) for r in self.records]
        first, _, _ = turning_service.batch_confirm(ids, request_id=rid)
        # 即使包装组随后把包装批重新确认，重交同一份验收也不得改变首轮结果
        self.packs[1]["status"] = "已确认"
        second, msg, idem = turning_service.batch_confirm(ids, request_id=rid)
        self.assertTrue(idem)
        self.assertIn("幂等", msg)
        self.assertEqual(second["回执编号"], first["回执编号"])
        # 不多记一次翻仓
        self.assertEqual(self.records[0]["翻仓次数"], 1)
        self.assertEqual(self.records[2]["翻仓次数"], 1)
        # 不替另一份待翻仓记录结案
        self.assertTrue(turning_service.is_pending_turning(self.records[1]))
        self.assertNotEqual(self.records[1].get("翻仓状态"), "已翻仓")
        # 回执仍然只有一份
        mine = [r for r in store.turning_receipts()
                if r["回执编号"] == first["回执编号"]]
        self.assertEqual(len(mine), 1)

    def test_receipt_only_covers_its_own_records(self):
        """一份回执只覆盖本次提交的记录，不连带结清其他待翻仓记录。"""
        receipt, msg, _ = turning_service.batch_confirm(
            [int(self.records[0]["id"])], request_id=f"req-{self.suffix}-single")
        self.assertIsNotNone(receipt, msg)
        self.assertEqual(receipt["通过数"], 1)
        self.assertTrue(turning_service.is_pending_turning(self.records[1]))
        self.assertTrue(turning_service.is_pending_turning(self.records[2]))

    def test_mixed_shift_rejected(self):
        """跨班次混选不允许批量提交。"""
        self.records[2]["班次"] = f"测试晚班-{self.suffix}"
        ids = [int(r["id"]) for r in self.records]
        receipt, msg, _ = turning_service.batch_confirm(
            ids, request_id=f"req-{self.suffix}-mix")
        self.assertIsNone(receipt)
        self.assertIn("同一班次", msg)
        for r in self.records:
            self.assertNotEqual(r.get("翻仓状态"), "已翻仓")

    def test_new_round_on_turned_records_not_double_counted(self):
        """新一轮请求提交已翻仓记录：拒绝且翻仓次数不变。"""
        ids = [int(r["id"]) for r in self.records]
        turning_service.batch_confirm(ids, request_id=f"req-{self.suffix}-round1")
        receipt, msg, _ = turning_service.batch_confirm(
            ids, request_id=f"req-{self.suffix}-round2")
        self.assertIsNone(receipt)
        self.assertIn("不重复", msg)
        for r in self.records:
            self.assertEqual(r["翻仓次数"], 1)

    def test_shipment_gate_blocks_unfinished_turning(self):
        """待翻仓记录未完成时，发运不得拿上一轮回执当本轮通过证明。"""
        self._resubmit_one_for_review()
        receipt, _, _ = self._submit_three("gate")
        # 仓管员关闭本次处理结果
        closed, cmsg = turning_service.close_receipt(int(receipt["id"]))
        self.assertEqual(closed["status"], "已关闭")
        # 发运员逐件确认三件包装货物
        e0, m0 = self.shipment_svc.run_action(int(self.shipments[0]["id"]), "确认发运")
        self.assertIsNotNone(e0, m0)
        e2, m2 = self.shipment_svc.run_action(int(self.shipments[2]["id"]), "确认发运")
        self.assertIsNotNone(e2, m2)
        # 校验失败那件：上一轮已关闭的回执不能当成本轮通过证明
        e1, m1 = self.shipment_svc.run_action(int(self.shipments[1]["id"]), "确认发运")
        self.assertIsNone(e1)
        self.assertIn("待翻仓", m1)

    def test_reconfirmed_packing_allows_continuation(self):
        """重新送审的包装确认后，仓管员继续处理没办完的记录，发运放行。"""
        self._resubmit_one_for_review()
        self._submit_three("flow")
        # 第一件发运被拦截
        e1, m1 = self.shipment_svc.run_action(int(self.shipments[1]["id"]), "确认发运")
        self.assertIsNone(e1)
        # 重新送审的包装批确认
        entry, msg = self.packing_svc.run_action(int(self.packs[1]["id"]), "确认包装")
        self.assertIsNotNone(entry, msg)
        self.assertEqual(self.packs[1]["status"], "已确认")
        # 仓管员继续处理曾经没办完的记录（新一轮验收）
        receipt2, msg2, _ = turning_service.batch_confirm(
            [int(self.records[1]["id"])], request_id=f"req-{self.suffix}-flow-2")
        self.assertIsNotNone(receipt2, msg2)
        self.assertEqual(receipt2["status"], "通过核验")
        self.assertEqual(self.records[1]["翻仓次数"], 1)
        # 此时发运可通过
        e1b, m1b = self.shipment_svc.run_action(int(self.shipments[1]["id"]), "确认发运")
        self.assertIsNotNone(e1b, m1b)

    def test_shipper_sees_qualification_per_goods(self):
        """发运员看得出哪些货物已具备发运资格、哪些仍要等这次验收。"""
        self._resubmit_one_for_review()
        self._submit_three("vis")
        quals = {q["shipment_id"]: q
                 for q in turning_service.open_shipment_qualifications()}
        q0 = quals[int(self.shipments[0]["id"])]
        q1 = quals[int(self.shipments[1]["id"])]
        # 前一次提交让两件货物具备发运资格
        self.assertTrue(q0["all_qualified"])
        self.assertEqual(q0["goods"][0]["last_receipt"]["result"], "通过核验")
        # 重新送审那件仍要等本轮验收
        self.assertFalse(q1["all_qualified"])
        self.assertEqual(q1["goods"][0]["pending_entry_ids"],
                         [int(self.records[1]["id"])])
        self.assertEqual(q1["goods"][0]["last_receipt"]["result"], "已受理")

    def test_candidates_reflect_packing_status(self):
        """待翻仓候选清单随包装批状态实时反映验收资格。"""
        self.packs[0]["status"] = "待确认"
        cands = {int(c["id"]): c for c in turning_service.list_candidates()}
        self.assertFalse(cands[int(self.records[0]["id"])]["qualified"])
        self.assertTrue(cands[int(self.records[1]["id"])]["qualified"])
        self.assertEqual(cands[int(self.records[0]["id"])]["班次"], self.shift)


if __name__ == "__main__":
    unittest.main()
