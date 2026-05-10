<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import KLineChart from '@/components/KLineChart.vue'
import OrderForm from '@/components/OrderForm.vue'
import { useAppStore } from '@/store/app'

const store = useAppStore()
const interval = ref('1m')
let timer: number | undefined

const currentTicker = computed(() =>
  store.tickers.find((t) => t.symbol === store.currentSymbol)
)

async function refresh() {
  await store.refreshTickers()
}

onMounted(async () => {
  await store.loadConfig()
  await refresh()
  timer = window.setInterval(refresh, 5000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

function onSubmitted() {
  store.refreshAccount()
}
</script>

<template>
  <div class="page">
    <div class="market-toolbar">
      <el-select v-model="store.currentSymbol" style="width:180px">
        <el-option v-for="s in store.symbols" :key="s" :label="s" :value="s" />
      </el-select>
      <el-radio-group v-model="interval" size="small">
        <el-radio-button label="1m" />
        <el-radio-button label="5m" />
        <el-radio-button label="15m" />
        <el-radio-button label="1h" />
        <el-radio-button label="4h" />
        <el-radio-button label="1d" />
      </el-radio-group>
      <div class="spacer" />
      <div v-if="currentTicker" class="ticker-summary">
        <div class="ticker-cell">
          <div class="muted">最新价</div>
          <div class="ticker-main">{{ currentTicker.last }}</div>
        </div>
        <div class="ticker-cell">
          <div class="muted">24H 涨跌</div>
          <div :class="{ up: (currentTicker.change24h ?? 0) >= 0, down: (currentTicker.change24h ?? 0) < 0 }">
            {{ ((currentTicker.change24h ?? 0) * 100).toFixed(2) }}%
          </div>
        </div>
        <div class="ticker-cell">
          <div class="muted">24H 最高</div>
          <div>{{ currentTicker.high24h }}</div>
        </div>
        <div class="ticker-cell">
          <div class="muted">24H 最低</div>
          <div>{{ currentTicker.low24h }}</div>
        </div>
      </div>
    </div>

    <div class="market-grid">
      <div class="panel">
        <KLineChart :symbol="store.currentSymbol" :interval="interval" />
      </div>
      <div class="panel">
        <h2 class="section-title">下单面板</h2>
        <OrderForm
          :symbol="store.currentSymbol"
          :last-price="currentTicker?.last"
          @submitted="onSubmitted"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.market-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.market-toolbar .spacer { flex: 1; }

.ticker-summary {
  display: flex;
  gap: 28px;
  align-items: center;
  flex-wrap: wrap;
}
.ticker-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.ticker-cell .muted {
  font-size: 11px;
  font-weight: 500;
}
.ticker-cell > div:last-child {
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  white-space: nowrap;
}
.ticker-cell .ticker-main {
  font-size: 22px;
}

.market-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 18px;
}
@media (max-width: 1100px) {
  .market-grid {
    grid-template-columns: 1fr;
  }
}
</style>
