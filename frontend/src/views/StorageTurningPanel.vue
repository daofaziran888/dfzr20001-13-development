<template>
  <section class="turning-panel" data-testid="turning-panel">
    <header class="panel-head">
      <div>
        <h3>同班次批量确认翻仓</h3>
        <p class="panel-desc">
          勾选同一班次的待翻仓记录一次提交，验收结果与涉及包装批写入翻仓验收回执，供交接时确认发运；
          只有关联包装批仍为「已确认」的记录才具备验收资格。
        </p>
      </div>
      <button class="btn ghost" type="button" data-testid="turn-refresh" @click="loadAll">刷新</button>
    </header>

    <p v-if="errorMessage" class="error-text" data-testid="turn-error">{{ errorMessage }}</p>
    <p v-if="infoMessage" class="info-text" data-testid="turn-info">{{ infoMessage }}</p>

    <div v-if="shiftGroups.length" class="shift-groups">
      <div v-for="group in shiftGroups" :key="group.shift" class="shift-group">
        <header class="shift-head">
          <strong>班次：{{ group.shift }}</strong>
          <span>{{ group.items.length }} 条待翻仓</span>
        </header>
        <table class="data-table turning-table">
          <thead>
            <tr>
              <th>选择</th>
              <th>登记编号</th>
              <th>翻仓日期</th>
              <th>包装批</th>
              <th>包装批状态</th>
              <th>验收资格</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in group.items" :key="item.id" :data-testid="`turn-row-${item.id}`">
              <td>
                <input
                  type="checkbox"
                  :checked="selected.has(item.id)"
                  :disabled="!canSelect(item)"
                  :data-testid="`turn-select-${item.id}`"
                  @change="toggle(item)"
                />
              </td>
              <td>{{ item.登记编号 }}</td>
              <td>{{ item.翻仓日期 }}</td>
              <td>{{ item.包装批 ?? '—' }}</td>
              <td>{{ item.包装批状态 ?? '—' }}</td>
              <td>
                <span class="badge" :class="item.qualified ? 'ok' : 'warn'">
                  {{ item.qualified ? '具备验收资格' : '不具备验收资格' }}
                </span>
                <span v-if="item.qualify_reason" class="reason">{{ item.qualify_reason }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <p v-else class="empty-state">当前没有待翻仓记录</p>

    <div class="panel-actions">
      <span>已选 {{ selected.size }} 条{{ selectedShift ? `（班次：${selectedShift}）` : '' }}</span>
      <button
        class="btn primary"
        type="button"
        data-testid="batch-turn-submit"
        :disabled="!selected.size || submitting"
        @click="submit"
      >
        {{ submitting ? '提交中…' : '批量确认翻仓' }}
      </button>
    </div>

    <div v-if="receipts.length" class="receipt-list">
      <h4>翻仓验收回执</h4>
      <article
        v-for="receipt in receipts"
        :key="receipt.id"
        class="receipt"
        :data-testid="`receipt-${receipt.id}`"
      >
        <header class="receipt-head">
          <strong>{{ receipt.回执编号 }}</strong>
          <span>班次：{{ receipt.班次 }}</span>
          <span class="badge" :class="receiptStatusClass(receipt.status)">{{ receipt.status }}</span>
          <span>通过核验 {{ receipt.通过数 }} 条 / 已受理 {{ receipt.受理数 }} 条</span>
          <span class="receipt-time">{{ receipt.提交时间 }}</span>
          <button
            v-if="receipt.status !== '已关闭'"
            class="link"
            type="button"
            :data-testid="`close-receipt-${receipt.id}`"
            @click="closeReceipt(receipt)"
          >
            关闭处理结果
          </button>
        </header>
        <ul class="receipt-items">
          <li v-for="item in receipt.items" :key="item.entry_id">
            <span>{{ item.登记编号 }}（包装批：{{ item.包装批 ?? '—' }}）</span>
            <span class="badge" :class="item.result === '通过核验' ? 'ok' : 'warn'">{{ item.result }}</span>
            <span v-if="item.reason" class="reason">{{ item.reason }}</span>
          </li>
        </ul>
        <p class="receipt-packs">
          涉及包装批：
          <span v-for="pack in receipt.包装批清单" :key="pack.packing_id" class="pack-tag">
            {{ pack.登记编号 }}·{{ pack.result }}
          </span>
          <span v-if="!receipt.包装批清单.length">—</span>
        </p>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  batchConfirmTurning,
  closeTurningReceipt,
  fetchTurningCandidates,
  fetchTurningReceipts,
  type TurningCandidate,
  type TurningReceipt,
} from '@/domain/storage'

