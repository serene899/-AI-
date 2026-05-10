<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { useAppStore } from '@/store/app'

/**
 * 手动下单表单（USDT First）
 * ─────────────────────────────────────────
 * - 统一以 USDT 为输入单位
 * - 市价单：按最新价实时换算代币数量
 * - 限价单：按用户填写的限价换算代币数量
 * - Buy 区显示可用 USDT；Sell 区显示持仓代币数量 + USDT 价值
 * - 25 / 50 / 75 / 100% 快捷按钮：
 *     Buy  -> 按可用 USDT 百分比填充
 *     Sell -> 按"持仓市值 USDT"百分比填充
 */
const props = defineProps<{ symbol: string; lastPrice?: number }>()
const emit = defineEmits<{ (e: 'submitted'): void }>()

const store = useAppStore()

// ───────── 表单状态 ─────────
const side = ref<'buy' | 'sell'>('buy')
const type = ref<'market' | 'limit'>('market')
const amountUsdt = ref<number>(100) // ★ 统一输入单位：USDT
const limitPrice = ref<number | undefined>(undefined)
const submitting = ref(false)

// ───────── 账户信息（从 store 读，实时刷新） ─────────
let accTimer: number | undefined
onMounted(() => {
  // 首次拉一次，再开启 3s 刷新，保证"可用余额"/"持仓"始终最新
  store.refreshAccount().catch(() => {})
  accTimer = window.setInterval(() => store.refreshAccount().catch(() => {}), 3000)
})
onUnmounted(() => {
  if (accTimer) clearInterval(accTimer)
})

// 切换交易对时，清掉旧限价（避免拿 BTC 价格的限价挂到 ETH 去）
watch(
  () => props.symbol,
  () => {
    limitPrice.value = undefined
  }
)

// 切到限价模式且未填限价时，预填当前市价
watch(
  () => [type.value, props.lastPrice] as const,
  ([t, lp]) => {
    if (t === 'limit' && !limitPrice.value && lp) limitPrice.value = lp
  }
)

// ───────── 计算属性 ─────────
const baseCoin = computed(() => props.symbol.split('-')[0] ?? '')

const availableCash = computed(() => store.account?.cash ?? 0)

const position = computed(() =>
  store.account?.positions.find((p) => p.symbol === props.symbol)
)
const heldQty = computed(() => position.value?.quantity ?? 0)

/** 换算用的参考价：市价 → 实时行情；限价 → 用户填的价；都没有则 0 */
const referencePrice = computed(() => {
  if (type.value === 'limit') return limitPrice.value ?? 0
  return props.lastPrice ?? 0
})

/** 输入 USDT 金额 → 代币数量（下单时真正用的 quantity） */
const estimatedQty = computed(() => {
  const p = referencePrice.value
  if (!p || !amountUsdt.value) return 0
  return amountUsdt.value / p
})

/** 持仓当前市值（USDT），按实时价 */
const heldValueUsdt = computed(() => {
  if (!heldQty.value || !props.lastPrice) return 0
  return heldQty.value * props.lastPrice
})

/** 百分比按钮点击 */
function applyPercent(pct: number) {
  if (side.value === 'buy') {
    const cash = availableCash.value
    if (cash <= 0) return ElMessage.warning('可用余额为 0')
    amountUsdt.value = round2(cash * pct)
  } else {
    const v = heldValueUsdt.value
    if (v <= 0) return ElMessage.warning(`当前没有 ${baseCoin.value} 持仓`)
    amountUsdt.value = round2(v * pct)
  }
}

function round2(n: number): number {
  return Math.floor(n * 100) / 100
}

function fmt(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || isNaN(n as number)) return '--'
  return (n as number).toLocaleString(undefined, {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })
}

// ───────── 提交 ─────────
async function submit() {
  if (!props.symbol) return ElMessage.warning('请选择交易对')
  if (!amountUsdt.value || amountUsdt.value <= 0) {
    return ElMessage.warning('请输入有效的 USDT 金额')
  }
  const refP = referencePrice.value
  if (!refP || refP <= 0) {
    return ElMessage.warning(
      type.value === 'limit' ? '请输入限价' : '行情暂未加载，请稍候重试'
    )
  }
  if (type.value === 'limit' && (!limitPrice.value || limitPrice.value <= 0)) {
    return ElMessage.warning('限价单必须填写有效价格')
  }

  let qty = amountUsdt.value / refP

  // Buy 侧预检：别挂到超过可用现金
  if (side.value === 'buy' && amountUsdt.value > availableCash.value + 0.000001) {
    return ElMessage.warning(
      `金额 ${fmt(amountUsdt.value)} USDT 超过可用余额 ${fmt(availableCash.value)} USDT`
    )
  }

  // Sell 侧预检 + 自动收敛：避免"持仓不足"的 400
  if (side.value === 'sell') {
    if (heldQty.value <= 0) {
      return ElMessage.warning(`当前没有 ${baseCoin.value} 持仓`)
    }
    if (qty > heldQty.value) {
      // 如果 100% 点击误差溢出，夹到刚好全仓
      qty = heldQty.value
    }
  }

  // 精度防护：交易量至少 8 位小数，且 > 0
  qty = Math.floor(qty * 1e8) / 1e8
  if (qty <= 0) return ElMessage.warning('换算后的数量过小，请提高金额')

  try {
    submitting.value = true
    await api.createOrder({
      symbol: props.symbol,
      side: side.value,
      type: type.value,
      quantity: qty,
      price: type.value === 'limit' ? limitPrice.value : undefined,
    })
    ElMessage.success(
      `${side.value === 'buy' ? '买入' : '卖出'}下单成功：${qty} ${baseCoin.value}`
    )
    emit('submitted')
    // 下单后立刻刷一下账户，让"可用余额/持仓"立即更新
    store.refreshAccount().catch(() => {})
  } catch {
    /* 错误由 axios 拦截器统一弹 */
  } finally {
    submitting.value = false
  }
}

