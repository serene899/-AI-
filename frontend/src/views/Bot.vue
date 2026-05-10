<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { type Bot, type BotLog, type StrategyDef, type StrategyField } from '@/api'
import { useAppStore } from '@/store/app'

const store = useAppStore()

const strategies = ref<StrategyDef[]>([])
const bots = ref<Bot[]>([])
const loading = ref(false)
const submitting = ref(false)

/** 每个机器人卡片独立的日志流（增量拉取） */
const logStreams = reactive<Record<number, BotLog[]>>({})
/** 每个机器人最后一次拉取日志的时间戳 */
const logCursors = reactive<Record<number, number>>({})
/** 折叠状态（默认已停止的自动折叠） */
const collapsed = reactive<Record<number, boolean>>({})

// ========== 创建机器人表单 ==========
const form = reactive<{
  strategy: string
  symbol: string
  params: Record<string, number | string>
}>({
  strategy: 'dca',
  symbol: 'BTC-USDT',
  params: {},
})

const currentStrategy = computed(() =>
  strategies.value.find((s) => s.key === form.strategy)
)

// 估算每分钟下单频率和每日花费（给新手的风险提示）
const riskHint = computed(() => {
  if (!currentStrategy.value) return ''
  const p = form.params
  if (form.strategy === 'dca') {
    const amt = Number(p.amount_usdt) || 0
    const sec = Number(p.interval_sec) || 0
    if (!amt || !sec) return ''
    const perDay = (86400 / sec) * amt
    return `提示：此配置每 ${sec} 秒下单 ${amt} USDT，若行情不回撤，每天约花费 ${perDay.toFixed(0)} USDT`
  }
  return ''
})

// ========== 热编辑对话框 ==========
const editingBot = ref<Bot | null>(null)
const editForm = reactive<Record<string, number | string>>({})
const editSubmitting = ref(false)
const editDialogOpen = ref(false)

function openEditDialog(bot: Bot) {
  editingBot.value = bot
  const st = strategies.value.find((s) => s.key === bot.strategy)
  if (!st) return
  // 只载入 hot=true 的字段
  Object.keys(editForm).forEach((k) => delete editForm[k])
  st.fields
    .filter((f) => f.hot)
    .forEach((f) => {
      editForm[f.name] = bot.params[f.name] ?? f.default
    })
  editDialogOpen.value = true
}

async function submitEdit() {
  if (!editingBot.value) return
  try {
    editSubmitting.value = true
    await api.updateBotParams(editingBot.value.id, { ...editForm })
    ElMessage.success('参数已热更新，下一轮立即生效')
    editDialogOpen.value = false
    await refreshBots()
  } catch {
  } finally {
    editSubmitting.value = false
  }
}

function hotFieldsOf(strategy: string): StrategyField[] {
  const st = strategies.value.find((s) => s.key === strategy)
  return st?.fields.filter((f) => f.hot) ?? []
}

// ========== 数据加载 ==========
async function loadStrategies() {
  strategies.value = await api.listStrategies()
  if (!Object.keys(form.params).length) resetParams()
}

function resetParams() {
  const st = strategies.value.find((x) => x.key === form.strategy)
  if (!st) return
  Object.keys(form.params).forEach((k) => delete form.params[k])
  st.fields.forEach((f) => {
    form.params[f.name] = f.default
  })
}

function onStrategyChange() {
  resetParams()
}

async function refreshBots() {
  loading.value = true
  try {
    bots.value = await api.listBots()
    // 新停止的机器人默认折叠
    bots.value.forEach((b) => {
      if (b.status === 'stopped' && collapsed[b.id] === undefined) {
        collapsed[b.id] = true
      }
    })
    // 清理已删除的日志流
    Object.keys(logStreams).forEach((id) => {
      if (!bots.value.find((b) => b.id === Number(id))) {
        delete logStreams[Number(id)]
        delete logCursors[Number(id)]
      }
    })
  } finally {
    loading.value = false
  }
}

