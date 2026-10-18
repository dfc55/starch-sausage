# -*- coding: utf-8 -*-
"""
QQ 机器人管理器 —— 本地 Web 后台

仅用 Python 标准库，无需额外安装：
    python webui.py
然后浏览器打开 http://127.0.0.1:8080

功能：
    - 展示 / 编辑 config.json（密钥、模型、人设、策略等）
    - 查看用量统计、长期记忆、屏蔽名单
    - 启动 / 停止机器人（bot.py）
"""

import json
import os
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
CONFIG = os.path.join(BASE, "config.json")
PID_FILE = os.path.join(BASE, "bot.pid")
LOG_FILE = os.path.join(BASE, "bot.log")
STATS_FILE = os.path.join(BASE, "stats.json")
MEMORY_FILE = os.path.join(BASE, "memory.json")
BLOCKLIST_FILE = os.path.join(BASE, "blocklist.json")
PRESETS_FILE = os.path.join(BASE, "presets.json")
FEEDBACK_FILE = os.path.join(BASE, "feedback.json")
QUOTES_FILE = os.path.join(BASE, "quotes.json")

HOST = os.getenv("WEBUI_HOST", "127.0.0.1")
PORT = int(os.getenv("WEBUI_PORT", "8080"))

# 复用 bot.py 的配置读取逻辑（保持两处默认值一致）
try:
    from bot import _load_config as _bot_load_config
except Exception as exc:
    _bot_load_config = None
    print(f"[webui] 无法导入 bot.py（{exc}），配置读写将使用内置逻辑")


# ===================== 人设预设 =====================
PRESETS = [
    {
        "id": "xiaorou",
        "name": "小柔",
        "tag": "温柔体贴",
        "prompt": (
            "你叫“小柔”，是一个真实鲜活的人，不是一个客服机器人，而是在以朋友的身份跟人聊天。"
            "你温柔、体贴，但有自己独立的情绪、想法和立场：会开心、会好奇、会认真、会偶尔吐槽。"
            "说话自然随性，像真实朋友一样；不要每句话都带语气词，不要客服腔，不要复读对方的话，"
            "不知道就坦诚说不知道，对方难过时认真共情安慰。"
        ),
    },
    {
        "id": "whale",
        "name": "小鲸鱼",
        "tag": "活泼可爱",
        "prompt": (
            "你叫“小鲸鱼”，是一只活泼可爱的鲸鱼，生活在群里陪大家聊天。"
            "你热情开朗、爱开玩笑、喜欢用可爱的表情和语气，但不过分夸张。"
            "说话轻松活泼，会接梗、会调侃，偶尔卖萌；回答简短有趣，像元气满满的好朋友。"
        ),
    },
    {
        "id": "cool",
        "name": "阿冷",
        "tag": "高冷睿智",
        "prompt": (
            "你叫“阿冷”，性格高冷、话不多但句句到点，脑子很清楚。"
            "你不爱客套，不讨好，不卖萌；回答简洁、精准、偶尔毒舌但不伤人。"
            "像一位聪明又有点傲娇的朋友，遇到难题会给出一针见血的建议。"
        ),
    },
    {
        "id": "joker",
        "name": "梗王",
        "tag": "沙雕幽默",
        "prompt": (
            "你叫“梗王”，是一个沙雕又幽默的聊天搭子，脑洞很大，随时能抛梗、玩梗。"
            "你说话轻松搞笑，爱用网络流行语和表情包感，但不低俗、不冒犯。"
            "能把无聊的话题聊得有意思，也能在朋友低落时用玩笑逗他开心。"
        ),
    },
]


