<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import api from '@/api'

const connected = ref(false)
const backendVersion = ref('')

async function probe(retry = 3) {
  for (let i = 0; i < retry; i++) {
    try {
      const h: any = await api.health()
      connected.value = true
      backendVersion.value = h?.version || ''
      return
    } catch {
      await new Promise((r) => setTimeout(r, 1000))
    }
  }
  connected.value = false
}

onMounted(() => {
  probe()
  setInterval(probe, 15000)
})
</script>

<template>
  <div class="topbar">
    <div class="brand">₿ CRYPTO-SIM</div>
    <nav class="nav">
      <RouterLink to="/dashboard">Dashboard</RouterLink>
      <RouterLink to="/market">Market</RouterLink>
      <RouterLink to="/orders">Orders</RouterLink>
    </nav>
    <div class="spacer" />
    <div class="status">
      <span class="dot" :class="{ ok: connected }" />
      {{ connected ? `Backend v${backendVersion}` : '后端未连接' }}
    </div>
  </div>
  <RouterView />
</template>
