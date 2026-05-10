<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { type Bot, type StrategyDef } from '@/api'
import { useAppStore } from '@/store/app'

const store = useAppStore()

const strategies = ref<StrategyDef[]>([])
const activeBots = ref<Bot[]>([])
const stoppedBots = ref<Bot[]>([])
const loading = ref(false)
const submitting = ref(false)
const showHistory = ref(false)

// 表单状态
const form = reactive<{ strategy: string; symbol: string; params: Record<string, number> }>({
  strategy: 'dca',
  symbol: 'BTC-USDT',
  params: {},
})

const currentStrategy = computed(() =>
  strategies.value.find((s) => s.key === form.strategy)
)

let timer: number | undefined

async function loadAll() {
  try {
    loading.value = true
    const [s, active, stopped] = await Promise.all([
      api.listStrategies(),
      api.listBots('running'),
      api.listBots('stopped'),
    ])
    strategies.value = s
    activeBots.value = active
    stoppedBots.value = stopped
    // 初次填充表单默认参数
    if (!Object.keys(form.params).length) resetParams()
  } finally {
    loading.value = false
  }
}

function resetParams() {
  const st = strategies.value.find((x) => x.key === form.strategy)
  if (!st) return
  const p: Record<string, number> = {}
  st.fields.forEach((f) => (p[f.name] = f.default))
  form.params = p
}

function onStrategyChange() {
  resetParams()
}

async function onStart() {
  if (!form.symbol) return ElMessage.warning('请选择交易对')
  try {
    submitting.value = true
    await api.startBot(form.strategy, form.symbol, form.params)
    ElMessage.success('机器人已启动，开始自动交易')
    await loadAll()
  } catch {
  } finally {
    submitting.value = false
  }
}

