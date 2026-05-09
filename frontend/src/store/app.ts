import { defineStore } from 'pinia'
import api, { type AccountSnapshot, type Ticker } from '@/api'

interface State {
  symbols: string[]
  currentSymbol: string
  account: AccountSnapshot | null
  tickers: Ticker[]
  loading: boolean
}

export const useAppStore = defineStore('app', {
  state: (): State => ({
    symbols: ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT', 'DOGE-USDT'],
    currentSymbol: 'BTC-USDT',
    account: null,
    tickers: [],
    loading: false,
  }),
  actions: {
    async loadConfig() {
      try {
        const c: any = await api.config()
        if (c?.symbols?.length) this.symbols = c.symbols
      } catch {}
    },
    async refreshAccount() {
      this.account = await api.account()
    },
    async refreshTickers() {
      this.tickers = await api.tickers(this.symbols)
    },
    setSymbol(s: string) {
      this.currentSymbol = s
    },
  },
})
