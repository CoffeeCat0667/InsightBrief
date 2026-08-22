// 简报: briefView = 简报存档浏览; briefTasksView = 创建 + SSE + 任务历史
import { api, toastErr, toastOk, toastWarn } from "../api.js";
import { streamEvents } from "../sse.js";
import {
  CATEGORY_LABELS,
  catBadge,
  esc,
  fmtDateTime,
  pager,
  statusBadge,
} from "../util.js";

const PAGE_SIZE = 10;

async function loadSources() {
  try {
    const page = await api.get("/api/sources", { page_size: 100 });
    return page.items || [];
  } catch {
    return [];
  }
}

// ───────────────────────────────────────
// briefView: 简报存档 (仅产出物浏览/阅读)
// ───────────────────────────────────────
export async function briefView(root) {
  root.innerHTML = `
    <div class="card">
      <div class="section-title" style="margin-top:0">简报存档</div>
      <div id="b-list"><div class="skeleton" style="height:70px;margin-bottom:12px"></div></div>
      <div id="b-pager"></div>
    </div>`;

  const listEl = root.querySelector("#b-list");
  const pagerEl = root.querySelector("#b-pager");

  async function renderBriefs(page = 1) {
    listEl.innerHTML = `<div class="skeleton" style="height:70px;margin-bottom:12px"></div>`;
    try {
      const data = await api.get("/api/briefs", { page, page_size: PAGE_SIZE });
      if (!data.items.length) {
        listEl.innerHTML = `<div class="empty-hint">暂无简报</div>`;
        pagerEl.innerHTML = "";
        return;
      }
      listEl.innerHTML = data.items
        .map(
          (b) => `
        <div class="card clickable" data-brief="${b.id}" style="margin-bottom:10px">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <b style="font-size:15px">#${b.id}</b>
            ${b.category ? catBadge(b.category) : ""}
            ${b.title ? `<span style="flex:1;min-width:200px">${esc(b.title)}</span>` : `<span style="flex:1" class="empty-hint" style="padding:0">(无标题)</span>`}
            <span style="color:var(--text-3);font-size:12.5px">${b.items.length} 条</span>
            <span style="color:var(--text-3);font-size:12.5px">${fmtDateTime(b.created_at)}</span>
          </div>
          ${b.summary ? `<p class="brief-summary" style="margin-top:8px">${esc(b.summary).slice(0, 160)}${b.summary.length > 160 ? "\u2026" : ""}</p>` : ""}
        </div>`
        )
        .join("");
      listEl
        .querySelectorAll("[data-brief]")
        .forEach((el) =>
          el.addEventListener("click", () => openBrief(Number(el.dataset.brief)))
        );
      pagerEl.innerHTML = pager(data.page, data.pages, data.total, renderBriefs);
      pagerEl
        .querySelectorAll("[data-pg]")
        .forEach((b) =>
          b.addEventListener("click", () => renderBriefs(Number(b.dataset.pg)))
        );
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
    card.innerHTML = `<button class="icon-btn" style="position:absolute;right:14px;top:14px">\u2715</button><div class="skeleton" style="height:80px"></div>`;
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    card.querySelector("button").addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });
    document.addEventListener(
      "keydown",
      (e) => {
        if (e.key === "Escape") close();
      },
      { once: true }
    );
    try {
      const b = await api.get(`/api/briefs/${id}`);
      card.innerHTML = `
        <button class="icon-btn" style="position:absolute;right:14px;top:14px">\u2715</button>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
          <b style="font-size:17px">简报 #${b.id}</b>
          ${b.category ? catBadge(b.category) : ""}
          <span style="color:var(--text-3);font-size:12.5px">${fmtDateTime(b.created_at)}</span>
          ${b.stats?.by_category ? `<span style="color:var(--text-3);font-size:12.5px">${Object.entries(b.stats.by_category).map(([k, v]) => `${CATEGORY_LABELS[k] || k}: ${v}`).join(" \u00b7 ")}</span>` : ""}
        </div>
        ${b.title ? `<h2 style="font-size:20px;line-height:1.5;margin-bottom:12px">${esc(b.title)}</h2>` : ""}
        ${b.summary ? `<div class="section-title">综述</div><div class="content-block" style="margin-bottom:16px;line-height:1.9">${esc(b.summary)}</div>` : ""}
        <div class="section-title">条目 (${b.items.length})</div>
        ${b.items
          .map(
            (it) => `
          <div class="brief-item">
            <div style="display:flex;align-items:flex-start;gap:8px">
              <span class="idx">${it.seq}</span>
              <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                  <span class="brief-item-title">${esc(it.title_cn || "(未翻译标题)")}</span>
                  ${it.category ? catBadge(it.category) : ""}
                  ${it.meta?.degraded ? `<span class="badge warn">降级 ${esc(it.meta.degraded)}</span>` : ""}
                </div>
                <div style="color:var(--text-3);font-size:12.5px;margin:4px 0">${esc(it.source_name || "")} \u00b7 <a href="${esc(it.url)}" target="_blank" rel="noopener">原文</a> \u00b7 文章 #${it.article_id}</div>
                ${it.summary ? `<p class="article-summary">${esc(it.summary)}</p>` : ""}
              </div>
            </div>
          </div>`
          )
          .join("")}
        ${!b.items.length ? `<div class="empty-hint">无条目</div>` : ""}`;
      card.querySelector("button").addEventListener("click", close);
    } catch (e) {
      card.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`;
    }
  }

  renderBriefs(1);
}

// ───────────────────────────────────────
// briefTasksView: 创建 + SSE + 任务历史
// ───────────────────────────────────────
const STAGE_LABELS = {
  "\u5206\u7c7b\u4e2d": "\u5206\u7c7b",
  "\u5206\u7c7b\u5b8c\u6210": "\u5206\u7c7b",
  "\u6458\u8981\u5b8c\u6210": "\u6458\u8981/\u6807\u9898",
  "\u7efc\u8ff0\u5b8c\u6210": "\u7efc\u8ff0",
  "\u843d\u5e93": "\u843d\u5e93",
};

export async function briefTasksView(root) {
  const sources = await loadSources();
  const srcName = (id) =>
    (sources.find((s) => s.id === id) || {}).name || id;
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
        <div class="field" style="max-width:160px" id="b-max-wrap"><label class="label">最大文章数</label>
          <input class="input" type="number" id="b-max" min="1" max="500" placeholder="默认 20"></div>
        <div class="field" style="display:flex;align-items:center;gap:10px;padding-top:22px">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;white-space:nowrap;font-size:13.5px">
            <input type="checkbox" id="b-all-pending" style="width:16px;height:16px;cursor:pointer">
            生成所有未简报文章 (<span id="b-pending-count" style="font-weight:600">-</span> 篇)
          </label>
        </div>
        <div class="field" style="align-self:flex-end">
          <button class="btn lg" id="b-start-btn">开始生成</button>
        </div>
      </div>
    </div>

    <div id="b-live" class="card hidden" style="margin-bottom:16px"></div>

    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:10px;cursor:pointer" id="bstats-toggle">
        <span style="font-weight:600;font-size:14px">📊 统计信息</span>
        <span style="color:var(--text-3);font-size:12px" id="bstats-arrow">▸ 展开</span>
      </div>
      <div id="bstats-box" style="display:none;margin-top:14px;border-top:1px solid var(--border);padding-top:14px">
        <div class="chips" id="bstats-mode" style="margin-bottom:12px">
          <button class="chip active" data-mode="overview">概览</button>
          <button class="chip" data-mode="by-day">按天统计</button>
          <button class="chip" data-mode="by-source">按源统计</button>
        </div>
        <div id="bstats-overview"></div>
        <div id="bstats-by-day" style="display:none">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
            <input type="date" class="input" id="bstats-day" style="width:160px">
            <button class="btn primary sm" id="bstats-day-btn">查询</button>
          </div>
          <div id="bstats-day-result"></div>
        </div>
        <div id="bstats-by-source" style="display:none">
          <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
            <select class="select" id="bstats-src" style="min-width:180px">
              ${sources.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join("")}
            </select>
            <select class="select" id="bstats-days">
              <option value="7">近 7 天</option>
              <option value="30" selected>近 30 天</option>
              <option value="90">近 90 天</option>
            </select>
            <button class="btn primary sm" id="bstats-src-btn">查询</button>
          </div>
          <div id="bstats-src-result"></div>
        </div>
      </div>
    </div>

    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <div class="section-title" style="margin:0">简报任务历史</div>
        <div class="chips" id="bt-status">
          <button class="chip active" data-st="">全部</button>
          <button class="chip" data-st="pending">待处理</button>
          <button class="chip" data-st="running">运行中</button>
          <button class="chip" data-st="completed">已完成</button>
          <button class="chip" data-st="failed">失败</button>
          <button class="chip" data-st="cancelled">已取消</button>
        </div>
      </div>
      <div id="bt-list"><div class="skeleton" style="height:60px"></div></div>
      <div id="bt-pager"></div>
    </div>`;

  // ---- 源/分类选择 ----
  let selected = new Set();
  root
    .querySelectorAll("#b-srcs .chip")
    .forEach((c) =>
      c.addEventListener("click", () => {
        c.classList.toggle("active");
        if (c.classList.contains("active")) selected.add(c.dataset.id);
        else selected.delete(c.dataset.id);
      })
    );
  let bCat = "";
  root
    .querySelectorAll("#b-cat .chip")
    .forEach((c) =>
      c.addEventListener("click", () => {
        root
          .querySelectorAll("#b-cat .chip")
          .forEach((x) => x.classList.remove("active"));
        c.classList.add("active");
        bCat = c.dataset.cat;
      })
    );

  /* ── all_pending 开关 ── */
  const allPendingCb = root.querySelector("#b-all-pending");
  const maxWrap = root.querySelector("#b-max-wrap");
  allPendingCb.addEventListener("change", () => {
    maxWrap.style.opacity = allPendingCb.checked ? "0.4" : "1";
    maxWrap.style.pointerEvents = allPendingCb.checked ? "none" : "";
    root.querySelector("#b-max").disabled = allPendingCb.checked;
  });

  /* ── 未简报文章数量 ── */
  const pendingCountEl = root.querySelector("#b-pending-count");
  try {
    const { count } = await api.get("/api/brief-tasks/pending-count");
    pendingCountEl.textContent = count;
  } catch { pendingCountEl.textContent = "?"; }

  /* ── 统计信息 ── */
  const bstatsOverview = root.querySelector("#bstats-overview");
  const bstatsDayResult = root.querySelector("#bstats-day-result");
  const bstatsSrcResult = root.querySelector("#bstats-src-result");

  root.querySelector("#bstats-toggle").addEventListener("click", () => {
    const box = root.querySelector("#bstats-box");
    const arrow = root.querySelector("#bstats-arrow");
    if (box.style.display === "none") {
      box.style.display = "";
      arrow.textContent = "▾ 收起";
      if (!bstatsOverview.dataset.loaded) loadOverview();
    } else {
      box.style.display = "none";
      arrow.textContent = "▸ 展开";
    }
  });

  root.querySelectorAll("#bstats-mode .chip").forEach((c) =>
    c.addEventListener("click", () => {
      root.querySelectorAll("#bstats-mode .chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      root.querySelector("#bstats-overview").style.display = c.dataset.mode === "overview" ? "" : "none";
      root.querySelector("#bstats-by-day").style.display = c.dataset.mode === "by-day" ? "" : "none";
      root.querySelector("#bstats-by-source").style.display = c.dataset.mode === "by-source" ? "" : "none";
    })
  );

  async function loadOverview() {
    bstatsOverview.innerHTML = `<div class="skeleton" style="height:60px"></div>`;
    try {
      const data = await api.get("/api/brief-tasks/stats-overview");
      bstatsOverview.dataset.loaded = "1";
      const catParts = Object.entries(data.by_category).map(
        ([k, v]) => `${CATEGORY_LABELS[k] || k}: ${v}`
      );
      const srcLines = data.by_source.slice(0, 15).map(
        (r) => `<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">
          <span style="width:140px;font-size:13px;text-align:right;color:var(--text-3)">${esc(r.source_name)}</span>
          <div style="flex:1;height:16px;background:var(--bg-2);border-radius:4px;overflow:hidden">
            <div style="width:${data.by_source[0] ? (r.count / data.by_source[0].count * 100).toFixed(1) : 0}%;height:100%;background:var(--accent);border-radius:4px"></div>
          </div>
          <span style="width:40px;font-size:13px;font-weight:600">${r.count}</span>
        </div>`
      ).join("");
      bstatsOverview.innerHTML = `
        <div style="font-size:13.5px;color:var(--text-2);margin-bottom:10px">全部简报: <b>${data.total}</b> 份 · 分类: ${catParts.join(" / ")}</div>
        ${srcLines ? `<div style="font-size:13px;font-weight:600;margin-bottom:6px">Top 来源</div>${srcLines}` : ""}`;
    } catch (e) {
      bstatsOverview.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`;
    }
  }

  root.querySelector("#bstats-day-btn").addEventListener("click", async () => {
    const day = root.querySelector("#bstats-day").value;
    if (!day) { toastErr("请选择日期"); return; }
    bstatsDayResult.innerHTML = `<div class="skeleton" style="height:40px"></div>`;
    try {
      const data = await api.get("/api/brief-tasks/stats-by-day", { day });
      if (!data.length) { bstatsDayResult.innerHTML = `<div class="empty-hint">${esc(day)} 暂无数据</div>`; return; }
      const total = data.reduce((s, r) => s + r.count, 0);
      const maxCount = data[0].count;
      bstatsDayResult.innerHTML = `
        <div style="margin-bottom:6px;color:var(--text-2);font-size:13px">${esc(day)} 共 <b>${total}</b> 份，<b>${data.length}</b> 个来源</div>
        ${data.map((r) => `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="width:140px;font-size:13px;text-align:right;color:var(--text-3)">${esc(r.source_name)}</span>
            <div style="flex:1;height:18px;background:var(--bg-2);border-radius:4px;overflow:hidden">
              <div style="width:${(r.count / maxCount * 100).toFixed(1)}%;height:100%;background:var(--accent);border-radius:4px"></div>
            </div>
            <span style="width:40px;font-size:13px;font-weight:600">${r.count}</span>
          </div>`).join("")}`;
    } catch (e) { bstatsDayResult.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`; }
  });

  root.querySelector("#bstats-src-btn").addEventListener("click", async () => {
    const srcName = root.querySelector("#bstats-src").value;
    const days = root.querySelector("#bstats-days").value;
    if (!srcName) { toastErr("请选择新闻源"); return; }
    bstatsSrcResult.innerHTML = `<div class="skeleton" style="height:40px"></div>`;
    try {
      const data = await api.get("/api/brief-tasks/stats-by-source", { source_name: srcName, days: Number(days) });
      if (!data.length) { bstatsSrcResult.innerHTML = `<div class="empty-hint">近 ${days} 天暂无数据</div>`; return; }
      const total = data.reduce((s, r) => s + r.count, 0);
      const maxCount = Math.max(...data.map((r) => r.count));
      const avg = (total / data.length).toFixed(1);
      bstatsSrcResult.innerHTML = `
        <div style="margin-bottom:6px;color:var(--text-2);font-size:13px">${esc(srcName)} 近 ${days} 天共 <b>${total}</b> 份，日均 <b>${avg}</b> 份</div>
        ${data.map((r) => `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="width:85px;font-size:13px;text-align:right;color:var(--text-3)">${esc(r.day.slice(5))}</span>
            <div style="flex:1;height:18px;background:var(--bg-2);border-radius:4px;overflow:hidden">
              <div style="width:${maxCount ? (r.count / maxCount * 100).toFixed(1) : 0}%;height:100%;background:var(--accent);border-radius:4px"></div>
            </div>
            <span style="width:40px;font-size:13px;font-weight:600">${r.count}</span>
          </div>`).join("")}`;
    } catch (e) { bstatsSrcResult.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`; }
  });

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
    if (allPendingCb.checked) body.all_pending = true;
    if (ac) {
      ac.abort();
      ac = null;
    }
    try {
      const task = await api.post("/api/brief-tasks", body);
      toastOk(`简报任务 #${task.id} 已创建`);
      startLive(task);
      renderTaskHistory(1);
    } catch (e) {
      if (e.status === 409) toastWarn(`任务冲突: ${e.message}`);
      else toastErr(e.message);
    }
  }
  root
    .querySelector("#b-start-btn")
    .addEventListener("click", startBrief);

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
    box
      .querySelector("#b-cancel")
      .addEventListener("click", async () => {
        try {
          await api.post(`/api/brief-tasks/${task.id}/cancel`, {
            reason: "用户取消",
          });
          toastWarn(`已请求取消简报任务 #${task.id}`);
        } catch (e) {
          toastErr(e.message);
        }
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
        if (
          event === "brief_update" ||
          event === "brief_completed" ||
          event === "brief_failed" ||
          event === "brief_cancelled"
        ) {
          if (data?.progress !== undefined) {
            const p = Math.round(data.progress);
            fill.style.width = `${p}%`;
            percent.textContent = `${p}%`;
            fill.className = `progress-fill ${data.status === "completed" ? "ok" : data.status === "failed" ? "err" : data.status === "cancelled" ? "warn" : ""}`;
          }
          if (data?.stage)
            stageEl.textContent = STAGE_LABELS[data.stage] || data.stage;
          if (data?.message)
            logLine("", `<b>${esc(data.status)}</b> ${esc(data.message)}`);
          if (data?.stats?.by_category) {
            logLine(
              "",
              `分类分布: ${Object.entries(data.stats.by_category).map(([k, v]) => `${CATEGORY_LABELS[k] || k}:${v}`).join(" / ")}`
            );
          }
          const TERMINAL = ["completed", "failed", "cancelled"];
          if (TERMINAL.includes(data?.status)) {
            logLine(
              data.status === "completed" ? "ok" : "err",
              `** 任务 ${data.status} **`
            );
            box.querySelector("#b-cancel")?.remove();
            ac?.abort();
            renderTaskHistory(1);
          }
        }
        if (event.startsWith("brief_") && event !== "brief_update") {
          const st = event.replace("brief_", "");
          logLine(
            st === "completed" ? "ok" : "err",
            `** 任务 ${st} **`
          );
          box.querySelector("#b-cancel")?.remove();
          ac?.abort();
          renderTaskHistory(1);
        }
      },
    }).catch((e) => {
      if (e.name !== "AbortError") {
        logLine("err", `SSE 断开: ${esc(e.message)}`);
        box.querySelector(".badge").textContent = "SSE 已断开";
      }
    });
  }

  // ---- 任务历史列表 ----
  const listEl = root.querySelector("#bt-list");
  const pagerEl = root.querySelector("#bt-pager");
  let state = { page: 1, status: "" };

  root
    .querySelectorAll("#bt-status .chip")
    .forEach((c) =>
      c.addEventListener("click", () => {
        root
          .querySelectorAll("#bt-status .chip")
          .forEach((x) => x.classList.remove("active"));
        c.classList.add("active");
        state.status = c.dataset.st;
        renderTaskHistory(1);
      })
    );

  async function cancelTask(id) {
    try {
      await api.post(`/api/brief-tasks/${id}/cancel`, {
        reason: "用户取消",
      });
      toastWarn(`已请求取消简报任务 #${id}`);
    } catch (e) {
      toastErr(e.message);
    }
  }

  async function renderTaskHistory(page) {
    state.page = page;
    listEl.innerHTML = `<div class="skeleton" style="height:60px;margin-bottom:10px"></div>`;
    try {
      const data = await api.get("/api/brief-tasks", {
        status: state.status || undefined,
        page,
        page_size: PAGE_SIZE,
      });
      if (!data.items.length) {
        listEl.innerHTML = `<div class="empty-hint">暂无简报任务</div>`;
        pagerEl.innerHTML = "";
        return;
      }
      listEl.innerHTML = data.items
        .map((t) => {
          const params = t.params || {};
          const srcCount = params.source_ids?.length || 0;
          const maxItems = params.max_items || 20;
          const catLabel = params.category
            ? CATEGORY_LABELS[params.category] || params.category
            : "全部";
          return `
        <div class="card clickable task-row" data-id="${t.id}" style="margin-bottom:10px">
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
            <b>#${t.id}</b>
            ${statusBadge(t.status)}
            <span style="color:var(--text-3);font-size:12.5px">${fmtDateTime(t.created_at)}</span>
            <span style="color:var(--text-3);font-size:12.5px">进度 ${t.progress}%</span>
            <span style="color:var(--text-3);font-size:12.5px">分类: ${catLabel} \u00b7 ${srcCount ? `${srcCount} 源` : "全部源"} \u00b7 上限 ${maxItems}</span>
            ${t.stage ? `<span style="color:var(--text-3);font-size:12.5px">阶段: ${STAGE_LABELS[t.stage] || t.stage}</span>` : ""}
            <span style="flex:1"></span>
            ${t.status === "running" || t.status === "pending" ? `<button class="btn ghost danger sm" data-cancel="${t.id}">取消</button>` : ""}
            <button class="btn ghost sm" data-toggle="${t.id}">详情</button>
          </div>
          <div class="task-detail hidden" data-detail="${t.id}" style="margin-top:10px;display:none"></div>
        </div>`;
        })
        .join("");

      listEl
        .querySelectorAll("[data-cancel]")
        .forEach((b) =>
          b.addEventListener("click", (e) => {
            e.stopPropagation();
            cancelTask(Number(b.dataset.cancel));
          })
        );
      listEl
        .querySelectorAll("[data-toggle]")
        .forEach((b) =>
          b.addEventListener("click", async (e) => {
            e.stopPropagation();
            const id = Number(b.dataset.toggle);
            const det = listEl.querySelector(`[data-detail="${id}"]`);
            if (!det.classList.contains("hidden")) {
              det.classList.add("hidden");
              det.style.display = "none";
              b.textContent = "详情";
              return;
            }
            det.classList.remove("hidden");
            det.style.display = "block";
            b.textContent = "收起";
            try {
              const t = await api.get(`/api/brief-tasks/${id}`);
              let html = "";
              if (t.stats) {
                const s = t.stats;
                const parts = [];
                if (s.total != null) parts.push(`总计 ${s.total} 篇`);
                if (s.success != null) parts.push(`成功 ${s.success}`);
                if (s.degraded != null) parts.push(`降级 ${s.degraded}`);
                if (s.by_category) {
                  const catParts = Object.entries(s.by_category).map(
                    ([k, v]) => `${CATEGORY_LABELS[k] || k}${v}`
                  );
                  parts.push(catParts.join("/"));
                }
                if (s.overview_degraded)
                  parts.push(`综述降级: ${s.overview_degraded}`);
                html += `<div style="color:var(--text-2);font-size:13px;margin-bottom:8px">${parts.join(" \u00b7 ")}</div>`;
              }
              if (t.error) {
                html += `<div style="color:var(--err);font-size:13px;margin-bottom:8px">错误: ${esc(t.error.message || t.error.error || JSON.stringify(t.error))}</div>`;
              }
              if (t.briefs?.length) {
                html += `<div class="table-wrap"><table>
                  <thead><tr><th>分类</th><th>标题</th><th>条目</th><th>生成时间</th></tr></thead>
                  <tbody>${t.briefs.map((b) => `<tr>
                    <td>${b.category ? catBadge(b.category) : `<span style="color:var(--text-3)">-</span>`}</td>
                    <td>${b.title ? esc(b.title) : `<span style="color:var(--text-3)">(无标题)</span>`}</td>
                    <td>${b.items?.length ?? 0} 条</td>
                    <td style="font-size:12.5px;color:var(--text-3)">${fmtDateTime(b.generated_at || b.created_at)}</td>
                  </tr>`).join("")}</tbody></table></div>`;
              } else {
                html += `<div class="empty-hint">无产出简报</div>`;
              }
              det.innerHTML = html;
            } catch (err) {
              det.innerHTML = `<div class="empty-hint">${esc(err.message)}</div>`;
            }
          })
        );
      root.querySelectorAll(".task-row").forEach((row) =>
        row.addEventListener("click", (e) => {
          if (e.target.closest("[data-cancel],[data-toggle]")) return;
          row.querySelector("[data-toggle]")?.click();
        })
      );
      pagerEl.innerHTML = pager(data.page, data.pages, data.total, renderTaskHistory);
      pagerEl
        .querySelectorAll("[data-pg]")
        .forEach((b) =>
          b.addEventListener("click", () => renderTaskHistory(Number(b.dataset.pg)))
        );
    } catch (e) {
      toastErr(e.message);
    }
  }

  renderTaskHistory(1);
}
