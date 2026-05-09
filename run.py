#!/usr/bin/env python3
"""
Crypto Sim — 一键启动脚本 (跨平台)
用法: python run.py
功能:
  1. 自动检测并安装后端 Python 依赖 (requirements.txt)
  2. 自动检测并安装前端依赖 (npm install)
  3. 并行启动 FastAPI (8000) 与 Vite (5173)
  4. 等后端就绪后自动打开浏览器
  5. Ctrl+C 同时关闭两个子进程
"""
import os
import sys
import time
import signal
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))

IS_WIN = os.name == "nt"


# ---------- helpers ----------
def log(tag: str, msg: str, color: str = "36"):
    print(f"\033[{color}m[{tag}]\033[0m {msg}", flush=True)


def run(cmd, cwd=None, check=True):
    log("run", f"$ {' '.join(cmd)} (cwd={cwd})", "90")
    return subprocess.run(cmd, cwd=cwd, check=check, shell=IS_WIN)


def need(cmd: str) -> str:
    path = shutil.which(cmd)
    if not path:
        log("ERR", f"未找到命令: {cmd}，请先安装", "31")
        sys.exit(1)
    return path


# ---------- setup ----------
def ensure_backend():
    venv_marker = BACKEND / ".deps_installed"
    req = BACKEND / "requirements.txt"
    # 简单时间戳对比：requirements.txt 更新了就重装
    if venv_marker.exists() and venv_marker.stat().st_mtime >= req.stat().st_mtime:
        log("backend", "依赖已安装，跳过", "90")
        return
    log("backend", "安装 Python 依赖 ...", "35")
    run([sys.executable, "-m", "pip", "install", "-r", str(req)])
    venv_marker.write_text("ok")

    # 拷贝 .env.example 到 .env（如果不存在）
    env_file = BACKEND / ".env"
    env_example = BACKEND / ".env.example"
    if not env_file.exists() and env_example.exists():
        env_file.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
        log("backend", "已创建 backend/.env (默认配置)", "33")


def ensure_frontend():
    need("node")
    npm = need("npm")
    node_modules = FRONTEND / "node_modules"
    if node_modules.exists():
        log("frontend", "node_modules 存在，跳过 npm install", "90")
        return
    log("frontend", "安装前端依赖 (这可能需要几分钟) ...", "35")
    run([npm, "install"], cwd=str(FRONTEND))


# ---------- runners ----------
def start_backend():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1",
        "--port", str(BACKEND_PORT),
        "--reload",
    ]
    log("backend", f"启动 uvicorn on :{BACKEND_PORT}", "36")
    return subprocess.Popen(cmd, cwd=str(BACKEND), env=env)


def start_frontend():
    npm = need("npm")
    cmd = [npm, "run", "dev", "--", "--port", str(FRONTEND_PORT)]
    log("frontend", f"启动 Vite on :{FRONTEND_PORT}", "36")
    return subprocess.Popen(cmd, cwd=str(FRONTEND), shell=IS_WIN)


def wait_backend_ready(timeout=30) -> bool:
    url = f"http://127.0.0.1:{BACKEND_PORT}/health"
    log("probe", f"等待后端就绪 {url} ...", "33")
    for i in range(timeout):
        try:
            with urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    log("probe", f"后端已就绪 (用时 {i+1}s) ✓", "32")
                    return True
        except URLError:
            pass
        except Exception:
            pass
        time.sleep(1)
    log("probe", "后端启动超时", "31")
    return False


def open_browser():
    # 延迟一点等 Vite 起来
    def _open():
        time.sleep(2.5)
        url = f"http://127.0.0.1:{FRONTEND_PORT}"
        log("browser", f"打开 {url}", "32")
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()


# ---------- main ----------
def main():
    log("boot", "Crypto Sim 启动中 ...", "36")

    ensure_backend()
    ensure_frontend()

    backend_proc = start_backend()
    if not wait_backend_ready():
        backend_proc.terminate()
        sys.exit(1)

    frontend_proc = start_frontend()
    open_browser()

    log("ready", "=" * 52, "32")
    log("ready", f"  后端 API     → http://127.0.0.1:{BACKEND_PORT}", "32")
    log("ready", f"  API 文档     → http://127.0.0.1:{BACKEND_PORT}/docs", "32")
    log("ready", f"  前端界面     → http://127.0.0.1:{FRONTEND_PORT}", "32")
    log("ready", "  按 Ctrl+C 停止", "32")
    log("ready", "=" * 52, "32")

    def shutdown(*_):
        log("stop", "正在关闭 ...", "33")
        for p in (frontend_proc, backend_proc):
            try:
                if p and p.poll() is None:
                    if IS_WIN:
                        p.terminate()
                    else:
                        p.send_signal(signal.SIGINT)
            except Exception:
                pass
        for p in (frontend_proc, backend_proc):
            try:
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        log("stop", "已退出。", "33")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if not IS_WIN:
        signal.signal(signal.SIGTERM, shutdown)

    # 阻塞等待
    try:
        while True:
            if backend_proc.poll() is not None:
                log("backend", "后端进程退出", "31")
                shutdown()
            if frontend_proc.poll() is not None:
                log("frontend", "前端进程退出", "31")
                shutdown()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