/** 增量拉取单个机器人的日志 */
async function pullLogs(bot: Bot) {
  const since = logCursors[bot.id] || 0
  try {
    const incoming = await api.getBotLogs(bot.id, since)
    if (!logStreams[bot.id]) logStreams[bot.id] = []
    if (incoming.length) {
      logStreams[bot.id].push(...incoming)
      // 只保留最近 200 条
      if (logStreams[bot.id].length > 200) {
        logStreams[bot.id] = logStreams[bot.id].slice(-200)
      }
      logCursors[bot.id] = incoming[incoming.length - 1].ts_epoch
      // 自动滚动到底
      requestAnimationFrame(() => {
        const el = document.getElementById(`log-${bot.id}`)
        if (el) el.scrollTop = el.scrollHeight
      })
    }
  } catch {}
}

async function pullAllLogs() {
  await Promise.all(bots.value.map((b) => pullLogs(b)))
}

// ========== 操作 ==========
async function onStart() {
  if (!form.symbol) return ElMessage.warning('请选择交易币种')
  try {
    submitting.value = true
    await api.startBot(form.strategy, form.symbol, { ...form.params })
    ElMessage.success('机器人已启动，开始自动交易')
    await refreshBots()
  } catch {
  } finally {
    submitting.value = false
  }
}

async function onStop(bot: Bot) {
  try {
    await ElMessageBox.confirm(
      `确认停止机器人 #${bot.id} (${strategyName(bot.strategy)} · ${bot.symbol})？`,
      '确认停止',
      { type: 'warning', confirmButtonText: '停止', cancelButtonText: '取消' }
    )
    await api.stopBot(bot.id)
    ElMessage.success('已发送停止指令')
    await refreshBots()
  } catch {}
}

async function onStopAll() {
  if (!bots.value.some((b) => b.running)) {
    return ElMessage.info('当前没有运行中的机器人')
  }
  try {
    await ElMessageBox.confirm(
      '🚨 确认停止全部运行中的机器人？',
      '应急停机',
      { type: 'warning', confirmButtonText: '全部停止', cancelButtonText: '取消' }
    )
    await api.stopAllBots()
    ElMessage.success('所有机器人已停止')
    await refreshBots()
  } catch {}
}

// ========== 工具函数 ==========
function fmt(n: number | null | undefined, d = 4): string {
  if (n === null || n === undefined || isNaN(n as number)) return '--'
  return n.toLocaleString(undefined, {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })
}

function fmtTime(s: string | null): string {
  if (!s) return '--'
  return new Date(s).toLocaleString('zh-CN', { hour12: false })
}

function fmtShortTime(s: string): string {
  return fmtTime(s).split(' ')[1] ?? s
}

function strategyName(k: string): string {
  return strategies.value.find((s) => s.key === k)?.name || k.toUpperCase()
}

function profitOf(b: Bot): number {
  return b.stats.total_received - b.stats.total_spent
}

function winRate(b: Bot): string {
  const win = b.stats.win_count ?? 0
  const loss = b.stats.loss_count ?? 0
  const total = win + loss
  if (!total) return '--'
  return `${((win / total) * 100).toFixed(1)}%`
}

function runDuration(b: Bot): string {
  const start = new Date(b.started_at).getTime()
  const end = b.stopped_at ? new Date(b.stopped_at).getTime() : Date.now()
  const sec = Math.floor((end - start) / 1000)
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return `${h}h ${m}m`
}

function statusMeta(b: Bot): { type: string; label: string; color: string } {
  switch (b.status) {
    case 'initializing':
      return { type: 'warning', label: '初始化中', color: '#ffbb33' }
    case 'running':
      return { type: 'success', label: '运行中', color: '#00ff88' }
    case 'error':
      return { type: 'danger', label: '错误', color: '#ff3b5c' }
    case 'stopped':
    default:
      return { type: 'info', label: '已停止', color: '#8b949e' }
  }
}

function paramSummary(b: Bot): string {
  const fields = strategies.value.find((s) => s.key === b.strategy)?.fields ?? []
  return fields
    .map((f) => `${f.label.split(' ')[0]}:${b.params[f.name]}`)
    .join(' · ')
}

// ========== 生命周期 ==========
let refreshTimer: number | undefined
let logTimer: number | undefined

