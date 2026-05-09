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
  <div>
    <el-radio-group v-model="side" style="margin-bottom:12px">
      <el-radio-button label="buy">
        <span style="color:var(--up)">买入 BUY</span>
      </el-radio-button>
      <el-radio-button label="sell">
        <span style="color:var(--down)">卖出 SELL</span>
      </el-radio-button>
    </el-radio-group>

    <el-form label-position="top" size="default">
      <el-form-item label="订单类型">
        <el-select v-model="type" style="width:100%">
          <el-option label="市价单 Market" value="market" />
          <el-option label="限价单 Limit" value="limit" />
        </el-select>
      </el-form-item>

      <el-form-item label="数量">
        <el-input-number v-model="quantity" :min="0" :step="0.01" :precision="6" style="width:100%" />
      </el-form-item>

      <el-form-item v-if="type === 'limit'" label="价格">
        <el-input-number v-model="price" :min="0" :step="1" :precision="4" style="width:100%" />
      </el-form-item>

      <div class="muted" style="font-size:12px;margin-bottom:10px">
        当前价: {{ lastPrice ?? '--' }} · 预估金额:
        ${{ lastPrice && quantity ? (lastPrice * quantity).toFixed(2) : '--' }}
      </div>

      <el-button
        :type="side === 'buy' ? 'success' : 'danger'"
        :loading="submitting"
        @click="submit"
        style="width:100%"
      >
        确认{{ side === 'buy' ? '买入' : '卖出' }} {{ symbol }}
      </el-button>
    </el-form>
  </div>
</template>