async function onStop(bot: Bot) {
  try {
    await ElMessageBox.confirm(
      `确认停止机器人 #${bot.id} (${bot.strategy.toUpperCase()} · ${bot.symbol})？`,
      '确认',
      { type: 'warning' }
    )
    await api.stopBot(bot.id)
    ElMessage.success('已停止')
    await loadAll()
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

function strategyName(k: string) {
  return strategies.value.find((s) => s.key === k)?.name || k
}

function profitOf(b: Bot) {
  // 总盈亏 = 未实现 + 已实现（由后端计算）
  return (b.stats as any).total_pnl ?? 0
}

function unrealizedOf(b: Bot) {
  return (b.stats as any).unrealized_pnl ?? 0
}

function realizedOf(b: Bot) {
  return (b.stats as any).realized_pnl ?? 0
}

function holdingValueOf(b: Bot) {
  return (b.stats as any).holding_value ?? 0
}

onMounted(async () => {
  await store.loadConfig()
  await loadAll()
  timer = window.setInterval(loadAll, 3000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="panel" style="margin-bottom:20px">
      <h2 class="section-title">创建自动交易机器人</h2>
      <el-form label-position="top" inline>
        <el-form-item label="策略类型">
          <el-select v-model="form.strategy" style="width:220px" @change="onStrategyChange">
            <el-option
              v-for="s in strategies"
              :key="s.key"
              :label="s.name"
              :value="s.key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="交易对">
          <el-select v-model="form.symbol" style="width:180px">
            <el-option v-for="s in store.symbols" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-for="f in currentStrategy?.fields"
          :key="f.name"
          :label="f.label"
        >
          <el-input-number
            v-model="form.params[f.name]"
            :min="f.min ?? 0"
            :max="f.max"
            :step="(f.default ?? 1) > 10 ? 10 : 0.1"
            :precision="6"
            style="width:180px"
          />
        </el-form-item>
        <el-form-item label=" " style="align-self:flex-end">
          <el-button
            type="primary"
            :loading="submitting"
            @click="onStart"
          >
            启动机器人
          </el-button>
        </el-form-item>
      </el-form>
      <div v-if="currentStrategy" class="muted" style="font-size:12px;margin-top:4px">
        策略说明：{{ currentStrategy.description }}
      </div>
    </div>

    <div class="panel">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h2 class="section-title" style="margin:0">🟢 运行中的机器人</h2>
        <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
      </div>

      <el-empty v-if="!activeBots.length" description="暂无运行中的机器人，快去上方创建一个吧" />

      <div v-for="b in activeBots" :key="b.id" class="bot-card" style="margin-bottom:14px">
        <div class="bot-header">
          <div>
            <el-tag type="success" size="small">运行中</el-tag>
            <span style="margin-left:8px;font-weight:600">
              #{{ b.id }} · {{ strategyName(b.strategy) }} · {{ b.symbol }}
            </span>
          </div>
          <el-button size="small" type="danger" @click="onStop(b)">
            停止
          </el-button>
        </div>

        <div class="bot-stats">
          <div><span class="muted">成交次数</span><b>{{ b.stats.trades }}</b></div>
          <div><span class="muted">买入次数</span><b class="up">{{ b.stats.buys }}</b></div>
          <div><span class="muted">卖出次数</span><b class="down">{{ b.stats.sells }}</b></div>
          <div><span class="muted">累计买入量</span><b>{{ fmt(b.stats.total_buy_qty, 6) }}</b></div>
          <div><span class="muted">累计卖出量</span><b>{{ fmt(b.stats.total_sell_qty, 6) }}</b></div>
          <div><span class="muted">已花费</span><b>${{ fmt(b.stats.total_spent, 2) }}</b></div>
          <div><span class="muted">已收回</span><b>${{ fmt(b.stats.total_received, 2) }}</b></div>
          <div>
            <span class="muted">持仓市值</span>
            <b>${{ fmt(holdingValueOf(b), 2) }}</b>
          </div>
          <div>
            <span class="muted">未实现盈亏</span>
            <b :class="{ up: unrealizedOf(b) >= 0, down: unrealizedOf(b) < 0 }">
              ${{ fmt(unrealizedOf(b), 2) }}
            </b>
          </div>
          <div>
            <span class="muted">总盈亏</span>
            <b :class="{ up: profitOf(b) >= 0, down: profitOf(b) < 0 }">
              ${{ fmt(profitOf(b), 2) }}
            </b>
          </div>
          <div v-if="b.stats.reference_price">
            <span class="muted">参考价</span><b>{{ fmt(b.stats.reference_price, 4) }}</b>
          </div>
          <div v-if="b.stats.last_price">
            <span class="muted">最新价</span><b>{{ fmt(b.stats.last_price, 4) }}</b>
          </div>
        </div>

        <div class="bot-logs">
          <div class="muted" style="font-size:11px;margin-bottom:6px">
            实时日志（最近 20 条） · 启动于 {{ fmtTime(b.started_at) }}
          </div>
          <div class="log-scroll">
            <div
              v-for="(log, i) in [...b.logs].reverse()"
              :key="i"
              class="log-line"
              :class="log.level"
            >
              <span class="log-ts">{{ fmtTime(log.ts).split(' ')[1] }}</span>
              <span class="log-tag">[{{ log.level }}]</span>
              <span>{{ log.message }}</span>
            </div>
            <div v-if="!b.logs.length" class="muted" style="padding:8px">暂无日志</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 历史归档 -->
    <div class="panel" style="margin-top:20px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h2 class="section-title" style="margin:0">
          📁 历史归档
          <span class="muted" style="font-size:12px;margin-left:8px">({{ stoppedBots.length }})</span>
        </h2>
        <el-button size="small" text @click="showHistory = !showHistory">
          {{ showHistory ? '收起' : '展开' }}
        </el-button>
      </div>

      <template v-if="showHistory">
        <el-empty v-if="!stoppedBots.length" description="暂无历史记录" />

        <div v-for="b in stoppedBots" :key="b.id" class="bot-card bot-card--stopped" style="margin-bottom:14px">
          <div class="bot-header">
            <div>
              <el-tag type="info" size="small">已停止</el-tag>
              <span style="margin-left:8px;font-weight:600">
                #{{ b.id }} · {{ strategyName(b.strategy) }} · {{ b.symbol }}
              </span>
            </div>
            <span class="muted" style="font-size:12px">
              停止于 {{ fmtTime(b.stopped_at) }}
            </span>
          </div>

          <div class="bot-stats">
            <div><span class="muted">成交次数</span><b>{{ b.stats.trades }}</b></div>
            <div><span class="muted">买入次数</span><b class="up">{{ b.stats.buys }}</b></div>
            <div><span class="muted">卖出次数</span><b class="down">{{ b.stats.sells }}</b></div>
            <div><span class="muted">已花费</span><b>${{ fmt(b.stats.total_spent, 2) }}</b></div>
            <div><span class="muted">已收回</span><b>${{ fmt(b.stats.total_received, 2) }}</b></div>
            <div>
              <span class="muted">总盈亏</span>
              <b :class="{ up: profitOf(b) >= 0, down: profitOf(b) < 0 }">
                ${{ fmt(profitOf(b), 2) }}
              </b>
            </div>
          </div>

          <div class="muted" style="font-size:11px;margin-top:6px">
            运行时间: {{ fmtTime(b.started_at) }} ~ {{ fmtTime(b.stopped_at) }}
          </div>
        </div>
      </template>

      <div v-else class="muted" style="font-size:13px;padding:8px 0">
        点击「展开」查看 {{ stoppedBots.length }} 条历史记录
      </div>
    </div>
  </div>
</template>

<style scoped>
.bot-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 22px;
  background: rgba(58, 58, 60, 0.5);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: all 0.2s ease;
}
.bot-card:hover {
  border-color: var(--border-strong);
}
.bot-card--stopped {
  opacity: 0.72;
  background: rgba(44, 44, 46, 0.35);
}
.bot-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 12px;
  flex-wrap: wrap;
}
.bot-stats {
  display: grid;
  /* 自适应列数，最小宽度 140px 保证数字不会被截断重叠 */
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px 20px;
  padding: 14px 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  margin-bottom: 14px;
}
.bot-stats > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 14px;
  min-width: 0; /* 关键：防止 grid 子元素撑出 */
}
.bot-stats > div b {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 15px;
}
.bot-stats .muted {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0;
}
.bot-logs {}
.log-scroll {
  max-height: 220px;
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.28);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
}
.log-line {
  padding: 1px 0;
  color: var(--text-main);
  word-break: break-word;
}
.log-line.trade { color: var(--accent); }
.log-line.error { color: var(--down); }
.log-line.info { color: var(--text-sub); }
.log-ts { color: var(--text-tertiary); margin-right: 10px; }
.log-tag { color: var(--text-sub); margin-right: 6px; }
</style>