onMounted(async () => {
  await store.loadConfig()
  await loadStrategies()
  await refreshBots()
  await pullAllLogs()
  // 基础信息 3 秒一次
  refreshTimer = window.setInterval(refreshBots, 3000)
  // 日志流 1.5 秒一次（实时感）
  logTimer = window.setInterval(pullAllLogs, 1500)
})
onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (logTimer) clearInterval(logTimer)
})
</script>

<template>
  <div class="page">
    <!-- ========== 创建机器人 ========== -->
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
        <el-form-item label="交易币种">
          <el-select v-model="form.symbol" style="width:180px">
            <el-option v-for="s in store.symbols" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item
          v-for="f in currentStrategy?.fields"
          :key="f.name"
          :label="f.label + (f.hot ? ' ♨' : '')"
        >
          <el-select
            v-if="f.type === 'select'"
            v-model="form.params[f.name]"
            style="width:180px"
          >
            <el-option
              v-for="opt in f.options ?? []"
              :key="opt"
              :label="opt"
              :value="opt"
            />
          </el-select>
          <el-input-number
            v-else
            v-model="(form.params[f.name] as number)"
            :min="f.min ?? 0"
            :max="f.max"
            :step="Number(f.default) > 10 ? 10 : 0.1"
            :precision="6"
            style="width:180px"
          />
        </el-form-item>
        <el-form-item label=" " style="align-self:flex-end">
          <el-button type="primary" :loading="submitting" @click="onStart">
            启动机器人
          </el-button>
        </el-form-item>
      </el-form>
      <div v-if="currentStrategy" class="muted" style="font-size:12px;margin-top:4px">
        策略说明：{{ currentStrategy.description }}
        <span style="color:var(--accent);margin-left:8px">（♨ 标记的字段运行中支持热修改）</span>
      </div>
      <div v-if="riskHint" class="warn-hint">⚠ {{ riskHint }}</div>
    </div>

    <!-- ========== 机器人列表 ========== -->
    <div class="panel">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h2 class="section-title" style="margin:0">机器人列表</h2>
        <div>
          <el-button size="small" :loading="loading" @click="refreshBots">刷新</el-button>
          <el-button size="small" type="danger" @click="onStopAll">🚨 停止全部</el-button>
        </div>
      </div>

      <el-empty v-if="!bots.length" description="暂无机器人，快去上方创建一个吧 🤖" />

      <!-- 状态速览表（Task 4：状态列一目了然） -->
      <el-table
        v-if="bots.length"
        :data="bots"
        size="small"
        stripe
        style="margin-bottom:16px"
      >
        <el-table-column prop="id" label="编号" width="60" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag
              :type="(statusMeta(row).type as any)"
              size="small"
              effect="dark"
            >
              {{ statusMeta(row).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="策略">
          <template #default="{ row }">
            {{ strategyName(row.strategy) }}
          </template>
        </el-table-column>
        <el-table-column prop="symbol" label="交易币种" width="120" />
        <el-table-column label="金额 (USDT)" width="120">
          <template #default="{ row }">
            {{ fmt(row.params.amount_usdt, 2) }}
          </template>
        </el-table-column>
        <el-table-column label="成交" width="70">
          <template #default="{ row }">{{ row.stats.trades ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="盈亏 (USDT)" width="130">
          <template #default="{ row }">
            <span :class="{ up: profitOf(row) >= 0, down: profitOf(row) < 0 }">
              {{ fmt(profitOf(row), 2) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="运行时长" width="100">
          <template #default="{ row }">{{ runDuration(row) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.running"
              size="small"
              link
              type="primary"
              @click="openEditDialog(row)"
            >编辑</el-button>
            <el-button
              v-if="row.running"
              size="small"
              link
              type="danger"
              @click="onStop(row)"
            >停止</el-button>
            <el-button
              size="small"
              link
              @click="collapsed[row.id] = !collapsed[row.id]"
            >{{ collapsed[row.id] ? '详情' : '收起' }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-for="b in bots" :key="b.id" class="bot-card" :class="'status-' + b.status">
        <!-- 卡片头 -->
        <div class="bot-header">
          <div class="bot-title">
            <el-tag :type="(statusMeta(b).type as any)" size="small">
              {{ statusMeta(b).label }}
            </el-tag>
            <span class="title-main">
              #{{ b.id }} · {{ strategyName(b.strategy) }} · {{ b.symbol }}
            </span>
            <span class="muted" style="font-size:12px">
              · {{ runDuration(b) }}
            </span>
          </div>
          <div>
            <el-button
              v-if="b.running"
              size="small"
              type="primary"
              plain
              @click="openEditDialog(b)"
            >
              ♨ 编辑参数
            </el-button>
            <el-button
              v-if="b.running"
              size="small"
              type="danger"
              @click="onStop(b)"
            >
              停止
            </el-button>
            <el-button
              size="small"
              link
              @click="collapsed[b.id] = !collapsed[b.id]"
            >
              {{ collapsed[b.id] ? '展开' : '折叠' }}
            </el-button>
          </div>
        </div>

        <!-- 错误横幅 -->
        <div v-if="b.status === 'error' && b.last_error" class="error-banner">
          ❌ {{ b.last_error }}
          <span class="muted" style="margin-left:8px">
            · 连续错误 {{ b.consecutive_errors }} 次
            <span v-if="b.last_error_ts"> · {{ fmtShortTime(b.last_error_ts) }}</span>
          </span>
        </div>

        <div v-if="!collapsed[b.id]">
          <!-- 参数摘要 -->
          <div class="param-summary muted" style="font-size:12px;margin-bottom:8px">
            当前参数：{{ paramSummary(b) }}
          </div>

          <!-- 统计 -->
          <div class="bot-stats">
            <div><span class="muted">成交次数</span><b>{{ b.stats.trades }}</b></div>
            <div><span class="muted">买入</span><b class="up">{{ b.stats.buys }}</b></div>
            <div><span class="muted">卖出</span><b class="down">{{ b.stats.sells }}</b></div>
            <div><span class="muted">累计买入量</span><b>{{ fmt(b.stats.total_buy_qty, 6) }}</b></div>
            <div><span class="muted">累计卖出量</span><b>{{ fmt(b.stats.total_sell_qty, 6) }}</b></div>
            <div><span class="muted">已花费</span><b>${{ fmt(b.stats.total_spent, 2) }}</b></div>
            <div><span class="muted">已收回</span><b>${{ fmt(b.stats.total_received, 2) }}</b></div>
            <div>
              <span class="muted">已实现盈亏</span>
              <b :class="{ up: profitOf(b) >= 0, down: profitOf(b) < 0 }">
                ${{ fmt(profitOf(b), 2) }}
              </b>
            </div>
            <div v-if="b.stats.last_price !== null">
              <span class="muted">最新价</span><b>{{ fmt(b.stats.last_price, 4) }}</b>
            </div>
            <div v-if="b.stats.reference_price !== null">
              <span class="muted">参考价</span><b>{{ fmt(b.stats.reference_price, 4) }}</b>
            </div>
            <div v-if="b.stats.ma_short">
              <span class="muted">MA 短</span><b>{{ fmt(b.stats.ma_short, 4) }}</b>
            </div>
            <div v-if="b.stats.ma_long">
              <span class="muted">MA 长</span><b>{{ fmt(b.stats.ma_long, 4) }}</b>
            </div>
          </div>

          <!-- 实时日志终端 -->
          <div class="log-header muted">
            实时日志 · 启动 {{ fmtTime(b.started_at) }}
            <span v-if="b.stopped_at"> · 停止 {{ fmtTime(b.stopped_at) }}</span>
            <span style="float:right">
              <span class="dot-live" :class="{ active: b.running }"></span>
              {{ b.running ? '直播中' : '回看' }}
            </span>
          </div>
          <div :id="'log-' + b.id" class="log-terminal">
            <div
              v-for="(log, i) in logStreams[b.id] ?? []"
              :key="i"
              class="log-line"
              :class="log.level"
            >
              <span class="log-ts">{{ fmtShortTime(log.ts) }}</span>
              <span class="log-tag">{{
                log.level === 'trade' ? '成交' : log.level === 'error' ? '错误' : '信息'
              }}</span>
              <span class="log-msg">{{ log.message }}</span>
            </div>
            <div v-if="!(logStreams[b.id] ?? []).length" class="muted log-empty">
              等待日志...
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 热编辑对话框 ========== -->
    <el-dialog
      v-model="editDialogOpen"
      :title="editingBot ? `♨ 热编辑参数 · ${strategyName(editingBot.strategy)} #${editingBot.id}` : '编辑参数'"
      width="480px"
    >
      <div v-if="editingBot" class="muted" style="font-size:12px;margin-bottom:12px">
        修改后会在下一轮循环立即生效（当前 sleep 会被唤醒）。
        仅 ♨ 标记字段可热修改；交易币种和策略类型需要停止后重建。
      </div>
      <el-form v-if="editingBot" label-position="top">
        <el-form-item
          v-for="f in hotFieldsOf(editingBot.strategy)"
          :key="f.name"
          :label="f.label"
        >
          <el-select v-if="f.type === 'select'" v-model="editForm[f.name]" style="width:100%">
            <el-option v-for="opt in f.options ?? []" :key="opt" :label="opt" :value="opt" />
          </el-select>
          <el-input-number
            v-else
            v-model="(editForm[f.name] as number)"
            :min="f.min ?? 0"
            :max="f.max"
            :step="Number(f.default) > 10 ? 10 : 0.1"
            :precision="6"
            style="width:100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="submitEdit">
          确认热更新
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bot-card {
  border: 1px solid var(--border);
  border-left: 3px solid var(--text-sub);
  border-radius: 8px;
  padding: 14px 16px;
  background: #121722;
  margin-bottom: 14px;
  transition: border-color 0.3s;
}
.bot-card.status-running { border-left-color: var(--up); }
.bot-card.status-initializing { border-left-color: var(--warn); }
.bot-card.status-error { border-left-color: var(--down); }
.bot-card.status-stopped { border-left-color: var(--text-sub); opacity: 0.85; }

.bot-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  flex-wrap: wrap;
  gap: 8px;
}
.bot-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.title-main { font-weight: 600; font-size: 14px; }

.error-banner {
  background: rgba(255, 59, 92, 0.12);
  border: 1px solid rgba(255, 59, 92, 0.4);
  color: var(--down);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 10px;
}

.param-summary {
  background: #0e131d;
  padding: 6px 10px;
  border-radius: 4px;
}

.warn-hint {
  color: var(--warn);
  background: rgba(255, 187, 51, 0.1);
  border: 1px solid rgba(255, 187, 51, 0.3);
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 12px;
  margin-top: 10px;
}

.bot-stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px 16px;
  padding: 10px 0;
  border-top: 1px dashed var(--border);
  border-bottom: 1px dashed var(--border);
  margin-bottom: 12px;
}
.bot-stats > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
}
.bot-stats .muted { font-size: 11px; }

.log-header {
  font-size: 11px;
  margin-bottom: 4px;
  padding: 0 2px;
}
.dot-live {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-sub);
  margin-right: 4px;
  vertical-align: middle;
}
.dot-live.active {
  background: var(--up);
  box-shadow: 0 0 6px var(--up);
  animation: pulse 1.6s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.log-terminal {
  max-height: 220px;
  overflow-y: auto;
  background: #05080d;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  scroll-behavior: smooth;
}
.log-terminal::-webkit-scrollbar { width: 6px; }
.log-terminal::-webkit-scrollbar-thumb { background: #2a3344; border-radius: 3px; }

.log-line { padding: 1px 0; color: var(--text-main); display: flex; gap: 8px; }
.log-line.trade .log-msg { color: var(--accent); }
.log-line.error .log-msg { color: var(--down); }
.log-line.info .log-msg { color: var(--text-main); opacity: 0.85; }
.log-ts { color: #4a5668; flex-shrink: 0; }
.log-tag {
  color: var(--text-sub);
  flex-shrink: 0;
  min-width: 30px;
  font-size: 11px;
}
.log-line.trade .log-tag { color: var(--accent); }
.log-line.error .log-tag { color: var(--down); }
.log-msg { flex: 1; word-break: break-all; }
.log-empty { padding: 8px; text-align: center; }

@media (max-width: 900px) {
  .bot-stats { grid-template-columns: repeat(2, 1fr); }
}
</style>
