<template>
  <section class="ship-turning-panel" data-testid="shipment-turning-panel">
    <header class="panel-head">
      <div>
        <h3>翻仓验收发运资格</h3>
        <p class="panel-desc">
          装车草稿逐件对照翻仓验收回执：上一轮已通过核验的包装货物具备发运资格；
          仍有待翻仓记录未完成的，上一轮回执不能当成本轮通过证明，须等本次验收通过后再确认发运。
        </p>
      </div>
      <button class="btn ghost" type="button" data-testid="qual-refresh" @click="load">刷新</button>
    </header>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <table v-if="items.length" class="data-table">
      <thead>
        <tr>
          <th>发运单</th>
          <th>物流单号</th>
          <th>当前状态</th>
          <th>包装货物</th>
          <th>发运资格</th>
          <th>最近翻仓回执</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="q in items" :key="q.shipment_id">
          <tr
            v-for="(g, idx) in q.goods"
            :key="`${q.shipment_id}-${g.packing_id}`"
            :data-testid="`qual-${q.shipment_id}-${g.packing_id}`"
          >
            <td v-if="idx === 0" :rowspan="q.goods.length">{{ q.登记编号 }}</td>
            <td v-if="idx === 0" :rowspan="q.goods.length">{{ q.物流单号 }}</td>
            <td v-if="idx === 0" :rowspan="q.goods.length">{{ q.status }}</td>
            <td>
              {{ g.包装批 }}
              <span v-if="g.reason" class="reason">（{{ g.reason }}）</span>
            </td>
            <td>
              <span class="badge" :class="g.qualified ? 'ok' : 'warn'">
                {{ g.qualified ? '具备发运资格' : '待本轮翻仓验收' }}
              </span>
            </td>
            <td>
              <span v-if="g.last_receipt">
                {{ g.last_receipt.回执编号 }} · {{ g.last_receipt.result }}
              </span>
              <span v-else>—</span>
            </td>
          </tr>
          <tr v-if="!q.goods.length" :key="`${q.shipment_id}-none`">
            <td>{{ q.登记编号 }}</td>
            <td>{{ q.物流单号 }}</td>
            <td>{{ q.status }}</td>
            <td colspan="2">未关联包装批，无需翻仓核验</td>
            <td>—</td>
          </tr>
        </template>
      </tbody>
    </table>
    <p v-else class="empty-state">当前没有待发运的装车草稿</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { fetchShipmentQualifications, type ShipmentQualification } from '@/domain/storage'

const props = defineProps<{ refreshKey?: number }>()

const items = ref<ShipmentQualification[]>([])
const errorMessage = ref('')

async function load() {
  errorMessage.value = ''
  try {
    const result = await fetchShipmentQualifications()
    items.value = result.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发运资格读取失败'
  }
}

watch(() => props.refreshKey, () => { void load() })
onMounted(load)
</script>

<style scoped>
.ship-turning-panel {
  margin-bottom: 16px;
  padding: 14px 16px;
  background: #f7f9fc;
  border: 1px solid #d8e0ec;
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
.badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}
.badge.ok { background: #d4edda; color: #155724; }
.badge.warn { background: #fff3cd; color: #856404; }
.reason {
  color: #b03a2e;
  font-size: 11px;
}
.empty-state {
  color: #95a5a6;
  font-size: 13px;
  margin: 8px 0;
}
</style>
