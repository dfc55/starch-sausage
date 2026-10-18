// QQ 机器人管理器 —— 前端逻辑
const $ = (id) => document.getElementById(id);

function toast(msg, ok = true) {
  const el = $("toast");
  el.textContent = msg;
  el.style.background = ok ? "rgba(26,30,43,.92)" : "rgba(220,38,38,.94)";
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).error || ""; } catch (e) {}
    throw new Error(detail || `请求失败（${res.status}）`);
  }
  return res.json();
}

function fmt(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ===================== 主题（亮 / 暗 / 跟随系统 / 整活） =====================
const THEME_ORDER = ["light", "dark", "auto", "fun"];
const THEME_ICON = { light: "🌙", dark: "☀️", auto: "🖥️", fun: "🎡" };
function currentTheme() { return localStorage.getItem("theme") || "light"; }
function systemDark() { return window.matchMedia("(prefers-color-scheme: dark)").matches; }

function applyTheme(mode) {
  const html = document.documentElement;
  if (mode === "dark") html.setAttribute("data-theme", "dark");
  else if (mode === "fun") html.setAttribute("data-theme", "fun");
  else if (mode === "auto") {
    html.setAttribute("data-theme", systemDark() ? "dark" : "");
    if (!window._themeListener) {
      window._themeListener = (e) => {
        if (currentTheme() === "auto") html.setAttribute("data-theme", e.matches ? "dark" : "");
      };
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", window._themeListener);
    }
  } else {
    html.removeAttribute("data-theme");
  }
  $("themeBtn").textContent = THEME_ICON[mode];
  localStorage.setItem("theme", mode);
}
$("themeBtn").addEventListener("click", () => {
  applyTheme(THEME_ORDER[(THEME_ORDER.indexOf(currentTheme()) + 1) % THEME_ORDER.length]);
});
applyTheme(currentTheme());

// ===================== 标签切换 =====================
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const panel = $("tab-" + tab.dataset.tab);
    if (panel) panel.classList.add("active");
  });
});

// ===================== 配置读写 =====================
function collect() {
  return {
    appid: $("appid").value.trim(),
    secret: $("secret").value.trim(),
    llm: { api_key: $("apiKey").value.trim(), base_url: $("baseUrl").value.trim(), model: $("model").value.trim() },
    system_prompt: $("systemPrompt").value.trim(),
    temperature: parseFloat($("temperature").value),
    max_tokens: parseInt($("maxTokens").value, 10),
    max_history: parseInt($("maxHistory").value, 10),
    response_level: parseInt($("responseLevel").value, 10),
    pricing: { input: parseFloat($("priceInput").value) || 0, output: parseFloat($("priceOutput").value) || 0 },
  };
}

const LEVEL_DESC = {
  1: "仅回复 QQ 单聊",
  2: "回复单聊 + 群里 @ 机器人",
  3: "单聊 + 群@ + 频道（推荐）",
  4: "全部（官方接口上限，等同档位 3）",
};

function fill(cfg) {
  $("appid").value = cfg.appid || "";
  $("secret").value = cfg.secret || "";
  const llm = cfg.llm || {};
  $("apiKey").value = llm.api_key || "";
  $("baseUrl").value = llm.base_url || "https://api.deepseek.com";
  $("model").value = llm.model || "deepseek-chat";
  $("systemPrompt").value = cfg.system_prompt || "";
  $("temperature").value = cfg.temperature != null ? cfg.temperature : 0.9;
  $("temperatureVal").textContent = parseFloat($("temperature").value).toFixed(1);
  $("maxTokens").value = cfg.max_tokens != null ? cfg.max_tokens : 512;
  $("maxHistory").value = cfg.max_history != null ? cfg.max_history : 10;
  $("maxHistoryVal").textContent = $("maxHistory").value;
  const lvl = cfg.response_level != null ? cfg.response_level : 3;
  $("responseLevel").value = lvl;
  $("responseLevelVal").textContent = lvl;
  $("responseLevelDesc").textContent = LEVEL_DESC[lvl] || "";
  const pr = cfg.pricing || {};
  $("priceInput").value = pr.input != null ? pr.input : 1.0;
  $("priceOutput").value = pr.output != null ? pr.output : 2.0;
  $("heroAppid").textContent = "AppID：" + (cfg.appid || "—");
}