const props = defineProps<{ refreshKey?: number }>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const candidates = ref<TurningCandidate[]>([])
const receipts = ref<TurningReceipt[]>([])
const selected = ref<Set<number>>(new Set())
const submitting = ref(false)
const errorMessage = ref('')
const infoMessage = ref('')

// 同一份提交（相同记录组合）复用同一个 request_id：
// 重交时后端幂等返回原回执，不会多记一次翻仓。
const requestIds = new Map<string, string>()

const shiftGroups = computed(() => {
  const groups = new Map<string, TurningCandidate[]>()
  for (const item of candidates.value) {
    const shift = item.班次 || '未分班'
    if (!groups.has(shift)) groups.set(shift, [])
    groups.get(shift)!.push(item)
  }
  return [...groups.entries()].map(([shift, items]) => ({ shift, items }))
})

const selectedShift = computed(() => {
  if (!selected.value.size) return ''
  const first = candidates.value.find((item) => selected.value.has(item.id))
  return first?.班次 ?? ''
})

function canSelect(item: TurningCandidate): boolean {
  if (selected.value.has(item.id)) return true
  if (!selected.value.size) return true
  return item.班次 === selectedShift.value
}

function toggle(item: TurningCandidate) {
  const next = new Set(selected.value)
  if (next.has(item.id)) next.delete(item.id)
  else next.add(item.id)
  selected.value = next
}

function requestIdFor(key: string): string {
  let rid = requestIds.get(key)
  if (!rid) {
    rid = `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    requestIds.set(key, rid)
  }
  return rid
}

async function submit() {
  const ids = [...selected.value].sort((a, b) => a - b)
  if (!ids.length) return
  submitting.value = true
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const result = await batchConfirmTurning(ids, requestIdFor(ids.join(',')))
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    infoMessage.value = result.message
    selected.value = new Set()
    await loadAll()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量确认翻仓失败'
  } finally {
    submitting.value = false
  }
}

async function closeReceipt(receipt: TurningReceipt) {
  errorMessage.value = ''
  try {
    const result = await closeTurningReceipt(receipt.id)
    infoMessage.value = result.message
    await loadAll()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '关闭处理结果失败'
  }
}

function receiptStatusClass(status: string): string {
  if (status === '通过核验') return 'ok'
  if (status === '已关闭') return 'closed'
  return 'warn'
}

async function loadAll() {
  try {
    const [cand, rec] = await Promise.all([fetchTurningCandidates(), fetchTurningReceipts()])
    candidates.value = cand.items
    receipts.value = rec.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '翻仓数据读取失败'
  }
}

watch(() => props.refreshKey, () => { void loadAll() })
onMounted(loadAll)
</script>

<style scoped>
.turning-panel {
  margin-bottom: 16px;
  padding: 14px 16px;
  background: #f7fbF7;
  border: 1px solid #d8e6d8;
  border-radius: 6px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.panel-head h3 {
  margin: 0 0 4px;
  font-size: 15px;
  color: #2c3e50;
}
.panel-desc {
  margin: 0 0 10px;
  font-size: 12px;
  color: #7f8c8d;
}
.shift-group {
  margin-bottom: 10px;
}
.shift-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-bottom: 4px;
  font-size: 13px;
  color: #2c3e50;
}
.shift-head span {
  color: #7f8c8d;
  font-size: 12px;
}
.turning-table {
  margin-bottom: 6px;
}
.panel-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  margin: 8px 0;
  font-size: 13px;
  color: #2c3e50;
}
.receipt-list h4 {
  margin: 12px 0 6px;
  font-size: 14px;
  color: #2c3e50;
}
.receipt {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  background: #fff;
  padding: 8px 12px;
  margin-bottom: 8px;
}
.receipt-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  font-size: 13px;
}
.receipt-time {
  color: #95a5a6;
  font-size: 12px;
}
.receipt-items {
  margin: 6px 0;
  padding-left: 18px;
  font-size: 12px;
  color: #2c3e50;
}
.receipt-items li {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 2px;
}
.receipt-packs {
  margin: 4px 0 0;
  font-size: 12px;
  color: #7f8c8d;
}
.pack-tag {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 6px;
  border: 1px solid #d8e6d8;
  border-radius: 3px;
  background: #f2f8f2;
}
.badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}
.badge.ok { background: #d4edda; color: #155724; }
.badge.warn { background: #fff3cd; color: #856404; }
.badge.closed { background: #e2e3e5; color: #383d41; }
.reason {
  color: #b03a2e;
  font-size: 11px;
}
.info-text {
  color: #1e8449;
  font-size: 12px;
  margin: 4px 0;
}
.empty-state {
  color: #95a5a6;
  font-size: 13px;
  margin: 8px 0;
}
</style>
