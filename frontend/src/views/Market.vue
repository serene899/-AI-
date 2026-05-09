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
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:14px">
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
      <div class="spacer" style="flex:1" />
      <div v-if="currentTicker" style="display:flex;gap:18px;align-items:center">
        <div>
          <div class="muted" style="font-size:11px">LAST</div>
          <div style="font-size:22px;font-weight:600">{{ currentTicker.last }}</div>
        </div>
        <div>
          <div class="muted" style="font-size:11px">24H CHG</div>
          <div :class="{ up: (currentTicker.change24h ?? 0) >= 0, down: (currentTicker.change24h ?? 0) < 0 }">
            {{ ((currentTicker.change24h ?? 0) * 100).toFixed(2) }}%
          </div>
        </div>
        <div>
          <div class="muted" style="font-size:11px">24H HIGH</div>
          <div>{{ currentTicker.high24h }}</div>
        </div>
        <div>
          <div class="muted" style="font-size:11px">24H LOW</div>
          <div>{{ currentTicker.low24h }}</div>
        </div>
      </div>
    </div>

    <div style="display:grid;grid-template-columns: 1fr 340px; gap:16px">
      <div class="panel">
        <KLineChart :symbol="store.currentSymbol" :interval="interval" />
      </div>
      <div class="panel">
        <h2 class="section-title">PLACE ORDER</h2>
        <OrderForm
          :symbol="store.currentSymbol"
          :last-price="currentTicker?.last"
          @submitted="onSubmitted"
        />
      </div>
    </div>
  </div>
</template>
