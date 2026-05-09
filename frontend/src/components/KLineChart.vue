<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import api from '@/api'

echarts.use([
  CandlestickChart, LineChart, BarChart,
  GridComponent, TooltipComponent, DataZoomComponent, LegendComponent, TitleComponent,
  CanvasRenderer,
])

const props = defineProps<{ symbol: string; interval?: string }>()

const chartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let timer: number | undefined

async function load() {
  if (!chart || !props.symbol) return
  try {
    const data = await api.kline(props.symbol, props.interval || '1m', 120)
    const times = data.candles.map((c) => {
      const d = new Date(c[0])
      return d.toLocaleTimeString('en-GB', { hour12: false })
    })
    // ECharts candlestick data: [open, close, low, high]
    const candles = data.candles.map((c) => [c[1], c[4], c[3], c[2]])
    const volumes = data.candles.map((c, i) => ({
      value: c[5],
      itemStyle: { color: c[4] >= c[1] ? '#00ff88' : '#ff3b5c' },
    }))
    chart.setOption({
      backgroundColor: 'transparent',
      animation: false,
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      grid: [
        { left: 50, right: 20, top: 30, height: '60%' },
        { left: 50, right: 20, top: '75%', height: '18%' },
      ],
      xAxis: [
        { type: 'category', data: times, axisLine: { lineStyle: { color: '#2a3344' } } },
        { type: 'category', gridIndex: 1, data: times, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#2a3344' } } },
      ],
      yAxis: [
        { scale: true, splitLine: { lineStyle: { color: '#1e2635' } }, axisLabel: { color: '#8b949e' } },
        { gridIndex: 1, splitNumber: 2, splitLine: { show: false }, axisLabel: { color: '#8b949e' } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 }],
      series: [
        {
          name: props.symbol,
          type: 'candlestick',
          data: candles,
          itemStyle: {
            color: '#00ff88', color0: '#ff3b5c',
            borderColor: '#00ff88', borderColor0: '#ff3b5c',
          },
        },
        {
          name: 'Vol',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
        },
      ],
    })
  } catch (e) {
    console.warn('kline load failed', e)
  }
}

onMounted(() => {
  if (chartEl.value) {
    chart = echarts.init(chartEl.value)
    load()
    timer = window.setInterval(load, 10000)
    window.addEventListener('resize', onResize)
  }
})

function onResize() {
  chart?.resize()
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})

watch(() => [props.symbol, props.interval], load)
</script>

<template>
  <div ref="chartEl" style="width:100%;height:420px" />
</template>
