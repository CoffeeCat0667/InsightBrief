// 简报: 创建(分类/源/时间窗/max_items) + SSE 阶段进度 + 简报列表/阅读
import { api, toastErr, toastOk, toastWarn } from "../api.js";
import { streamEvents } from "../sse.js";
import { CATEGORY_LABELS, catBadge, esc, fmtDateTime, pager } from "../util.js";

const PAGE_SIZE = 10;

async function loadSources() {
  try {
    const page = await api.get("/api/sources", { page_size: 100 });
    return page.items || [];
  } catch {
    return [];
  }
}

export async function briefView(root) {
  const sources = await loadSources();
  const srcName = (id) => (sources.find((s) => s.id === id) || {}).name || id;
  const enabled = sources.filter((s) => s.enabled);
  const CATS = Object.entries(CATEGORY_LABELS).filter(([k]) => k !== "other");

  root.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-top:0">生成简报</div>
      <div class="field">
        <label class="label">分类</label>
        <div class="chips" id="b-cat">
          <button class="chip active" data-cat="">全部</button>
          ${CATS.map(([k, v]) => `<button class="chip" data-cat="${k}">${v}</button>`).join("")}
        </div>
      </div>
      <div class="field">
        <label class="label">来源于范围(留空 = 全部启用源, 共 ${enabled.length} 个; 简报优先取未生成过的文章)</label>
        <div class="chips" id="b-srcs" style="max-height:140px;overflow-y:auto;padding:4px">
          ${[...enabled].sort((a, b) => a.id.localeCompare(b.id)).map((s) => `
            <button class="chip" data-id="${esc(s.id)}" title="${esc(s.id)}">${esc(s.name)}</button>`).join("")}
        </div>
      </div>
      <div class="field-row">
        <div class="field"><label class="label">文章时间窗起(可选)</label>
          <input class="input" type="datetime-local" id="b-start"></div>
        <div class="field"><label class="label">文章时间窗止(可选)</label>
          <input class="input" type="datetime-local" id="b-end"></div>
        <div class="field" style="max-width:160px"><label class="label">最大文章数</label>
          <input class="input" type="number" id="b-max" min="1" max="500" placeholder="默认 20"></div>
        <div class="field" style="align-self:flex-end">
          <button class="btn lg" id="b-start-btn">开始生成</button>
        </div>
      </div>
    </div>

    <div id="b-live" class="card hidden" style="margin-bottom:16px"></div>

    <div class="card">
      <div class="section-title" style="margin-top:0">简报存档</div>
      <div id="b-list"><div class="skeleton" style="height:70px;margin-bottom:12px"></div></div>
      <div id="b-pager"></div>
    </div>`;

  let selected = new Set();
  root.querySelectorAll("#b-srcs .chip").forEach((c) => c.addEventListener("click", () => {
    c.classList.toggle("active");
    if (c.classList.contains("active")) selected.add(c.dataset.id);
    else selected.delete(c.dataset.id);
  }));
  let bCat = "";
  root.querySelectorAll("#b-cat .chip").forEach((c) => c.addEventListener("click", () => {
    root.querySelectorAll("#b-cat .chip").forEach((x) => x.classList.remove("active"));
    c.classList.add("active");
    bCat = c.dataset.cat;
  }));

  // ---- 创建 + SSE ----
  let ac = null;
  async function startBrief() {
    const body = {};
    if (bCat) body.category = bCat;
    if (selected.size) body.source_ids = [...selected];
    const start = root.querySelector("#b-start").value;
    const end = root.querySelector("#b-end").value;
    if (start) body.start_time = new Date(start).toISOString();
    if (end) body.end_time = new Date(end).toISOString();
    const max = Number(root.querySelector("#b-max").value);
    if (max) body.max_items = max;
    if (ac) { ac.abort(); ac = null; }
    try {
      const task = await api.post("/api/brief-tasks", body);
      toastOk(`简报任务 #${task.id} 已创建`);
      startLive(task);
      renderBriefs(1);
    } catch (e) {
      if (e.status === 409) toastWarn(`任务冲突: ${e.message}`);
      else toastErr(e.message);
    }
  }
  root.querySelector("#b-start-btn").addEventListener("click", startBrief);

  const STAGE_LABELS = { classify: "分类", summarize: "摘要/标题", overview: "综述", persist: "落库" };

  function startLive(task) {
    ac = new AbortController();
    const box = root.querySelector("#b-live");
    box.classList.remove("hidden");
    box.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <div class="section-title" style="margin:0">简报任务 #${task.id} <span class="badge info"><span class="dot"></span>SSE 已连接</span></div>
        <button class="btn ghost danger sm" id="b-cancel">取消任务</button>
      </div>
      <div class="progress-row">
        <span class="stage-label" id="b-stage">排队中</span>
        <div class="progress-track"><div class="progress-fill" id="b-fill" style="width:0%"></div></div>
        <span class="percent" id="b-percent">0%</span>
      </div>
      <div class="event-log" id="b-log"></div>`;
    box.querySelector("#b-cancel").addEventListener("click", async () => {
      try {
        await api.post(`/api/brief-tasks/${task.id}/cancel`, { reason: "用户取消" });
        toastWarn(`已请求取消简报任务 #${task.id}`);
      } catch (e) { toastErr(e.message); }
    });

    const stageEl = box.querySelector("#b-stage");
    const fill = box.querySelector("#b-fill");
    const percent = box.querySelector("#b-percent");
    const log = box.querySelector("#b-log");
    const logLine = (cls, html) => {
      const el = document.createElement("div");
      el.className = `ev ${cls}`;
      el.innerHTML = html;
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
    };

    streamEvents(`/api/brief-tasks/${task.id}/events`, {
      signal: ac.signal,
      onEvent: (event, data) => {
        if (event === "brief_update" || event === "brief_completed" || event === "brief_failed" || event === "brief_cancelled") {
          if (data?.progress !== undefined) {
            const p = Math.round(data.progress);
            fill.style.width = `${p}%`;
            percent.textContent = `${p}%`;
            fill.className = `progress-fill ${data.status === "completed" ? "ok" : data.status === "failed" ? "err" : data.status === "cancelled" ? "warn" : ""}`;
          }
          if (data?.stage) stageEl.textContent = STAGE_LABELS[data.stage] || data.stage;
          if (data?.message) logLine("", `<b>${esc(data.status)}</b> ${esc(data.message)}`);
          if (data?.stats?.by_category) {
            logLine("", `分类分布: ${Object.entries(data.stats.by_category).map(([k, v]) => `${CATEGORY_LABELS[k] || k}:${v}`).join(" / ")}`);
          }
        }
        if (event.startsWith("brief_") && event !== "brief_update") {
          const st = event.replace("brief_", "");
          logLine(st === "completed" ? "ok" : "err", `** 任务 ${st} **`);
          box.querySelector("#b-cancel")?.remove();
          ac?.abort();
          renderBriefs(1); // 终态后刷新存档列表
        }
      },
    }).catch((e) => {
      if (e.name !== "AbortError") {
        logLine("err", `SSE 断开: ${esc(e.message)}`);
        box.querySelector(".badge").textContent = "SSE 已断开";
      }
    });
  }

  // ---- 简报列表 ----
  const listEl = root.querySelector("#b-list");
  const pagerEl = root.querySelector("#b-pager");

  async function renderBriefs(page = 1) {
    listEl.innerHTML = `<div class="skeleton" style="height:70px;margin-bottom:12px"></div>`;
    try {
      const data = await api.get("/api/briefs", { page, page_size: PAGE_SIZE });
      if (!data.items.length) {
        listEl.innerHTML = `<div class="empty-hint">暂无简报 — 上方发起一次生成</div>`;
        pagerEl.innerHTML = "";
        return;
      }
      listEl.innerHTML = data.items.map((b) => `
        <div class="card clickable" data-brief="${b.id}" style="margin-bottom:10px">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <b style="font-size:15px">#${b.id}</b>
            ${b.category ? catBadge(b.category) : ""}
            ${b.title ? `<span style="flex:1;min-width:200px">${esc(b.title)}</span>` : `<span style="flex:1" class="empty-hint" style="padding:0">(无标题)</span>`}
            <span style="color:var(--text-3);font-size:12.5px">${b.items.length} 条</span>
            <span style="color:var(--text-3);font-size:12.5px">${fmtDateTime(b.created_at)}</span>
          </div>
          ${b.summary ? `<p class="brief-summary" style="margin-top:8px">${esc(b.summary).slice(0, 160)}${b.summary.length > 160 ? "…" : ""}</p>` : ""}
        </div>`).join("");
      listEl.querySelectorAll("[data-brief]").forEach((el) => el.addEventListener("click", () => openBrief(Number(el.dataset.brief))));
      pagerEl.innerHTML = pager(data.page, data.pages, data.total, renderBriefs);
      pagerEl.querySelectorAll("[data-pg]").forEach((b) => b.addEventListener("click", () => renderBriefs(Number(b.dataset.pg))));
    } catch (e) {
      toastErr(e.message);
    }
  }

  async function openBrief(id) {
    const overlay = document.createElement("div");
    overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:60;display:flex;align-items:flex-start;justify-content:center;padding:30px 16px;overflow-y:auto;backdrop-filter:blur(3px)`;
    const card = document.createElement("div");
    card.className = "card";
    card.style.cssText = "max-width:880px;width:100%;position:relative";
    card.innerHTML = `<button class="icon-btn" style="position:absolute;right:14px;top:14px">✕</button><div class="skeleton" style="height:80px"></div>`;
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    card.querySelector("button").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); }, { once: true });
    try {
      const b = await api.get(`/api/briefs/${id}`);
      card.innerHTML = `
        <button class="icon-btn" style="position:absolute;right:14px;top:14px">✕</button>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
          <b style="font-size:17px">简报 #${b.id}</b>
          ${b.category ? catBadge(b.category) : ""}
          <span style="color:var(--text-3);font-size:12.5px">${fmtDateTime(b.created_at)}</span>
          ${b.stats?.by_category ? `<span style="color:var(--text-3);font-size:12.5px">${Object.entries(b.stats.by_category).map(([k, v]) => `${CATEGORY_LABELS[k] || k}: ${v}`).join(" · ")}</span>` : ""}
        </div>
        ${b.title ? `<h2 style="font-size:20px;line-height:1.5;margin-bottom:12px">${esc(b.title)}</h2>` : ""}
        ${b.summary ? `<div class="section-title">综述</div><div class="content-block" style="margin-bottom:16px;line-height:1.9">${esc(b.summary)}</div>` : ""}
        <div class="section-title">条目 (${b.items.length})</div>
        ${b.items.map((it) => `
          <div class="brief-item">
            <div style="display:flex;align-items:flex-start;gap:8px">
              <span class="idx">${it.seq}</span>
              <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                  <span class="brief-item-title">${esc(it.title_cn || "(未翻译标题)")}</span>
                  ${it.category ? catBadge(it.category) : ""}
                  ${it.meta?.degraded ? `<span class="badge warn">降级 ${esc(it.meta.degraded)}</span>` : ""}
                </div>
                <div style="color:var(--text-3);font-size:12.5px;margin:4px 0">${esc(it.source_name || "")} · <a href="${esc(it.url)}" target="_blank" rel="noopener">原文</a> · 文章 #${it.article_id}</div>
                ${it.summary ? `<p class="article-summary">${esc(it.summary)}</p>` : ""}
              </div>
            </div>
          </div>`).join("")}
        ${!b.items.length ? `<div class="empty-hint">无条目</div>` : ""}`;
      card.querySelector("button").addEventListener("click", close);
    } catch (e) {
      card.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`;
    }
  }

  renderBriefs(1);
}