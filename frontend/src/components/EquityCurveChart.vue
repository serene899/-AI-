<script setup lang="ts">
/**
 * 资产净值曲线 —— Apple Stocks 风格的折线图。
 * ─────────────────────────────────────────────
 * - 时间范围切换：1H / 1D / 1W / 1M / ALL
 * - 盈亏变色：期间涨了用 var(--up)，跌了用 var(--down)
 * - 平滑曲线 + 面积渐变 + 最后一个点的光圈脉动
 * - 自动每 30s 刷新一次（和 Dashboard 整体节奏对齐）
 */
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  MarkPointComponent,
} from 'echarts/components'
import api, { type EquityCurve, type EquityRange } from '@/api'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, MarkPointComponent])

const RANGES: { key: EquityRange; label: string }[] = [
  { key: '1H', label: '1H' },
  { key: '1D', label: '1D' },
  { key: '1W', label: '1W' },
  { key: '1M', label: '1M' },
  { key: 'ALL', label: 'ALL' },
]

const range = ref<EquityRange>('1D')
const loading = ref(false)
const curve = shallowRef<EquityCurve | null>(null)

async function refresh() {
  loading.value = true
  try {
    curve.value = await api.equityCurve(range.value)
  } catch {
    // axios 拦截器已处理
  } finally {
    loading.value = false
  }
}

// 盈亏色调
const isUp = computed(() => (curve.value?.change ?? 0) >= 0)
const accentColor = computed(() =>
  isUp.value ? 'var(--up)' : 'var(--down)'
)
// ECharts 需要实际的色值（不能用 CSS 变量），取运行时 computed style
function cssVar(name: string): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim()
}

const chartOption = computed(() => {
  const c = curve.value
  if (!c || !c.points.length) return null
  const upColor = cssVar('--up') || '#30d158'
  const downColor = cssVar('--down') || '#ff453a'
  const lineColor = isUp.value ? upColor : downColor
  const toRgba = (hex: string, alpha: number) => {
    // 支持 #rrggbb
    const h = hex.replace('#', '')
    const r = parseInt(h.substring(0, 2), 16)
    const g = parseInt(h.substring(2, 4), 16)
    const b = parseInt(h.substring(4, 6), 16)
    return `rgba(${r},${g},${b},${alpha})`
  }

  return {
    grid: {
      top: 16,
      right: 16,
      bottom: 28,
      left: 8,
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(44, 44, 46, 0.92)',
      borderColor: 'rgba(84, 84, 88, 0.4)',
      textStyle: { color: '#f5f5f7', fontSize: 12 },
      padding: [8, 12],
      formatter: (params: any) => {
        const p = params[0]
        const v = p.value as number
        const ts = new Date(c.points[p.dataIndex].ts)
        const tsStr = ts.toLocaleString('zh-CN', { hour12: false })
        return `
          <div style="line-height:1.6">
            <div style="color:#ebebf599;font-size:11px">${tsStr}</div>
            <div style="font-size:14px;font-weight:600;font-variant-numeric:tabular-nums">
              $${v.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
          </div>
        `
      },
    },
    xAxis: {
      type: 'category',
      data: c.points.map((p) => p.ts),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: 'rgba(235, 235, 245, 0.45)',
        fontSize: 10,
        // 只显示几个稀疏的刻度
        interval: Math.max(0, Math.floor(c.points.length / 6) - 1),
        formatter: (value: string) => {
          const d = new Date(value)
          if (range.value === '1H' || range.value === '1D') {
            return d.toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
              hour12: false,
            })
          }
          return `${d.getMonth() + 1}/${d.getDate()}`
        },
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      position: 'right',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: 'rgba(235, 235, 245, 0.4)',
        fontSize: 10,
        formatter: (v: number) => {
          if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M'
          if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1) + 'K'
          return v.toFixed(0)
        },
      },
      splitLine: {
        lineStyle: { color: 'rgba(84, 84, 88, 0.22)', type: 'dashed' },
      },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        showSymbol: false,
        symbolSize: 6,
        data: c.points.map((p) => p.equity),
        lineStyle: { color: lineColor, width: 2 },
        itemStyle: { color: lineColor },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: toRgba(lineColor, 0.35) },
              { offset: 1, color: toRgba(lineColor, 0) },
            ],
          },
        },
        emphasis: { focus: 'series' },
        markPoint: {
          data: [
            {
              coord: [c.points.length - 1, c.last],
              symbol: 'circle',
              symbolSize: 10,
              itemStyle: {
                color: lineColor,
                borderColor: '#fff',
                borderWidth: 2,
                shadowBlur: 10,
                shadowColor: toRgba(lineColor, 0.8),
              },
              label: { show: false },
            },
          ],
        },
      },
    ],
  }
})

function fmtUsd(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || isNaN(n as number)) return '--'
  return (n as number).toLocaleString(undefined, {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })
}

let timer: number | undefined
onMounted(() => {
  refresh()
  timer = window.setInterval(refresh, 30_000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

watch(range, refresh)
</script>

<template>
  <div class="equity-chart">
    <!-- 顶部：当前资产 + 区间涨跌 + 范围切换 -->
    <div class="chart-header">
      <div class="chart-summary">
        <div class="summary-label">总资产</div>
        <div class="summary-value">
          ${{ fmtUsd(curve?.last ?? 0) }}
        </div>
        <div
          v-if="curve && curve.points.length > 1"
          class="summary-delta"
          :class="{ up: isUp, down: !isUp }"
        >
          {{ isUp ? '▲' : '▼' }}
          ${{ fmtUsd(Math.abs(curve.change)) }}
          ({{ fmtUsd(curve.change_pct) }}%)
          <span class="muted" style="margin-left:6px;font-size:11px">
            · {{ range }}
          </span>
        </div>
      </div>
      <div class="range-switch">
        <button
          v-for="r in RANGES"
          :key="r.key"
          class="range-btn"
          :class="{ active: range === r.key }"
          @click="range = r.key"
        >
          {{ r.label }}
        </button>
      </div>
    </div>

    <!-- 图表 -->
    <div class="chart-body">
      <VChart
        v-if="chartOption"
        :option="chartOption"
        :autoresize="true"
        :loading="loading"
        class="chart-instance"
      />
      <div v-else class="chart-empty muted">
        <template v-if="loading">图表加载中…</template>
        <template v-else>
          暂无数据 · 系统每分钟采集一次快照，稍等片刻后刷新即可看到曲线
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.equity-chart {
  background: var(--bg-panel);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 22px 14px;
  box-shadow: var(--shadow-card), var(--ring-inner);
}

.chart-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.chart-summary { min-width: 0; }
.summary-label {
  font-size: 12px;
  color: var(--text-sub);
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: none;
}
.summary-value {
  margin-top: 6px;
  font-size: 32px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.summary-delta {
  margin-top: 4px;
  font-size: 13px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.summary-delta.up { color: var(--up); }
.summary-delta.down { color: var(--down); }

.range-switch {
  display: flex;
  gap: 4px;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 10px;
  padding: 3px;
}
.range-btn {
  appearance: none;
  border: 0;
  background: transparent;
  color: var(--text-sub);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: -0.01em;
  padding: 4px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s ease;
}
.range-btn:hover { color: var(--text-main); }
.range-btn.active {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-main);
  box-shadow: var(--ring-inner);
}

.chart-body {
  position: relative;
  height: 260px;
}
.chart-instance {
  width: 100%;
  height: 100%;
}
.chart-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  text-align: center;
  padding: 0 20px;
}

@media (max-width: 600px) {
  .chart-body { height: 200px; }
  .summary-value { font-size: 26px; }
}
</style>