const percents = [0.25, 0.5, 0.75, 1]
</script>

<template>
  <div class="order-form">
    <!-- 买/卖切换 -->
    <el-radio-group v-model="side" class="side-switch">
      <el-radio-button label="buy">
        <span :class="side === 'buy' ? 'up' : 'muted'">买入</span>
      </el-radio-button>
      <el-radio-button label="sell">
        <span :class="side === 'sell' ? 'down' : 'muted'">卖出</span>
      </el-radio-button>
    </el-radio-group>

    <el-form label-position="top" size="default">
      <!-- 订单类型 -->
      <el-form-item label="订单类型">
        <el-select v-model="type" style="width:100%">
          <el-option label="市价单（按当前价立即成交）" value="market" />
          <el-option label="限价单（指定价格，等待成交）" value="limit" />
        </el-select>
      </el-form-item>

      <!-- 限价 -->
      <el-form-item v-if="type === 'limit'" label="限价 (USDT)">
        <el-input-number
          v-model="limitPrice"
          :min="0"
          :step="1"
          :precision="4"
          style="width:100%"
          :placeholder="String(lastPrice ?? '--')"
        />
      </el-form-item>

      <!-- ★ 核心：USDT 金额输入 -->
      <el-form-item>
        <template #label>
          <div class="amount-label">
            <span>{{ side === 'buy' ? '买入金额' : '卖出金额' }} (USDT)</span>
            <span class="muted hint-right">
              <template v-if="side === 'buy'">
                可用余额:
                <b>{{ fmt(availableCash) }} USDT</b>
                <span class="accent-tag">最大可买</span>
              </template>
              <template v-else>
                当前持有:
                <b>{{ fmt(heldQty, 6) }} {{ baseCoin }}</b>
                <span class="muted">
                  (约价值 <b>{{ fmt(heldValueUsdt) }} USDT</b>)
                </span>
              </template>
            </span>
          </div>
        </template>
        <el-input-number
          v-model="amountUsdt"
          :min="0"
          :step="10"
          :precision="2"
          style="width:100%"
        />
        <div class="convert-hint">
          ≈ <b>{{ fmt(estimatedQty, 8) }}</b> {{ baseCoin }}
          <span class="muted">
            · 换算价
            {{ type === 'limit' ? '(限价)' : '(市价)' }}:
            {{ fmt(referencePrice, 4) }} USDT
          </span>
        </div>
      </el-form-item>

      <!-- 百分比快捷键 -->
      <div class="percent-row">
        <el-button
          v-for="p in percents"
          :key="p"
          size="small"
          class="pct-btn"
          @click="applyPercent(p)"
        >
          {{ p * 100 }}%
        </el-button>
      </div>

      <!-- 提交按钮 -->
      <el-button
        :type="side === 'buy' ? 'success' : 'danger'"
        :loading="submitting"
        size="large"
        class="submit-btn"
        @click="submit"
      >
        确认{{ side === 'buy' ? '买入' : '卖出' }} {{ baseCoin }}
      </el-button>
    </el-form>
  </div>
</template>

<style scoped>
.order-form { }

.side-switch { margin-bottom: 14px; display: block; }
.side-switch :deep(.el-radio-button__inner) { padding: 8px 22px; font-weight: 600; }

.amount-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  width: 100%;
}
.hint-right { font-size: 11px; }
.hint-right b { color: var(--text-main); margin: 0 3px; font-weight: 600; }
.accent-tag {
  color: var(--accent);
  font-size: 10px;
  border: 1px solid var(--accent);
  border-radius: 3px;
  padding: 0 4px;
  margin-left: 6px;
  opacity: 0.85;
}

.convert-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-sub);
}
.convert-hint b { color: var(--accent); font-family: 'JetBrains Mono', monospace; }

.percent-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin: 6px 0 16px;
}
.pct-btn {
  width: 100% !important;
  margin-left: 0 !important;
}

.submit-btn {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
}
</style>
