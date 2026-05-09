import axios, { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/',
  timeout: 15000,
})

// 统一错误处理
http.interceptors.response.use(
  (resp) => {
    const data = resp.data
    // 后端统一格式: {code, message, data}
    if (data && typeof data === 'object' && 'code' in data) {
      if (data.code !== 0) {
        ElMessage.error(data.message || '请求失败')
        return Promise.reject(new Error(data.message || 'api error'))
      }
      return data.data
    }
    return data
  },
  (err: AxiosError<any>) => {
    const msg =
      err.response?.data?.detail ||
      err.response?.data?.message ||
      err.message ||
      '网络错误'
    ElMessage.error(`[${err.response?.status || 'ERR'}] ${msg}`)
    return Promise.reject(err)
  }
)

// -------- Types --------
export interface Ticker {
  symbol: string
  last: number
  high24h?: number
  low24h?: number
  vol24h?: number
  change24h?: number
  bid?: number
  ask?: number
}

export interface Kline {
  symbol: string
  interval: string
  candles: number[][]
}

export interface Position {
  symbol: string
  quantity: number
  avg_price: number
  last_price: number
  market_value: number
  unrealized_pnl: number
  pnl_pct: number
}

export interface AccountSnapshot {
  cash: number
  initial_capital: number
  position_market_value: number
  total_equity: number
  total_pnl: number
  total_pnl_pct: number
  unrealized_pnl: number
  positions: Position[]
}

export interface Order {
  id: number
  symbol: string
  side: 'buy' | 'sell'
  type: 'market' | 'limit'
  quantity: number
  price: number | null
  status: 'open' | 'filled' | 'cancelled'
  filled_price: number | null
  filled_at: string | null
  created_at: string
}

export interface Trade {
  id: number
  order_id: number
  symbol: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  created_at: string
}

// -------- API --------
export const api = {
  health: () => http.get('/health'),
  config: () => http.get<any, { exchange: string; symbols: string[]; version: string }>('/api/v1/config'),

  ticker: (symbol: string) => http.get<any, Ticker>('/api/v1/market/ticker', { params: { symbol } }),
  tickers: (symbols?: string[]) =>
    http.get<any, Ticker[]>('/api/v1/market/tickers', {
      params: symbols ? { symbols: symbols.join(',') } : {},
    }),
  kline: (symbol: string, interval = '1m', limit = 100) =>
    http.get<any, Kline>('/api/v1/market/kline', {
      params: { symbol, interval, limit },
    }),

  account: () => http.get<any, AccountSnapshot>('/api/v1/account'),
  resetAccount: (initial_capital: number) =>
    http.post<any, AccountSnapshot>('/api/v1/account/reset', { initial_capital }),

  createOrder: (body: {
    symbol: string
    side: 'buy' | 'sell'
    type: 'market' | 'limit'
    quantity: number
    price?: number
  }) => http.post<any, Order>('/api/v1/orders', body),

  listOrders: (status?: string) =>
    http.get<any, Order[]>('/api/v1/orders', { params: status ? { status } : {} }),
  cancelOrder: (id: number) => http.delete<any, Order>(`/api/v1/orders/${id}`),
  listTrades: () => http.get<any, Trade[]>('/api/v1/trades'),
}

export default api
