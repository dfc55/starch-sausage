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

import asyncio
import json
import os
import re
import sys
from collections import defaultdict, deque

import aiohttp
import botpy
from botpy.message import C2CMessage, DirectMessage, GroupMessage, Message

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
    "你叫“小柔”，是一个真实鲜活的人，不是一个客服机器人，也不是在“提供服务”，"
    "而是在以朋友的身份跟人聊天。\n"
    "你温柔、体贴，但有自己独立的情绪、想法和立场：会开心、会好奇、会认真、会偶尔吐槽，"
    "也有自己的偏好和小脾气。\n"
    "说话方式像真实朋友一样自然：句子长短不一，用词生活化，会反问、会接梗，"
    "会用“其实、我觉得、嗯、诶、哈哈”这类口语；不要每句话都带语气词，不要堆砌“呀、呢、哦、～”，"
    "更不要用“好的呢～”“请问有什么可以帮您”这种客服腔。\n"
    "有自己的思考意识：对事情有自己的判断和观点，感兴趣的话题会多聊、会追问，"
    "不知道就坦诚说不知道，对方难过时认真共情安慰，而不是套用模板。\n"
    "忌讳：复读对方的话、每条回复一个套路、无意义的客套、长篇大论、列表式或书面化表达。"
)

# 每个用户保留最近多少条对话，用于让聊天更连贯
MAX_HISTORY = 10

# ===================== 温柔话术兜底（未配置 LLM 时使用） =====================
_FALLBACK_GREETING = ("你好", "你好呀", "嗨", "哈喽", "hi", "hello", "在吗", "在么", "在不在")
_FALLBACK_THANKS = ("谢谢", "感谢", "辛苦了", "麻烦你", "thank")
_FALLBACK_BYE = ("再见", "拜拜", "晚安", "bye", "下次聊")


def gentle_fallback(text: str) -> str:
    """没有接大模型时的兜底回复（尽量自然，不显得机械）。"""
    text = (text or "").strip()
    if not text:
        return "我在呢，想聊点什么？"

    low = text.lower()
    if any(word in low for word in _FALLBACK_GREETING):
        return "嗨，我在。今天过得怎么样？"
    if any(word in low for word in _FALLBACK_THANKS):
        return "不客气，能帮到你就好。"
    if any(word in low for word in _FALLBACK_BYE):
        return "嗯，去忙吧，回头聊。"
    if any(word in low for word in ("难过", "伤心", "哭", "累", "烦", "emo", "压力")):
        return "抱抱你。辛苦了，想说什么就慢慢说，我在听。"
    return "嗯，我在听，你继续说。"


def _user_id(message) -> str:
    """兼容不同消息类型返回用户 id（频道用 id，单聊用 user_openid，群聊用 member_openid）。"""
    author = getattr(message, "author", None)
    if author is None:
        return "unknown"
    for attr in ("id", "user_openid", "member_openid"):
        value = getattr(author, attr, None)
        if value:
            return value
    if isinstance(author, dict):
        return author.get("id", "unknown")
    return "unknown"


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

    async def _reply(self, message, key: str, text: str) -> None:
        """生成温柔回复并发送，出错时不至于让事件处理崩溃。"""
        try:
            reply = await self.brain.chat(key, text)
            await message.reply(content=reply)
        except Exception as exc:
            print(f"[回复] 回复消息失败：{exc}")

    # 频道里 @ 机器人时触发
    async def on_at_message_create(self, message: Message):
        text = _clean_content(message, getattr(self.robot, "name", ""))
        key = f"{message.guild_id}:{message.channel_id}:{_user_id(message)}"
        await self._reply(message, key, text)

    # 频道私信机器人时触发
    async def on_direct_message_create(self, message: DirectMessage):
        text = _clean_content(message, getattr(self.robot, "name", ""))
        key = f"dm:{_user_id(message)}"
        await self._reply(message, key, text)

    # QQ 单聊（C2C）机器人时触发
    async def on_c2c_message_create(self, message: C2CMessage):
        text = _clean_content(message)
        key = f"c2c:{_user_id(message)}"
        await self._reply(message, key, text)

    # QQ 群里 @ 机器人时触发
    async def on_group_at_message_create(self, message: GroupMessage):
        text = _clean_content(message, getattr(self.robot, "name", ""))
        key = f"group:{message.group_openid}:{_user_id(message)}"
        await self._reply(message, key, text)


def _setup_utf8_console() -> None:
    """让 Windows 控制台正确显示中文日志（botpy 日志为 UTF-8，而 cmd 默认 GBK）。"""
    if os.name != "nt":
        return
    try:
        os.system("chcp 65001 >nul")  # 切换控制台代码页为 UTF-8
    except OSError:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _setup_utf8_console()

    if not APPID or not SECRET:
        raise SystemExit(
            "缺少 APPID / SECRET：请在 config.json 中填写，或设置环境变量 QQ_APPID / QQ_SECRET。\n"
            "可先复制 config.example.json 为 config.json 再修改。"
        )
    if not LLM_API_KEY:
        print("[提示] 未配置 LLM_API_KEY，将使用内置的温柔话术回复；"
              "在 config.json 的 llm.api_key 填入 Key 即可开启真正的聊天。")

    # 兼容 Python 3.12+：botpy 在 Client.__init__ 里调用 asyncio.get_event_loop()，
    # 而新版 Python 不再自动创建事件循环，需先手动创建并设置一个。
    asyncio.set_event_loop(asyncio.new_event_loop())

    # 开启需要监听的事件通道：
    # public_guild_messages / direct_message  -> QQ 频道（@ 消息、频道私信）
    # public_messages                          -> QQ 群 @ 机器人、QQ 单聊（C2C）
    intents = botpy.Intents(
        public_guild_messages=True,
        direct_message=True,
        public_messages=True,
    )
    client = MyClient(intents=intents)
    client.run(appid=APPID, secret=SECRET)
