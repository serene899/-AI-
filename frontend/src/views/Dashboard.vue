<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { type Bot } from '@/api'
import { useAppStore } from '@/store/app'

const store = useAppStore()
const loading = ref(false)
const runningBots = ref<Bot[]>([])
let timer: number | undefined

async function refresh() {
  try {
    loading.value = true
    const [_, __, bs] = await Promise.all([
      store.refreshAccount(),
      store.refreshTickers(),
      api.listBots(),
    ])
    runningBots.value = (bs as Bot[]).filter((b) => b.running)
  } finally {
    loading.value = false
  }
}

async function handleKillAll() {
  if (!runningBots.value.length) return ElMessage.info('当前没有运行中的机器人')
  try {
    await ElMessageBox.confirm(
      `🚨 确认停止全部 ${runningBots.value.length} 个运行中的机器人？`,
      '应急停机',
      { type: 'warning', confirmButtonText: '全部停止', cancelButtonText: '取消' }
    )
    await api.stopAllBots()
    ElMessage.success('已停止所有机器人')
    await refresh()
  } catch {}
}

async function handleReset() {
  try {
    const { value } = await ElMessageBox.prompt('输入新的初始资金（USDT）', '重置账户', {
      inputValue: '10000',
      inputPattern: /^\d+(\.\d+)?$/,
      inputErrorMessage: '请输入正数',
    })
    await api.resetAccount(Number(value))
    ElMessage.success('账户已重置')
    await refresh()
  } catch {}
}

function fmt(n: number | undefined, d = 2) {
  if (n === undefined || n === null || isNaN(n)) return '--'
  return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
}

onMounted(async () => {
  await store.loadConfig()
  await refresh()
  timer = window.setInterval(refresh, 5000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <h2 class="section-title">账户总览</h2>
      <div>
        <el-button size="small" :loading="loading" @click="refresh">刷新数据</el-button>
        <el-button
          v-if="runningBots.length"
          size="small"
          type="danger"
          @click="handleKillAll"
        >
          🚨 应急停机 ({{ runningBots.length }})
        </el-button>
        <el-button size="small" type="danger" plain @click="handleReset">重置账户</el-button>
      </div>
    </div>

    <div class="grid-cards">
      <div class="stat-card">
        <div class="label">总资产</div>
        <div class="value">${{ fmt(store.account?.total_equity) }}</div>
        <div class="delta" :class="{ up: (store.account?.total_pnl ?? 0) >= 0, down: (store.account?.total_pnl ?? 0) < 0 }">
          {{ (store.account?.total_pnl ?? 0) >= 0 ? '▲' : '▼' }}
          {{ fmt(store.account?.total_pnl) }} ({{ fmt(store.account?.total_pnl_pct) }}%)
        </div>
      </div>
      <div class="stat-card">
        <div class="label">现金余额 (USDT)</div>
        <div class="value">${{ fmt(store.account?.cash) }}</div>
        <div class="delta muted">初始资金: ${{ fmt(store.account?.initial_capital) }}</div>
      </div>
      <div class="stat-card">
        <div class="label">持仓市值</div>
        <div class="value">${{ fmt(store.account?.position_market_value) }}</div>
        <div class="delta muted">{{ store.account?.positions.length ?? 0 }} 个持仓</div>
      </div>
      <div class="stat-card">
        <div class="label">未实现盈亏</div>
        <div class="value" :class="{ up: (store.account?.unrealized_pnl ?? 0) >= 0, down: (store.account?.unrealized_pnl ?? 0) < 0 }">
          ${{ fmt(store.account?.unrealized_pnl) }}
        </div>
      </div>
    </div>

    <div style="height:20px" />

    <div class="panel">
      <h2 class="section-title">我的持仓</h2>
      <el-table :data="store.account?.positions ?? []" stripe empty-text="暂无持仓，去「行情交易」页买入吧">
        <el-table-column prop="symbol" label="交易对" />
        <el-table-column prop="quantity" label="数量" :formatter="(r: any) => fmt(r.quantity, 6)" />
        <el-table-column prop="avg_price" label="持仓均价" :formatter="(r: any) => fmt(r.avg_price, 4)" />
        <el-table-column prop="last_price" label="现价" :formatter="(r: any) => fmt(r.last_price, 4)" />
        <el-table-column prop="market_value" label="市值" :formatter="(r: any) => '$' + fmt(r.market_value)" />
        <el-table-column label="盈亏">
          <template #default="{ row }">
            <span :class="{ up: row.unrealized_pnl >= 0, down: row.unrealized_pnl < 0 }">
              ${{ fmt(row.unrealized_pnl) }} ({{ fmt(row.pnl_pct) }}%)
            </span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div style="height:20px" />

    <div class="panel">
      <h2 class="section-title">热门行情</h2>
      <el-table :data="store.tickers" stripe empty-text="行情加载中...">
        <el-table-column prop="symbol" label="交易对" />
        <el-table-column label="最新价" :formatter="(r: any) => fmt(r.last, 4)" />
        <el-table-column label="24小时涨跌">
          <template #default="{ row }">
            <span :class="{ up: (row.change24h ?? 0) >= 0, down: (row.change24h ?? 0) < 0 }">
              {{ fmt((row.change24h ?? 0) * 100, 2) }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="24小时最高" :formatter="(r: any) => fmt(r.high24h, 4)" />
        <el-table-column label="24小时最低" :formatter="(r: any) => fmt(r.low24h, 4)" />
        <el-table-column label="24小时成交量" :formatter="(r: any) => fmt(r.vol24h, 2)" />
      </el-table>
    </div>
  </div>
</template>
