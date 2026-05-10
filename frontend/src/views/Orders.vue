<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { type Order, type Trade } from '@/api'
import { formatDateTime } from '@/utils/time'

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
  return formatDateTime(s)
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
          <el-radio-button label="orders">我的订单</el-radio-button>
          <el-radio-button label="trades">成交记录</el-radio-button>
        </el-radio-group>
        <el-select
          v-if="activeTab === 'orders'"
          v-model="status"
          placeholder="全部状态"
          clearable
          style="width:180px"
          @change="load"
        >
          <el-option label="挂单中" value="open" />
          <el-option label="已成交" value="filled" />
          <el-option label="已撤销" value="cancelled" />
        </el-select>
        <div style="flex:1" />
        <el-button size="small" @click="load">刷新</el-button>
      </div>

      <!-- Orders -->
      <el-table v-if="activeTab === 'orders'" :data="orders" stripe empty-text="暂无订单">
        <el-table-column prop="id" label="编号" width="60" />
        <el-table-column prop="symbol" label="交易对" width="120" />
        <el-table-column label="方向" width="80">
          <template #default="{ row }">
            <span :class="{ up: row.side === 'buy', down: row.side === 'sell' }">
              {{ row.side === 'buy' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            {{ row.type === 'market' ? '市价' : '限价' }}
          </template>
        </el-table-column>
        <el-table-column label="数量" :formatter="(r: any) => fmt(r.quantity, 6)" />
        <el-table-column label="挂单价" :formatter="(r: any) => fmt(r.price, 4)" />
        <el-table-column label="成交价" :formatter="(r: any) => fmt(r.filled_price, 4)" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'filled' ? 'success' : row.status === 'cancelled' ? 'info' : 'warning'"
              size="small"
            >
              {{ row.status === 'filled' ? '已成交' : row.status === 'cancelled' ? '已撤销' : '挂单中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="下单时间" :formatter="(r: any) => fmtTime(r.created_at)" />
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
      <el-table v-else :data="trades" stripe empty-text="暂无成交记录">
        <el-table-column prop="id" label="编号" width="60" />
        <el-table-column prop="order_id" label="订单编号" width="90" />
        <el-table-column prop="symbol" label="交易对" width="120" />
        <el-table-column label="方向" width="80">
          <template #default="{ row }">
            <span :class="{ up: row.side === 'buy', down: row.side === 'sell' }">
              {{ row.side === 'buy' ? '买入' : '卖出' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="数量" :formatter="(r: any) => fmt(r.quantity, 6)" />
        <el-table-column label="成交价" :formatter="(r: any) => fmt(r.price, 4)" />
        <el-table-column label="成交金额" :formatter="(r: any) => '$' + fmt(r.quantity * r.price, 2)" />
        <el-table-column label="手续费" :formatter="(r: any) => '$' + fmt(r.fee ?? 0, 4)" />
        <el-table-column label="成交时间" :formatter="(r: any) => fmtTime(r.created_at)" />
      </el-table>
    </div>
  </div>
</template>
