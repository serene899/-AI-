<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const props = defineProps<{ symbol: string; lastPrice?: number }>()
const emit = defineEmits<{ (e: 'submitted'): void }>()

const side = ref<'buy' | 'sell'>('buy')
const type = ref<'market' | 'limit'>('market')
const quantity = ref<number>(0.01)
const price = ref<number | undefined>(undefined)
const submitting = ref(false)

watch(() => props.lastPrice, (v) => {
  if (type.value === 'limit' && !price.value && v) price.value = v
})

async function submit() {
  if (!props.symbol) return ElMessage.warning('请选择交易对')
  if (!quantity.value || quantity.value <= 0) return ElMessage.warning('数量必须 > 0')
  if (type.value === 'limit' && (!price.value || price.value <= 0))
    return ElMessage.warning('限价单必须填写价格')
  try {
    submitting.value = true
    await api.createOrder({
      symbol: props.symbol,
      side: side.value,
      type: type.value,
      quantity: quantity.value,
      price: type.value === 'limit' ? price.value : undefined,
    })
    ElMessage.success('下单成功')
    emit('submitted')
  } catch {} finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="order-form">
    <el-radio-group v-model="side" class="side-switch">
      <el-radio-button label="buy">
        <span class="side-label side-buy">买入</span>
      </el-radio-button>
      <el-radio-button label="sell">
        <span class="side-label side-sell">卖出</span>
      </el-radio-button>
    </el-radio-group>

    <el-form label-position="top" size="default">
      <el-form-item label="订单类型">
        <el-select v-model="type" style="width:100%">
          <el-option label="市价单（按当前价立即成交）" value="market" />
          <el-option label="限价单（指定价格，自动等待成交）" value="limit" />
        </el-select>
      </el-form-item>

      <el-form-item label="数量">
        <el-input-number v-model="quantity" :min="0" :step="0.01" :precision="6" style="width:100%" />
      </el-form-item>

      <el-form-item v-if="type === 'limit'" label="价格">
        <el-input-number v-model="price" :min="0" :step="1" :precision="4" style="width:100%" />
      </el-form-item>

      <div class="order-hint">
        <div>
          <span class="muted">当前价</span>
          <span>{{ lastPrice ?? '--' }}</span>
        </div>
        <div>
          <span class="muted">预估金额</span>
          <span>${{ lastPrice && quantity ? (lastPrice * quantity).toFixed(2) : '--' }}</span>
        </div>
      </div>

      <el-button
        :type="side === 'buy' ? 'success' : 'danger'"
        :loading="submitting"
        @click="submit"
        class="submit-btn"
      >
        确认{{ side === 'buy' ? '买入' : '卖出' }} {{ symbol }}
      </el-button>
    </el-form>
  </div>
</template>

<style scoped>
.order-form { }
.side-switch {
  margin-bottom: 16px;
  width: 100%;
  display: flex;
}
.side-switch :deep(.el-radio-button),
.side-switch :deep(.el-radio-button__inner) {
  width: 100%;
  flex: 1;
}
.side-label {
  font-weight: 600;
  letter-spacing: -0.01em;
}
.side-buy { color: var(--up); }
.side-sell { color: var(--down); }
.el-radio-button__original-radio:checked + .el-radio-button__inner .side-label {
  color: #fff !important;
}

.order-hint {
  display: flex;
  justify-content: space-between;
  padding: 10px 14px;
  margin-bottom: 14px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 10px;
  font-size: 12px;
}
.order-hint > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.order-hint .muted {
  font-size: 11px;
}
.order-hint > div > span:last-child {
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.submit-btn {
  width: 100%;
  height: 42px;
  font-size: 14px;
  font-weight: 600;
  border-radius: 12px !important;
}
</style>
