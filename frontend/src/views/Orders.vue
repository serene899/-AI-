<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { type Order, type Trade } from '@/api'

const activeTab = ref<'orders' | 'trades'>('orders')
const status = ref<string>('')
const orders = ref<Order[]>([])
const trades = ref<Trade[]>([])
let timer: number | undefined

async function load() {
  if (activeTab.value === 'orders') {
    orders.value = await api.listOrders(status.value || undefined)
  } else {
    trades.value = await api.listTrades()
  }
}

async function cancel(row: Order) {
  try {
    await ElMessageBox.confirm(`确认撤销订单 #${row.id} (${row.symbol})?`, '确认', {
      type: 'warning',
    })
    await api.cancelOrder(row.id)
    ElMessage.success('已撤销')
    load()
  } catch {}
}

function fmt(n: number | null | undefined, d = 4) {
  if (n === null || n === undefined) return '--'
  return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
}

function fmtTime(s: string | null) {
  if (!s) return '--'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await load()
  timer = window.setInterval(load, 5000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="panel">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:14px">
        <el-radio-group v-model="activeTab" @change="load">
          <el-radio-button label="orders">订单 Orders</el-radio-button>
          <el-radio-button label="trades">成交 Trades</el-radio-button>
        </el-radio-group>
        <el-select
          v-if="activeTab === 'orders'"
          v-model="status"
          placeholder="全部状态"
          clearable
          style="width:180px"
          @change="load"
        >
          <el-option label="挂单中 open" value="open" />
          <el-option label="已成交 filled" value="filled" />
          <el-option label="已撤销 cancelled" value="cancelled" />
        </el-select>
        <div style="flex:1" />
        <el-button size="small" @click="load">刷新</el-button>
      </div>

      <!-- Orders -->
      <el-table v-if="activeTab === 'orders'" :data="orders" stripe empty-text="暂无订单">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="symbol" label="Symbol" width="120" />
        <el-table-column label="Side" width="80">
          <template #default="{ row }">
            <span :class="{ up: row.side === 'buy', down: row.side === 'sell' }">
              {{ row.side.toUpperCase() }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="type" label="Type" width="90" />
        <el-table-column label="Qty" :formatter="(r: any) => fmt(r.quantity, 6)" />
        <el-table-column label="Price" :formatter="(r: any) => fmt(r.price, 4)" />
        <el-table-column label="Filled Price" :formatter="(r: any) => fmt(r.filled_price, 4)" />
        <el-table-column label="Status" width="110">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'filled' ? 'success' : row.status === 'cancelled' ? 'info' : 'warning'"
              size="small"
            >
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Created" :formatter="(r: any) => fmtTime(r.created_at)" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'open'"
              size="small"
              type="danger"
              link
              @click="cancel(row)"
            >
              撤销
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Trades -->
      <el-table v-else :data="trades" stripe empty-text="暂无成交">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="order_id" label="OrderID" width="90" />
        <el-table-column prop="symbol" label="Symbol" width="120" />
        <el-table-column label="Side" width="80">
          <template #default="{ row }">
            <span :class="{ up: row.side === 'buy', down: row.side === 'sell' }">
              {{ row.side.toUpperCase() }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Qty" :formatter="(r: any) => fmt(r.quantity, 6)" />
        <el-table-column label="Price" :formatter="(r: any) => fmt(r.price, 4)" />
        <el-table-column label="Amount" :formatter="(r: any) => '$' + fmt(r.quantity * r.price, 2)" />
        <el-table-column label="Time" :formatter="(r: any) => fmtTime(r.created_at)" />
      </el-table>
    </div>
  </div>
</template>