async function loadConfig() {
  try { fill(await api("/api/config")); } catch (e) { toast("加载配置失败：" + e.message, false); }
}

$("temperature").addEventListener("input", (e) => { $("temperatureVal").textContent = parseFloat(e.target.value).toFixed(1); });
$("maxHistory").addEventListener("input", (e) => { $("maxHistoryVal").textContent = e.target.value; });
$("responseLevel").addEventListener("input", (e) => {
  $("responseLevelVal").textContent = e.target.value;
  $("responseLevelDesc").textContent = LEVEL_DESC[e.target.value] || "";
});

$("saveBtn").addEventListener("click", async () => {
  const cfg = collect();
  if (!cfg.appid || !cfg.secret) { toast("AppID 与 AppSecret 不能为空", false); return; }
  $("saveBtn").disabled = true;
  $("saveBtn").textContent = "保存中…";
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify(cfg) });
    toast("已保存到 config.json");
    loadStats(); loadStatus();
  } catch (e) { toast("保存失败：" + e.message, false); }
  finally { $("saveBtn").disabled = false; $("saveBtn").textContent = "保存配置"; }
});

// ===================== 状态 / 统计 =====================
function setStatus(running) {
  const badge = $("heroBadge");
  badge.className = "hero-badge " + (running ? "on" : "");
  badge.textContent = running ? "在线" : "离线";
  $("startBtn").disabled = running;
  $("stopBtn").disabled = !running;
}
async function loadStatus() {
  try { setStatus(!!(await api("/api/status")).running); } catch (e) { setStatus(false); }
}

async function loadStats() {
  try {
    const s = await api("/api/stats");
    const today = (s.daily || {})[todayStr()] || {};
    $("statMsg").textContent = fmt(today.messages);
    $("statCalls").textContent = fmt(today.llm_calls);
    $("statCost").textContent = "¥" + (s.cost_today ?? 0);
    $("statToken").textContent = fmt((today.input_tokens || 0) + (today.output_tokens || 0));

    $("dTotalCost").textContent = "¥" + (s.cost_total ?? 0);
    $("dTotalTokens").textContent = fmt((s.input_tokens || 0) + (s.output_tokens || 0));
    $("dIn").textContent = fmt(s.input_tokens);
    $("dOut").textContent = fmt(s.output_tokens);
    renderDaily(s.daily || {}, s);
  } catch (e) {}
}

function renderDaily(daily, s) {
  const box = $("dailyList");
  const pIn = parseFloat($("priceInput").value) || 0;
  const pOut = parseFloat($("priceOutput").value) || 0;
  const days = Object.keys(daily).sort().slice(-7);
  if (!days.length) { box.innerHTML = '<div class="empty">暂无数据</div>'; return; }
  box.innerHTML = "";
  days.forEach((day) => {
    const d = daily[day] || {};
    const cost = (d.input_tokens || 0) / 1e6 * pIn + (d.output_tokens || 0) / 1e6 * pOut;
    const row = document.createElement("div");
    row.className = "daily-row";
    row.innerHTML = `<span>${day}</span><span>${fmt(d.messages)} 消息 · ${fmt((d.input_tokens||0)+(d.output_tokens||0))} token</span><b>¥${cost.toFixed(4)}</b>`;
    box.appendChild(row);
  });
}

$("startBtn").addEventListener("click", async () => {
  $("startBtn").disabled = true;
  try { const r = await api("/api/bot/start", { method: "POST" }); toast(r.msg || "已启动"); setTimeout(loadStatus, 1500); }
  catch (e) { toast("启动失败：" + e.message, false); } finally { $("startBtn").disabled = false; }
});
$("stopBtn").addEventListener("click", async () => {
  $("stopBtn").disabled = true;
  try { await api("/api/bot/stop", { method: "POST" }); toast("已停止"); setTimeout(loadStatus, 800); }
  catch (e) { toast("停止失败：" + e.message, false); } finally { $("stopBtn").disabled = false; }
});

