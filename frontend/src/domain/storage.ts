/** 仓储养护-翻仓验收领域逻辑：同班次批量确认翻仓、验收回执、发运资格对照。 */
import { request } from '@/api/client'

const API = '/api/turning'

export interface TurningCandidate {
  id: number
  登记编号: string
  班次: string
  翻仓日期: string
  翻仓状态: string
  翻仓次数: number
  packing_id: number | null
  包装批: string | null
  包装批状态: string | null
  qualified: boolean
  qualify_reason: string
  status: string
}

export interface TurningReceiptItem {
  entry_id: number
  登记编号: string
  packing_id: number | null
  包装批: string | null
  result: '通过核验' | '已受理'
  reason: string
}

export interface TurningReceipt {
  id: number
  回执编号: string
  班次: string
  status: '通过核验' | '已受理' | '已关闭'
  request_id: string
  提交时间: string
  关闭时间?: string
  items: TurningReceiptItem[]
  包装批清单: { packing_id: number; 登记编号: string; result: string }[]
  通过数: number
  受理数: number
}

export interface ShipmentGoodsQualification {
  packing_id: number
  包装批: string
  qualified: boolean
  reason: string
  pending_entry_ids: number[]
  last_receipt: { id: number; 回执编号: string; result: string; 回执状态: string } | null
}

export interface ShipmentQualification {
  shipment_id: number
  登记编号: string
  物流单号: string
  status: string
  goods: ShipmentGoodsQualification[]
  all_qualified: boolean
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return (await response.json()) as T
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path)
  return (await response.json()) as T
}

export async function fetchTurningCandidates(): Promise<{ items: TurningCandidate[]; total: number }> {
  return getJson(`${API}/candidates`)
}

export async function batchConfirmTurning(
  entryIds: number[],
  requestId: string,
): Promise<{ ok: boolean; message: string; receipt?: TurningReceipt; idempotent?: boolean }> {
  return postJson(`${API}/batch-confirm`, { entry_ids: entryIds, request_id: requestId })
}

export async function fetchTurningReceipts(): Promise<{ items: TurningReceipt[]; total: number }> {
  return getJson(`${API}/receipts`)
}

export async function closeTurningReceipt(
  receiptId: number,
): Promise<{ ok: boolean; message: string; receipt: TurningReceipt }> {
  return postJson(`${API}/receipts/${receiptId}/close`)
}

export async function fetchShipmentQualifications(): Promise<{ items: ShipmentQualification[] }> {
  return getJson(`${API}/shipment-qualifications`)
}
