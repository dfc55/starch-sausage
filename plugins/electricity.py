# -*- coding: utf-8 -*-
"""
天津财经大学宿舍电表查询插件（已接入真实接口）

接口：https://di.tjufe.edu.cn:8088/cardapp/ElecSearch.php?ec=<电表号>&xq=<校区>
无需鉴权，直接返回 JSON。注意：学校接口有频率限制，连续快速查询会偶发返回
rec=-1，本插件已做「重试 + 短时缓存」处理。

返回字段：
    rec   电表号（查询失败时为 -1）
    rsmd  剩余电量（度）
    rsfd  剩余金额（元）
    rljd  累计电量（度）
    rtzd  退补电量（度）
    rgzzt 供电状态（正常供电 / ...）

配置放在 electricity.json：
{
  "ec": "903005",   # 电表号（走廊开关箱门盖上 / 楼栋入口处一览表）
  "xq": "1"         # 校区编号
}
"""

import asyncio
import json
import os
import time

import aiohttp

_BASE_URL = "https://di.tjufe.edu.cn:8088/cardapp/ElecSearch.php"
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "electricity.json")

# 缓存：短时间内重复查询直接复用，避免触发学校接口限流
_CACHE_TTL = 30  # 秒
_cache = {"ts": 0.0, "text": None}


def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _format_result(data: dict, ec: str) -> str:
    rsmd = data.get("rsmd")
    if rsmd is None:
        return "电表查询被限流了，稍等一分钟再试哦。"

    lines = [
        f"电表 {ec} 查询结果",
        f"剩余电量：{rsmd} 度",
        f"剩余金额：{data.get('rsfd', '-')} 元",
        f"供电状态：{data.get('rgzzt', '-')}",
    ]
    rljd = data.get("rljd")
    if rljd:
        lines.append(f"累计用电：{rljd} 度")
    return "\n".join(lines)


async def _query_once(url: str) -> dict | None:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=timeout) as resp:
            text = await resp.text()
    return json.loads(text)  # 服务器 Content-Type 是 text/html，内容实为 JSON


async def query_electricity() -> str:
    cfg = _load_config()
    ec = str(cfg.get("ec", "")).strip()
    if not ec:
        return "还没设置电表号。请在 electricity.json 里填 ec（电表号）和 xq（校区编号）。"

    # 命中缓存直接返回，避免频繁打学校接口
    if _cache["text"] and (time.time() - _cache["ts"]) < _CACHE_TTL:
        return _cache["text"]

    xq = str(cfg.get("xq", "1")).strip()
    url = f"{_BASE_URL}?ec={ec}&xq={xq}"

    data = None
    for _ in range(3):
        try:
            data = await _query_once(url)
        except Exception:
            data = None
        if isinstance(data, dict) and data.get("rsmd") is not None:
            break
        await asyncio.sleep(1.5)

    if not isinstance(data, dict) or data.get("rsmd") is None:
        return "电表查询太频繁被限流了，过一分钟再试哦。"

    text = _format_result(data, ec)
    _cache["ts"] = time.time()
    _cache["text"] = text
    return text