// ===================== 人设预设 =====================
const BUILTIN_IDS = ["xiaorou", "whale", "cool", "joker"];
let customPresets = [];

async function loadPresets() {
  try {
    const all = (await api("/api/presets")).presets || [];
    customPresets = all.filter((p) => !BUILTIN_IDS.includes(p.id));
    renderPresets(all);
  } catch (e) {}
}
function renderPresets(all) {
  const box = $("presetList");
  box.innerHTML = "";
  all.forEach((p) => {
    const isCustom = !BUILTIN_IDS.includes(p.id);
    const el = document.createElement("button");
    el.className = "preset";
    const name = document.createElement("div");
    name.className = "preset-name";
    name.textContent = p.name;
    if (isCustom) {
      const del = document.createElement("span");
      del.className = "preset-del";
      del.textContent = "✕";
      del.addEventListener("click", (e) => { e.stopPropagation(); deletePreset(p.id); });
      name.appendChild(del);
    }
    const tag = document.createElement("div");
    tag.className = "preset-tag";
    tag.textContent = p.tag;
    el.appendChild(name);
    el.appendChild(tag);
    el.addEventListener("click", () => { $("systemPrompt").value = p.prompt; toast(`已套用「${p.name}」，记得保存`); });
    box.appendChild(el);
  });
}
async function deletePreset(id) {
  customPresets = customPresets.filter((p) => p.id !== id);
  await saveCustomPresets();
}
async function saveCustomPresets() {
  try {
    await api("/api/presets", { method: "POST", body: JSON.stringify({ presets: customPresets }) });
    loadPresets();
    toast("人设已更新");
  } catch (e) { toast("保存失败：" + e.message, false); }
}
$("newPresetBtn").addEventListener("click", () => { $("presetForm").style.display = "block"; $("newPresetBtn").style.display = "none"; });
$("cancelPresetBtn").addEventListener("click", () => { $("presetForm").style.display = "none"; $("newPresetBtn").style.display = "block"; });
$("savePresetBtn").addEventListener("click", async () => {
  const name = $("presetName").value.trim();
  const prompt = $("presetPrompt").value.trim();
  if (!name || !prompt) { toast("名字和提示词都要填", false); return; }
  customPresets.push({ id: "c" + Date.now(), name, tag: $("presetTag").value.trim() || "自定义", prompt });
  await saveCustomPresets();
  $("presetName").value = $("presetTag").value = $("presetPrompt").value = "";
  $("presetForm").style.display = "none";
  $("newPresetBtn").style.display = "block";
});

