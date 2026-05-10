# Crypto Sim · 加密货币自动交易模拟系统

> 独立运行的全栈模拟交易系统：实时对接 **OKX** 公共行情，支持虚拟资金、市价 / 限价挂单、实时盈亏计算。
> 一条命令启动前后端，深色科技风界面。

---

## 📦 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.10+ · FastAPI · SQLModel · SQLite · httpx |
| 前端 | Vue 3 · Vite · TypeScript · Element Plus · Pinia · ECharts |
| 行情 | OKX V5 公共 API (无需 Key) |

---

## 🚀 一键启动

### 前置依赖
- **Python 3.10+**
- **Node.js 18+** (含 npm)

### 启动（三选一）

```bash
# 方式 A (推荐，跨平台)
python run.py

# 方式 B (Linux / macOS)
chmod +x start.sh
./start.sh

# 方式 C (Windows 双击)
start.bat
```

启动脚本会：
1. 自动安装 `backend/requirements.txt` 与 `frontend/package.json` 里的依赖
2. 首次运行自动复制 `backend/.env.example → backend/.env`
3. 启动后端 (`127.0.0.1:8000`) 与前端 (`127.0.0.1:5173`)
4. 等后端 `/health` 返回 200 后自动打开浏览器

### 启动成功后访问

| 地址 | 说明 |
|---|---|
| http://127.0.0.1:5173 | **前端界面** |
| http://127.0.0.1:8000/docs | Swagger API 文档 |
| http://127.0.0.1:8000/health | 健康检查 |

按 `Ctrl+C` 同时关闭前后端。

---

## 🗂 项目结构

```
crypto-sim/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 (CORS + 路由)
│   │   ├── config.py            # 读取 .env
│   │   ├── api/                 # 路由层
│   │   ├── services/            # exchange / matching / portfolio
│   │   ├── models/              # SQLModel + Pydantic schemas
│   │   └── core/response.py     # 统一响应
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── views/               # Dashboard / Market / Orders
│   │   ├── components/          # KLineChart / OrderForm
│   │   ├── api/                 # axios 封装
│   │   ├── store/               # Pinia
│   │   └── styles/theme.scss    # 深色科技风
│   ├── vite.config.ts           # ★ proxy 解决 CORS
│   └── package.json
├── run.py                       # 一键启动 (跨平台)
├── start.sh / start.bat
└── README.md
```

---

## 🔌 REST API 接口协议

所有接口前缀：`/api/v1`（除健康检查）。统一响应：

```json
{ "code": 0, "message": "ok", "data": { ... } }
```

### 系统
| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/config` | 交易所 / 支持交易对 / 版本 |

### 行情
| Method | Path | 参数 |
|---|---|---|
| GET | `/api/v1/market/ticker` | `symbol=BTC-USDT` |
| GET | `/api/v1/market/tickers` | `symbols?=BTC-USDT,ETH-USDT` |
| GET | `/api/v1/market/kline` | `symbol`, `interval=1m`, `limit=100` |

### 账户
| Method | Path | Body |
|---|---|---|
| GET | `/api/v1/account` | - |
| POST | `/api/v1/account/reset` | `{ "initial_capital": 10000 }` |

### 交易
| Method | Path | 说明 |
|---|---|---|
| POST | `/api/v1/orders` | `{ symbol, side, type, quantity, price? }` |
| GET | `/api/v1/orders?status=open` | 订单列表 |
| DELETE | `/api/v1/orders/{id}` | 撤单 |
| GET | `/api/v1/trades` | 成交历史 |
| GET | `/api/v1/positions` | 当前持仓 |

---

## 🔐 安全与配置

所有敏感信息通过 `backend/.env` 注入，**严禁硬编码到代码中**。

```bash
EXCHANGE=okx
OKX_API_KEY=               # 公共行情无需填写
OKX_SECRET_KEY=
OKX_PASSPHRASE=
INITIAL_CAPITAL=10000
DB_PATH=./data.db
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
BACKEND_PORT=8000
```

---

## 🛠 前后端连接问题 — 本项目的解决方案

这是上次踩坑的重点，本项目用 **三层保障** 彻底规避：

### 1. Vite Proxy（核心）
`frontend/vite.config.ts` 中把 `/api/*` 和 `/health` 全部转发到 `127.0.0.1:8000`。
前端代码里**永远只写相对路径** `/api/v1/xxx`，不会出现 `localhost:8000` 硬编码。

### 2. 后端 CORSMiddleware
`backend/app/main.py` 显式加载 CORS 白名单（从 `.env` 读取）。
即使不走 proxy，本机两个端口也能互通。

### 3. 前端启动时探活
`App.vue` 加载后立即请求 `/health`，失败会重试 3 次；顶栏的绿点/红点实时显示连接状态，长期心跳每 15 秒检测一次。

---

## 🧠 撮合引擎逻辑

- **市价单**：下单瞬间以当前 OKX ticker 成交，扣现金 / 加持仓
- **限价单**：进入 `open` 状态 → 后台每 2s 扫描 → 条件满足自动成交
  - 买单：`last_price <= order.price` → 成交
  - 卖单：`last_price >= order.price` → 成交
- **盈亏**：持仓均价法，`未实现盈亏 = (现价 - 均价) × 数量`

---

## ❓ FAQ

**Q: 安装依赖时报错 `Failed building wheel for pydantic-core`？**
你大概率在用 **Python 3.14**。该版本过新，部分依赖还没发布预编译包，pip 会尝试从源码编译并失败。
✅ 解决：改用 **Python 3.12 或 3.13**（稳定版），从 https://www.python.org/downloads/ 下载。
安装后删掉 `backend/.deps_installed` 标记文件，重新 `python run.py` 即可。

**Q: 国内 PyPI 下载慢？**
```bash
pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```
npm 也可用淘宝镜像：`npm config set registry https://registry.npmmirror.com`

**Q: OKX 行情拉不到 / 国内网络？**
OKX 在国内大部分地区可直连。若失败，检查防火墙或在 `backend/.env` 里把 `EXCHANGE` 预留切换（后续可扩展 Binance）。

**Q: 想重置账户？**
Dashboard 页面右上角 **重置账户** 按钮，或调用 `POST /api/v1/account/reset`。

**Q: 端口被占用？**
在 `backend/.env` 改 `BACKEND_PORT`，或启动前设置环境变量：
```bash
FRONTEND_PORT=5180 BACKEND_PORT=8080 python run.py
```

**Q: 数据会丢吗？**
不会。所有账户 / 持仓 / 订单 / 成交持久化在 `backend/data.db` (SQLite)。重启自动加载。

---

## 📄 License

MIT — 随便折腾。
