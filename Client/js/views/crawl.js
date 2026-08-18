// 抓取任务: 创建(源多选/max_items) + SSE 实时进度 + 任务历史/详情/取消
import { api, toastErr, toastOk, toastWarn } from "../api.js";
import { streamEvents } from "../sse.js";
import { esc, fmtDateTime, statusBadge, pager } from "../util.js";

const PAGE_SIZE = 10;

async function loadSources() {
  try {
    const page = await api.get("/api/sources", { page_size: 100 });
    return page.items || [];
  } catch {
    return [];
  }
}

export async function crawlView(root) {
  const sources = await loadSources();
  const srcName = (id) => (sources.find((s) => s.id === id) || {}).name || id;
  const enabled = sources.filter((s) => s.enabled);

  root.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-top:0">发起抓取</div>
      <div class="field">
        <label class="label">抓取来源(留空 = 全部启用源, 共 ${enabled.length} 个)</label>
        <div class="chips" id="src-chips" style="max-height:150px;overflow-y:auto;padding:4px">
          ${[...enabled].sort((a, b) => a.id.localeCompare(b.id)).map((s) => `
            <button class="chip" data-id="${esc(s.id)}" title="${esc(s.id)}">${esc(s.name)}</button>`).join("")}
        </div>
      </div>
      <div class="field-row">
        <div class="field" style="max-width:200px">
          <label class="label">每个源数量上限</label>
          <input class="input" id="max-items" type="number" min="1" max="500" value="30">
        </div>
        <div class="field" style="align-self:flex-end">
          <button class="btn lg" id="start-crawl">开始抓取</button>
        </div>
      </div>
    </div>

    <div id="live-panel" class="card hidden" style="margin-bottom:16px"></div>

    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <div class="section-title" style="margin:0">任务历史</div>
        <div class="chips" id="f-status">
          <button class="chip active" data-st="">全部</button>
          ${["pending", "running", "completed", "failed", "cancelled"].map((st) =>
            `<button class="chip" data-st="${st}">${st}</button>`).join("")}
        </div>
      </div>
      <div id="task-list"><div class="skeleton" style="height:60px;margin-bottom:10px"></div></div>
      <div id="task-pager"></div>
    </div>`;

  const chipsBox = root.querySelector("#src-chips");
  const selected = new Set();
  chipsBox.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    c.classList.toggle("active");
    if (c.classList.contains("active")) selected.add(c.dataset.id);
    else selected.delete(c.dataset.id);
  }));

  // ---- SSE 实时进度 ----
  let ac = null;
  let runs = [];
  const upsertRun = (sid, patch) => {
    const i = runs.findIndex((r) => r.source_id === sid);
    if (i >= 0) runs[i] = { ...runs[i], ...patch };
    else runs.push({ source_id: sid, ...patch });
    renderRuns();
  };
  async function startCrawl() {
    const body = { max_items: Number(root.querySelector("#max-items").value) || 30 };
    if (selected.size) body.source_ids = [...selected];
    if (ac) { ac.abort(); ac = null; }
    try {
      const task = await api.post("/api/crawl-tasks", body);
      toastOk(`任务 #${task.id} 已创建, 开始抓取`);
      startLive(task);
      renderHistory(1);
    } catch (e) {
      if (e.status === 409) toastWarn(`任务冲突: ${e.message}`);
      else toastErr(e.message);
    }
  }
  root.querySelector("#start-crawl").addEventListener("click", startCrawl);

  function startLive(task) {
    ac = new AbortController();
    const panel = root.querySelector("#live-panel");
    panel.classList.remove("hidden");
    panel.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <div class="section-title" style="margin:0">任务 #${task.id} 实时进度 <span class="badge info"><span class="dot"></span>SSE 已连接</span></div>
        <button class="btn ghost danger sm" id="live-cancel">取消任务</button>
      </div>
      <div class="progress-row">
        <span class="stage-label">总体进度</span>
        <div class="progress-track"><div class="progress-fill" id="lp-fill" style="width:0%"></div></div>
        <span class="percent" id="lp-percent">0%</span>
      </div>
      <div class="run-strip" id="lp-runs"></div>
      <div class="event-log" id="lp-log"></div>`;
    panel.querySelector("#live-cancel").addEventListener("click", () => cancelTask(task.id));

    const fill = panel.querySelector("#lp-fill");
    const percent = panel.querySelector("#lp-percent");
    const strip = panel.querySelector("#lp-runs");
    const log = panel.querySelector("#lp-log");
    const logLine = (cls, html) => {
      const el = document.createElement("div");
      el.className = `ev ${cls}`;
      el.innerHTML = html;
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
    };
    const renderRuns = (list = runs) => {
      strip.innerHTML = list.map((r) => {
        const cls = r.status === "completed" ? "ok" : r.status === "failed" ? "err" : r.status === "running" ? "running" : "";
        return `<span class="run-dot ${cls}">${cls === "running" ? '<span class="dot"></span>' : ""}${esc(srcName(r.source_id))} ${r.success_count || 0}/${(r.success_count || 0) + (r.failed_count || 0)}</span>`;
      }).join("") || `<span class="empty-hint" style="padding:8px 0">等待源任务开始...</span>`;
    };

    streamEvents(`/api/tasks/${task.id}/events`, {
      signal: ac.signal,
      onEvent: (event, data) => {
        if (event === "run_started") {
          upsertRun(data.source_id, { status: "running" });
          logLine("", `<b>${esc(srcName(data.source_id))}</b> 开始抓取`);
          return;
        }
        if (event === "run_finished") {
          const ok = data.status === "completed";
          const ins = data.stats?.inserted || 0;
          const ex = data.stats?.existed || 0;
          const fail = data.stats?.failed || 0;
          upsertRun(data.source_id, { status: ok ? "completed" : "failed", success_count: ins, failed_count: fail });
          logLine(ok ? "ok" : "err", `<b>${esc(srcName(data.source_id))}</b> ${ok ? `完成, 新增 ${ins} 篇` : "失败"}${ex ? ` (${ex} 已存在)` : ""}${fail ? `, ${fail} 失败` : ""}`);
          return;
        }
        if (event === "task_update" || event.startsWith("task_")) {
          if (data?.progress !== undefined) {
            const p = Math.round(data.progress);
            fill.style.width = `${p}%`;
            percent.textContent = `${p}%`;
            fill.className = `progress-fill ${data.status === "completed" ? "ok" : data.status === "failed" ? "err" : data.status === "cancelled" ? "warn" : ""}`;
          }
          if (data?.runs) { runs = data.runs; renderRuns(); }
          if (data?.stage) logLine("", `<b>${esc(data.status)}</b> ${esc(data.stage)}`);
          if (data?.message) logLine("", `<b>${esc(data.status)}</b> ${esc(data.message)}`);
        }
        const TERMINAL = ["task_completed", "task_failed", "task_cancelled"];
        if (TERMINAL.includes(event)) {
          logLine(event === "task_completed" ? "ok" : "err", `** 任务 ${event.replace("task_", "")} **`);
          panel.querySelector("#live-cancel")?.remove();
          ac?.abort();
          renderHistory(state.page); // 终态后刷新历史状态/进度
        }
      },
    }).catch((e) => {
      if (e.name !== "AbortError") {
        logLine("err", `SSE 断开: ${esc(e.message)}`);
        panel.querySelector(".badge").textContent = "SSE 已断开";
      }
    });
  }

  async function cancelTask(id) {
    try {
      await api.post(`/api/crawl-tasks/${id}/cancel`, { reason: "用户取消" });
      toastWarn(`已请求取消任务 #${id}`);
    } catch (e) {
      toastErr(e.message);
    }
  }

  // ---- 历史列表 ----
  const listEl = root.querySelector("#task-list");
  const pagerEl = root.querySelector("#task-pager");
  let state = { page: 1, status: "" };

  root.querySelectorAll("#f-status .chip").forEach((c) => c.addEventListener("click", () => {
    root.querySelectorAll("#f-status .chip").forEach((x) => x.classList.remove("active"));
    c.classList.add("active");
    state.status = c.dataset.st;
    renderHistory(1);
  }));

  async function renderHistory(page) {
    state.page = page;
    listEl.innerHTML = `<div class="skeleton" style="height:60px;margin-bottom:10px"></div>`;
    try {
      const data = await api.get("/api/crawl-tasks", { status: state.status || undefined, page, page_size: PAGE_SIZE });
      if (!data.items.length) {
        listEl.innerHTML = `<div class="empty-hint">暂无抓取任务</div>`;
        pagerEl.innerHTML = "";
        return;
      }
      listEl.innerHTML = data.items.map((t) => `
        <div class="card clickable task-row" data-id="${t.id}" style="margin-bottom:10px">
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
            <b>#${t.id}</b>
            ${statusBadge(t.status)}
            <span style="color:var(--text-3);font-size:12.5px">${fmtDateTime(t.created_at)}</span>
            <span style="color:var(--text-3);font-size:12.5px">进度 ${t.progress}%</span>
            <span style="color:var(--text-3);font-size:12.5px">${(t.source_ids || []).length ? `源 ${t.source_ids.length} 个` : "全部源"} · 上限 ${t.max_items}</span>
            <span style="flex:1"></span>
            ${t.status === "running" || t.status === "pending" ? `<button class="btn ghost danger sm" data-cancel="${t.id}">取消</button>` : ""}
            <button class="btn ghost sm" data-toggle="${t.id}">详情</button>
          </div>
          <div class="task-detail hidden" data-detail="${t.id}" style="margin-top:10px;display:none"></div>
        </div>`).join("");

      listEl.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", (e) => {
        e.stopPropagation();
        cancelTask(Number(b.dataset.cancel));
      }));
      listEl.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = Number(b.dataset.toggle);
        const det = listEl.querySelector(`[data-detail="${id}"]`);
        if (!det.classList.contains("hidden")) { det.classList.add("hidden"); det.style.display = "none"; b.textContent = "详情"; return; }
        det.classList.remove("hidden");
        det.style.display = "block";
        b.textContent = "收起";
        try {
          const t = await api.get(`/api/crawl-tasks/${id}`);
          det.innerHTML = t.runs?.length ? `
            <div class="table-wrap"><table>
              <thead><tr><th>源</th><th>状态</th><th>发现链接</th><th>成功</th><th>失败</th><th>错误</th></tr></thead>
              <tbody>${t.runs.map((r) => `<tr>
                <td>${esc(srcName(r.source_id))}</td><td>${statusBadge(r.status)}</td>
                <td>${r.discovered_links}</td><td>${r.success_count}</td><td>${r.failed_count}</td>
                <td class="mono">${esc(r.error?.message || r.error?.error || "-")}</td></tr>`).join("")}
              </tbody></table></div>`
            : `<div class="empty-hint">无运行记录</div>`;
        } catch (err) {
          det.innerHTML = `<div class="empty-hint">${esc(err.message)}</div>`;
        }
      }));
      root.querySelectorAll(".task-row").forEach((row) => row.addEventListener("click", (e) => {
        if (e.target.closest("[data-cancel],[data-toggle]")) return;
        row.querySelector("[data-toggle]")?.click();
      }));
      pagerEl.innerHTML = pager(data.page, data.pages, data.total, renderHistory);
      pagerEl.querySelectorAll("[data-pg]").forEach((b) => b.addEventListener("click", () => renderHistory(Number(b.dataset.pg))));
    } catch (e) {
      toastErr(e.message);
    }
  }

  renderHistory(1);
}