// ===================== 记忆 =====================
async function loadMemory() {
  try {
    const mem = await api("/api/memory");
    const keys = Object.keys(mem);
    $("memCount").textContent = keys.length + " 个会话";
    const box = $("memoryList");
    box.innerHTML = "";
    if (!keys.length) { box.innerHTML = '<div class="empty">暂无记忆</div>'; return; }
    keys.forEach((k) => {
      const msgs = mem[k] || [];
      const lastUser = [...msgs].reverse().find((m) => m.role === "user");
      const lastBot = [...msgs].reverse().find((m) => m.role === "assistant");
      const el = document.createElement("div");
      el.className = "mem-item";
      el.innerHTML = `<div class="mem-key">${k}</div>
        <div class="mem-msg"><b>👤</b> ${(lastUser?.content || "—").slice(0, 40)}</div>
        <div class="mem-msg"><b>🤖</b> ${(lastBot?.content || "—").slice(0, 40)}</div>`;
      box.appendChild(el);
    });
  } catch (e) {}
}
$("clearMemoryBtn").addEventListener("click", async () => {
  if (!confirm("确定清空全部记忆？")) return;
  try { await api("/api/memory/clear", { method: "POST" }); toast("已清空"); loadMemory(); }
  catch (e) { toast("清空失败：" + e.message, false); }
});
$("exportBtn").addEventListener("click", async () => {
  try {
    const [mem, stats, quotes, feedback] = await Promise.all([
      api("/api/memory"), api("/api/stats"), api("/api/quotes"), api("/api/feedback"),
    ]);
    const data = { exported_at: new Date().toISOString(), memory: mem, stats, quotes: quotes.items, feedback: feedback.items };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `qq-bot-export-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已导出");
  } catch (e) { toast("导出失败：" + e.message, false); }
});

// ===================== 语录 =====================
async function loadQuotes() {
  try {
    const items = (await api("/api/quotes")).items || [];
    const box = $("quoteList");
    box.innerHTML = "";
    if (!items.length) { box.innerHTML = '<div class="empty">还没有金句，快收录一条</div>'; return; }
    items.forEach((q, i) => {
      const el = document.createElement("div");
      el.className = "quote-item";
      el.innerHTML = `<div class="quote-text">${q.text}</div><div class="quote-time">${q.time}</div><button class="del" title="删除">✕</button>`;
      el.querySelector(".del").addEventListener("click", async () => {
        try { await api("/api/quotes/delete", { method: "POST", body: JSON.stringify({ index: i }) }); loadQuotes(); }
        catch (e) { toast("删除失败：" + e.message, false); }
      });
      box.appendChild(el);
    });
  } catch (e) {}
}
$("addQuoteBtn").addEventListener("click", async () => {
  const v = $("quoteInput").value.trim();
  if (!v) { toast("先写点内容", false); return; }
  try { await api("/api/quotes", { method: "POST", body: JSON.stringify({ text: v }) }); $("quoteInput").value = ""; toast("已收录"); loadQuotes(); }
  catch (e) { toast("收录失败：" + e.message, false); }
});

// ===================== 意见箱 =====================
async function loadFeedback() {
  try {
    const items = (await api("/api/feedback")).items || [];
    const box = $("feedbackList");
    box.innerHTML = "";
    if (!items.length) { box.innerHTML = '<div class="empty">暂无反馈</div>'; return; }
    items.slice().reverse().forEach((f) => {
      const el = document.createElement("div");
      el.className = "quote-item";
      el.innerHTML = `<div class="quote-text">${f.text}</div><div class="quote-time">${f.time}</div>`;
      box.appendChild(el);
    });
  } catch (e) {}
}
$("addFeedbackBtn").addEventListener("click", async () => {
  const v = $("feedbackInput").value.trim();
  if (!v) { toast("先写点内容", false); return; }
  try { await api("/api/feedback", { method: "POST", body: JSON.stringify({ text: v }) }); $("feedbackInput").value = ""; toast("已提交，谢谢反馈"); loadFeedback(); }
  catch (e) { toast("提交失败：" + e.message, false); }
});

// ===================== 屏蔽名单 =====================
let blocklist = [];
async function loadBlocklist() {
  try { blocklist = (await api("/api/blocklist")).blocked || []; renderBlocklist(); } catch (e) {}
}
function renderBlocklist() {
  const box = $("blockList");
  box.innerHTML = "";
  if (!blocklist.length) { box.innerHTML = '<div class="empty">暂无屏蔽用户</div>'; return; }
  blocklist.forEach((id) => {
    const el = document.createElement("div");
    el.className = "block-item";
    el.innerHTML = `<span>${id}</span><button class="del" title="移除">✕</button>`;
    el.querySelector(".del").addEventListener("click", () => { blocklist = blocklist.filter((x) => x !== id); saveBlocklist(); });
    box.appendChild(el);
  });
}
async function saveBlocklist() {
  try { await api("/api/blocklist", { method: "POST", body: JSON.stringify({ blocked: blocklist }) }); renderBlocklist(); toast("已更新"); }
  catch (e) { toast("保存失败：" + e.message, false); }
}
$("addBlockBtn").addEventListener("click", () => {
  const v = $("blockInput").value.trim();
  if (!v) { toast("请输入 ID", false); return; }
  if (blocklist.includes(v)) { toast("已在名单中", false); return; }
  blocklist.push(v);
  $("blockInput").value = "";
  saveBlocklist();
});

// ===================== 初始化 =====================
loadConfig().then(() => loadStats());
loadStatus();
loadStats();
loadPresets();
loadMemory();
loadQuotes();
loadFeedback();
loadBlocklist();