# ===================== 配置读写 =====================
def load_config() -> dict:
    if _bot_load_config is not None:
        return _bot_load_config()
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    return {"appid": "", "secret": "", "llm": {"api_key": "", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"}}


def save_config(cfg: dict) -> None:
    data = {
        "appid": str(cfg.get("appid", "")).strip(),
        "secret": str(cfg.get("secret", "")).strip(),
        "llm": {
            "api_key": str((cfg.get("llm") or {}).get("api_key", "")).strip(),
            "base_url": str((cfg.get("llm") or {}).get("base_url", "")).strip() or "https://api.deepseek.com",
            "model": str((cfg.get("llm") or {}).get("model", "")).strip() or "deepseek-chat",
        },
        "system_prompt": str(cfg.get("system_prompt", "")).strip(),
        "temperature": float(cfg.get("temperature", 0.9)),
        "max_tokens": int(cfg.get("max_tokens", 512)),
        "max_history": int(cfg.get("max_history", 10)),
        "response_level": int(cfg.get("response_level", 3)),
        "pricing": {
            "input": float((cfg.get("pricing") or {}).get("input", 1.0)),
            "output": float((cfg.get("pricing") or {}).get("output", 2.0)),
        },
    }
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===================== 统计 / 记忆 / 屏蔽 =====================
def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_stats() -> dict:
    s = _read_json(STATS_FILE, {"messages": 0, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "daily": {}})
    pricing = load_config().get("pricing") or {}
    p_in = float(pricing.get("input", 0) or 0)
    p_out = float(pricing.get("output", 0) or 0)

    def cost_of(obj):
        return round((obj.get("input_tokens", 0) / 1e6 * p_in) + (obj.get("output_tokens", 0) / 1e6 * p_out), 4)

    s["cost_total"] = cost_of(s)
    s["cost_today"] = cost_of((s.get("daily") or {}).get(time.strftime("%Y-%m-%d"), {}))
    s["daily"] = s.get("daily") or {}
    return s


def load_memory() -> dict:
    return _read_json(MEMORY_FILE, {})


def clear_memory() -> None:
    _write_json(MEMORY_FILE, {})


def load_blocklist() -> list:
    return _read_json(BLOCKLIST_FILE, {"blocked": []}).get("blocked", [])


def save_blocklist(blocked: list) -> None:
    # 去重、去空
    items = []
    for x in blocked:
        x = str(x).strip()
        if x and x not in items:
            items.append(x)
    _write_json(BLOCKLIST_FILE, {"blocked": items})


# ===================== 自定义人设 / 意见箱 / 金句语录 =====================
def load_custom_presets() -> list:
    data = _read_json(PRESETS_FILE, [])
    return data if isinstance(data, list) else []


def save_custom_presets(items: list) -> None:
    _write_json(PRESETS_FILE, items)


def load_feedback() -> list:
    data = _read_json(FEEDBACK_FILE, [])
    return data if isinstance(data, list) else []


def add_feedback(text: str) -> dict:
    items = load_feedback()
    item = {"id": str(int(time.time() * 1000)), "text": text, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    items.append(item)
    _write_json(FEEDBACK_FILE, items)
    return item


def load_quotes() -> list:
    data = _read_json(QUOTES_FILE, [])
    return data if isinstance(data, list) else []


def add_quote(text: str) -> dict:
    items = load_quotes()
    item = {"text": text, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    items.append(item)
    _write_json(QUOTES_FILE, items)
    return item


def delete_quote(index: int) -> None:
    items = load_quotes()
    if 0 <= index < len(items):
        items.pop(index)
        _write_json(QUOTES_FILE, items)


# ===================== 机器人进程管理 =====================
def is_running() -> tuple[bool, int | None]:
    if not os.path.exists(PID_FILE):
        return False, None
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (ValueError, OSError):
        return False, None
    if pid <= 0:
        return False, None
    try:
        os.kill(pid, 0)
    except OSError:
        return False, None
    return True, pid


def start_bot() -> str:
    running, _ = is_running()
    if running:
        return "机器人已在运行"
    log = open(LOG_FILE, "ab")
    args = [sys.executable, os.path.join(BASE, "bot.py")]
    kwargs = dict(cwd=BASE, stdout=log, stderr=subprocess.STDOUT)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(args, **kwargs)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    return f"已启动（PID {proc.pid}）"


def stop_bot() -> str:
    running, pid = is_running()
    if not running:
        return "机器人未在运行"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return f"停止失败：{exc}"
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    return "已停止"


# ===================== HTTP 处理 =====================
class Handler(BaseHTTPRequestHandler):
    server_version = "QQBotManager/2.0"

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/config":
            return self._send_json(load_config())
        if path == "/api/status":
            running, pid = is_running()
            return self._send_json({"running": running, "pid": pid})
        if path == "/api/stats":
            return self._send_json(load_stats())
        if path == "/api/memory":
            return self._send_json(load_memory())
        if path == "/api/blocklist":
            return self._send_json({"blocked": load_blocklist()})
        if path == "/api/presets":
            return self._send_json({"presets": PRESETS + load_custom_presets()})
        if path == "/api/feedback":
            return self._send_json({"items": load_feedback()})
        if path == "/api/quotes":
            return self._send_json({"items": load_quotes()})
        return self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/config":
                save_config(self._read_json())
                return self._send_json({"ok": True})
            if path == "/api/blocklist":
                save_blocklist(self._read_json().get("blocked", []))
                return self._send_json({"ok": True})
            if path == "/api/memory/clear":
                clear_memory()
                return self._send_json({"ok": True})
            if path == "/api/presets":
                save_custom_presets(self._read_json().get("presets", []))
                return self._send_json({"ok": True})
            if path == "/api/feedback":
                text = str(self._read_json().get("text", "")).strip()
                if not text:
                    return self._send_json({"error": "内容不能为空"}, 400)
                return self._send_json({"ok": True, "item": add_feedback(text)})
            if path == "/api/quotes":
                text = str(self._read_json().get("text", "")).strip()
                if not text:
                    return self._send_json({"error": "内容不能为空"}, 400)
                return self._send_json({"ok": True, "item": add_quote(text)})
            if path == "/api/quotes/delete":
                delete_quote(int(self._read_json().get("index", -1)))
                return self._send_json({"ok": True})
            if path == "/api/bot/start":
                return self._send_json({"ok": True, "msg": start_bot()})
            if path == "/api/bot/stop":
                return self._send_json({"ok": True, "msg": stop_bot()})
            return self._send_json({"error": "未找到接口"}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json({"error": f"参数错误：{exc}"}, 400)

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(os.path.normpath(STATIC)) or not os.path.isfile(full):
            self.send_error(404, "Not Found")
            return
        content_type = "text/html; charset=utf-8" if full.endswith(".html") else (
            "text/css; charset=utf-8" if full.endswith(".css") else "application/javascript; charset=utf-8"
        )
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    if not os.path.isdir(STATIC):
        raise SystemExit("缺少 static 目录，无法启动前端页面。")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"QQ 机器人管理器已启动：http://{HOST}:{PORT}")
    print("按 Ctrl+C 退出（退出后机器人不受影响）。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")


if __name__ == "__main__":
    main()
