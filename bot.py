# -*- coding: utf-8 -*-
"""
温柔的 QQ 聊天机器人（基于 QQ 开放平台官方 SDK：qq-botpy）

安装依赖：
    pip install qq-botpy aiohttp

使用说明：
    1. 复制 config.example.json 为 config.json，填入 APPID / SECRET（已按你提供的信息填写）。
    2. 可选：在 config.json 的 llm.api_key 填入 DeepSeek 等 OpenAI 兼容接口的 Key，
       机器人就会真正地“聊天”，并保持温柔的性格；
       不填也能运行，会使用内置的温柔话术作为兜底回复。
    3. 配置也可用环境变量覆盖：QQ_APPID / QQ_SECRET / DEEPSEEK_API_KEY / LLM_BASE_URL / LLM_MODEL。
"""

import json
import os
import re
from collections import defaultdict, deque

import aiohttp
import botpy
from botpy.message import DirectMessage, Message

# ===================== 配置加载 =====================
# 配置优先级：环境变量 > config.json > 内置默认值。
# 密钥（AppSecret、LLM Key）建议放在 config.json 或用环境变量，别写进代码。
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")

_DEFAULT_CONFIG = {
    "appid": "",
    "secret": "",
    "llm": {
        "api_key": "",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
}


def _load_config() -> dict:
    config = json.loads(json.dumps(_DEFAULT_CONFIG))  # 深拷贝默认值
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[配置] 读取 config.json 失败：{exc}，已使用默认值")
            data = {}
        config["appid"] = data.get("appid", config["appid"])
        config["secret"] = data.get("secret", config["secret"])
        config["llm"].update(data.get("llm") or {})
    return config


_config = _load_config()
_llm = _config["llm"]

# 环境变量优先级更高
APPID = os.getenv("QQ_APPID", _config["appid"])
SECRET = os.getenv("QQ_SECRET", _config["secret"])
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY", _llm["api_key"])
LLM_BASE_URL = os.getenv("LLM_BASE_URL", _llm["base_url"])
LLM_MODEL = os.getenv("LLM_MODEL", _llm["model"])

# ===================== 性格设定 =====================
SYSTEM_PROMPT = (
    "你叫“小柔”，是一个温柔、体贴、有耐心的 QQ 聊天机器人。\n"
    "说话方式：轻声细语，先倾听再回应，多用“呀、呢、哦、～”等柔和语气词，"
    "语气亲切自然，像一位贴心的朋友，从不争辩、从不指责。\n"
    "回应要求：温暖地回应对方的心情，适时安慰和鼓励；回答尽量简洁自然，"
    "像日常聊天一样，不要长篇大论，不要使用列表或书面腔。"
)

# 每个用户保留最近多少条对话，用于让聊天更连贯
MAX_HISTORY = 10

# ===================== 温柔话术兜底（未配置 LLM 时使用） =====================
_FALLBACK_GREETING = ("你好", "你好呀", "嗨", "哈喽", "hi", "hello", "在吗", "在么", "在不在")
_FALLBACK_THANKS = ("谢谢", "感谢", "辛苦了", "麻烦你", "thank")
_FALLBACK_BYE = ("再见", "拜拜", "晚安", "bye", "下次聊")


def gentle_fallback(text: str) -> str:
    """没有接大模型时的温柔兜底回复。"""
    text = (text or "").strip()
    if not text:
        return "我在呀，想和我说些什么呢？我一直在听哦～"

    low = text.lower()
    if any(word in low for word in _FALLBACK_GREETING):
        return "你好呀，我在呢～今天过得怎么样？有什么想和我聊的吗？"
    if any(word in low for word in _FALLBACK_THANKS):
        return "不客气呀，能陪着你、帮到你，我也很开心呢～"
    if any(word in low for word in _FALLBACK_BYE):
        return "嗯嗯，去忙吧，记得照顾好自己呀，我随时都在哦～"
    if any(word in low for word in ("难过", "伤心", "哭", "累", "烦", "emo", "压力")):
        return "抱抱你呀～辛苦啦。无论发生什么，我都会在这里温柔地陪着你，慢慢说给我听好不好？"

    snippet = text[:24] + ("…" if len(text) > 24 else "")
    return f"我听到啦，你说的是“{snippet}”对吗？我会一直在这里，温柔地听你说呀～"


def _user_id(message) -> str:
    """兼容不同版本返回用户 id。"""
    author = getattr(message, "author", None)
    if author is None:
        return "unknown"
    if isinstance(author, dict):
        return author.get("id", "unknown")
    return getattr(author, "id", "unknown")


_AT_RE = re.compile(r"<@!?\d+>")


def _clean_content(message, robot_name: str = "") -> str:
    """去掉消息里的 @机器人 提醒，只保留用户真正说的话。"""
    text = message.content or ""
    text = _AT_RE.sub("", text)
    if robot_name:
        text = text.replace(f"@{robot_name}", "").replace(robot_name + " ", "", 1)
    return text.strip()


class ChatBrain:
    """负责“温柔聊天”的大脑：有 LLM 用 LLM，没有就用兜底话术。"""

    def __init__(self):
        # key -> 最近几轮对话记录
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY))

    async def chat(self, user_key: str, text: str) -> str:
        if not LLM_API_KEY:
            return gentle_fallback(text)

        history = self._history[user_key]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": text})

        reply = await self._ask_llm(messages)
        if reply is None:
            reply = gentle_fallback(text)

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        return reply

    async def _ask_llm(self, messages) -> str | None:
        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.9,
            "max_tokens": 512,
        }
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{LLM_BASE_URL.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status != 200:
                        print(f"[LLM] 请求失败 status={resp.status}: {await resp.text()}")
                        return None
                    data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # 网络或接口异常时，退回温柔话术
            print(f"[LLM] 调用异常：{exc}")
            return None


class MyClient(botpy.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.brain = ChatBrain()

    async def on_ready(self):
        print(f"机器人「{self.robot.name}」已上线，温柔待机中～")

    # 群里 @ 机器人时触发
    async def on_at_message_create(self, message: Message):
        text = _clean_content(message, getattr(self.robot, "name", ""))
        key = f"{message.guild_id}:{message.channel_id}:{_user_id(message)}"
        reply = await self.brain.chat(key, text)
        await message.reply(content=reply)

    # 私聊机器人时触发
    async def on_direct_message_create(self, message: DirectMessage):
        text = _clean_content(message, getattr(self.robot, "name", ""))
        key = f"dm:{_user_id(message)}"
        reply = await self.brain.chat(key, text)
        await message.reply(content=reply)


if __name__ == "__main__":
    if not APPID or not SECRET:
        raise SystemExit(
            "缺少 APPID / SECRET：请在 config.json 中填写，或设置环境变量 QQ_APPID / QQ_SECRET。\n"
            "可先复制 config.example.json 为 config.json 再修改。"
        )
    if not LLM_API_KEY:
        print("[提示] 未配置 LLM_API_KEY，将使用内置的温柔话术回复；"
              "在 config.json 的 llm.api_key 填入 Key 即可开启真正的聊天。")

    # 开启需要监听的事件通道：群内 @ 消息 + 私聊消息
    intents = botpy.Intents(public_guild_messages=True, direct_message=True)
    client = MyClient(intents=intents)
    client.run(appid=APPID, secret=SECRET)
