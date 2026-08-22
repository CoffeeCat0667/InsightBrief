// 抓取任务: 创建(源多选/max_items/国内占比) + SSE 实时进度 + 任务历史/详情/取消
import { api, toastErr, toastOk, toastWarn } from "../api.js";
import { isAdmin } from "../router.js";
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
        <div class="field" style="max-width:240px">
          <label class="label">国内源新闻数最大占比 (%)</label>
          <input class="input" id="domestic-max-ratio" type="number" min="0" max="100" step="1" value="100">
          <small class="help">按成功新闻数计算，100 = 不限制</small>
        </div>
        <div class="field" style="align-self:flex-end">
          <button class="btn lg" id="start-crawl">开始抓取</button>
        </div>
      </div>
    </div>

    ${isAdmin() ? `
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-top:0">定时任务</div>
      <div class="field-row">
        <div class="field" style="max-width:180px">
          <label class="label">每隔多少小时</label>
          <input class="input" id="schedule-interval" type="number" min="1" max="720" value="6">
        </div>
        <div class="field" style="max-width:180px">
          <label class="label">最多执行次数</label>
          <input class="input" id="schedule-max-runs" type="number" min="0" max="100000" value="0">
          <small class="help">0 = 无限循环</small>
        </div>
        <div class="field" style="align-self:flex-end">
          <label class="toggle-inline"><span class="switch"><input type="checkbox" id="schedule-brief"><span class="track"></span></span><span>抓取结束后生成简报</span></label>
        </div>
        <div class="field" style="align-self:flex-end">
          <button class="btn" id="create-schedule">创建并启用</button>
        </div>
        <span id="schedule-empty" class="schedule-empty">暂无定时任务</span>
      </div>
      <div id="schedule-list"><div class="skeleton" style="height:50px"></div></div>
    </div>` : ""}

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

  async function loadSchedules() {
    const list = root.querySelector("#schedule-list");
    const empty = root.querySelector("#schedule-empty");
    try {
      const data = await api.get("/api/crawl-schedules", { page: 1, page_size: 100 });
      if (!data.items.length) {
        empty.classList.remove("hidden");
        list.innerHTML = "";
        return;
      }
      empty.classList.add("hidden");
      list.innerHTML = data.items.map((s) => `
        <div class="schedule-row" data-schedule="${s.id}">
          <div><b>#${s.id}</b> ${s.enabled ? '<span class="badge ok">运行中</span>' : '<span class="badge mute">已暂停</span>'}</div>
          <div class="schedule-meta">每 ${s.interval_hours} 小时 · ${s.max_runs ? `${s.run_count}/${s.max_runs} 次` : `${s.run_count} 次/无限`} · 国内 ≤ ${s.domestic_max_ratio}% · 简报 ${s.generate_brief ? "开" : "关"}</div>
          <div class="schedule-meta">下次：${fmtDateTime(s.next_run_at)}${s.last_error ? ` · ${esc(s.last_error)}` : ""}</div>
          <div class="schedule-actions">
            <button class="btn ghost sm" data-run-now="${s.id}">立即执行</button>
            <button class="btn ghost sm" data-toggle-schedule="${s.id}">${s.enabled ? "暂停" : "启用"}</button>
            <button class="btn ghost danger sm" data-delete-schedule="${s.id}">删除</button>
          </div>
        </div>`).join("");
      list.querySelectorAll("[data-run-now]").forEach((b) => b.addEventListener("click", async (e) => {
        e.stopPropagation();
        try { const result = await api.post(`/api/crawl-schedules/${b.dataset.runNow}/run-now`); toastOk(`已创建抓取任务 #${result.crawl_task_id}`); renderHistory(1); }
        catch (err) { toastErr(err.message); }
      }));
      list.querySelectorAll("[data-toggle-schedule]").forEach((b) => b.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = b.dataset.toggleSchedule;
        const row = b.closest(".schedule-row");
        const enabled = row.querySelector(".badge.ok") !== null;
        try { await api.post(`/api/crawl-schedules/${id}/${enabled ? "disable" : "enable"}`); loadSchedules(); }
        catch (err) { toastErr(err.message); }
      }));
      list.querySelectorAll("[data-delete-schedule]").forEach((b) => b.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!window.confirm("确定删除此定时任务？历史抓取和简报不会删除。")) return;
        try { await api.delete(`/api/crawl-schedules/${b.dataset.deleteSchedule}`); loadSchedules(); }
        catch (err) { toastErr(err.message); }
      }));
    } catch (e) { toastErr(e.message); }
  }

  async function createSchedule() {
    const interval = Number(root.querySelector("#schedule-interval").value);
    const maxRuns = Number(root.querySelector("#schedule-max-runs").value);
    if (!Number.isInteger(interval) || interval < 1 || interval > 720) return toastWarn("执行间隔必须是 1-720 小时的整数");
    if (!Number.isInteger(maxRuns) || maxRuns < 0 || maxRuns > 100000) return toastWarn("最多执行次数必须是 0-100000 的整数");
    const body = {
      interval_hours: interval,
      max_runs: maxRuns,
      max_items: Number(root.querySelector("#max-items").value) || 30,
      domestic_max_ratio: Number(root.querySelector("#domestic-max-ratio").value),
      generate_brief: root.querySelector("#schedule-brief").checked,
    };
    if (selected.size) body.source_ids = [...selected];
    try { await api.post("/api/crawl-schedules", body); toastOk("定时任务已创建，将立即执行首次抓取"); loadSchedules(); }
    catch (e) { toastErr(e.message); }
  }
  if (isAdmin()) {
    root.querySelector("#create-schedule").addEventListener("click", createSchedule);
    loadSchedules();
  }

  // ---- SSE 实时进度 ----
  let ac = null;
  async function startCrawl() {
    const maxItems = Number(root.querySelector("#max-items").value);
    const domesticMaxRatio = Number(root.querySelector("#domestic-max-ratio").value);
    if (!Number.isInteger(maxItems) || maxItems < 1 || maxItems > 500) {
      toastWarn("每个源数量上限必须是 1-500 的整数");
      return;
    }
    if (!Number.isInteger(domesticMaxRatio) || domesticMaxRatio < 0 || domesticMaxRatio > 100) {
      toastWarn("国内源新闻数最大占比必须是 0-100 的整数");
      return;
    }
    const body = { max_items: maxItems, domestic_max_ratio: domesticMaxRatio };
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
      <div class="now-line" id="lp-now"></div>
      <div class="quota-line" id="lp-quota">国内源占比限制：${task.domestic_max_ratio ?? 100}%</div>
      <div class="progress-row">
        <span class="stage-label">当前源文章进度</span>
        <div class="progress-track"><div class="progress-fill" id="lp-fill" style="width:0%"></div></div>
        <span class="percent" id="lp-percent">0/0</span>
      </div>
      <div class="progress-row">
        <span class="stage-label">源进度</span>
        <div class="progress-track"><div class="progress-fill" id="lp-fill-src" style="width:0%"></div></div>
        <span class="percent" id="lp-percent-src">0%</span>
      </div>
      <div class="run-strip" id="lp-runs"></div>
      <div class="event-log" id="lp-log"></div>`;
    panel.querySelector("#live-cancel").addEventListener("click", () => cancelTask(task.id));

    const fill = panel.querySelector("#lp-fill");
    const percent = panel.querySelector("#lp-percent");
    const fillSrc = panel.querySelector("#lp-fill-src");
    const percentSrc = panel.querySelector("#lp-percent-src");
    const nowLine = panel.querySelector("#lp-now");
    const quotaLine = panel.querySelector("#lp-quota");
    const strip = panel.querySelector("#lp-runs");
    const log = panel.querySelector("#lp-log");
    const setNow = (html) => { nowLine.innerHTML = html; };
    const logLine = (cls, html) => {
      const el = document.createElement("div");
      el.className = `ev ${cls}`;
      el.innerHTML = html;
      log.appendChild(el);
      log.scrollTop = log.scrollHeight;
    };
    const renderRuns = (list = runs) => {
      strip.innerHTML = list.map((r) => {
        const cls = r.status === "completed" ? "ok" : r.status === "failed" ? "err" : r.status === "running" ? "running" : r.status === "skipped" ? "skipped" : "";
        const total = (r.success_count || 0) + (r.existed_count || 0) + (r.failed_count || 0);
        const label = r.status === "skipped" ? "已跳过" : `${r.success_count || 0}/${total}`;
        return `<span class="run-dot ${cls}">${cls === "running" ? '<span class="dot"></span>' : ""}${esc(srcName(r.source_id))} ${label}</span>`;
      }).join("") || `<span class="empty-hint" style="padding:8px 0">等待源任务开始...</span>`;
    };
    let runs = [];
    const upsertRun = (sid, patch) => {
      const i = runs.findIndex((r) => r.source_id === sid);
      if (i >= 0) runs[i] = { ...runs[i], ...patch };
      else runs.push({ source_id: sid, ...patch });
      renderRuns();
    };

    streamEvents(`/api/tasks/${task.id}/events`, {
      signal: ac.signal,
      onEvent: (event, data) => {
        if (event === "run_started") {
          upsertRun(data.source_id, { status: "running" });
          const seq = (data.index ?? 0) + 1;
          const tot = data.total_sources ?? "?";
          setNow(`<b>${esc(srcName(data.source_id))}</b> 开始抓取 <span style="color:var(--text-3)">(第 ${seq}/${tot} 源)</span>`);
          fill.style.width = "0%";
          percent.textContent = `0/${data.total ?? 0}`;
          logLine("", `<b>${esc(srcName(data.source_id))}</b> 开始抓取 (第 ${seq}/${tot} 源)`);
          return;
        }
        if (event === "run_progress") {
          const pct = data.total ? Math.round((data.done / data.total) * 100) : 100;
          fill.style.width = `${pct}%`;
          percent.textContent = `${data.done}/${data.total}`;
          const seq = (data.index ?? 0) + 1;
          const tot = data.total_sources ?? "?";
          setNow(`正在抓取 <b>${esc(srcName(data.source_id))}</b>: <b>${data.done}/${data.total}</b> 篇 <span style="color:var(--text-3)">(第 ${seq}/${tot} 源)</span>`);
          return;
        }
        if (event === "run_finished") {
          const skipped = data.status === "skipped";
          const ok = data.status === "completed";
          const ins = data.stats?.inserted || 0;
          const ex = data.stats?.existed || 0;
          const fail = data.stats?.failed || 0;
          upsertRun(data.source_id, { status: skipped ? "skipped" : ok ? "completed" : "failed", success_count: ins, failed_count: fail });
          if (data.quota) {
            const q = data.quota;
            quotaLine.textContent = `国内源占比：${q.domestic_count || 0}/${(q.domestic_count || 0) + (q.foreign_count || 0)} = ${q.actual_domestic_ratio || 0}% · 上限 ${task.domestic_max_ratio ?? 100}%`;
          }
          fill.style.width = "100%";
          percent.textContent = skipped ? "跳过" : "完成";
          const message = skipped ? "跳过（国内源配额已用尽）" : ok ? `完成, 新增 ${ins} 篇` : "失败";
          setNow(`<b>${esc(srcName(data.source_id))}</b> ${message}${ex ? ` (${ex} 已存在)` : ""}${fail ? `, ${fail} 失败` : ""}`);
          logLine(skipped ? "" : ok ? "ok" : "err", `<b>${esc(srcName(data.source_id))}</b> ${message}${ex ? ` (${ex} 已存在)` : ""}${fail ? `, ${fail} 失败` : ""}`);
          return;
        }
        if (event === "task_update" || event.startsWith("task_")) {
          if (data?.progress !== undefined) {
            const p = Math.round(data.progress);
            fillSrc.style.width = `${p}%`;
            percentSrc.textContent = `${p}%`;
            fillSrc.className = `progress-fill ${data.status === "completed" ? "ok" : data.status === "failed" ? "err" : data.status === "cancelled" ? "warn" : ""}`;
          }
          if (data?.runs) { runs = data.runs; renderRuns(); }
          if (data?.stats?.quota) {
            const q = data.stats.quota;
            quotaLine.textContent = `国内源占比：${q.domestic_count || 0}/${(q.domestic_count || 0) + (q.foreign_count || 0)} = ${q.actual_domestic_ratio || 0}% · 上限 ${task.domestic_max_ratio ?? 100}%`;
          }
          if (data?.stage) {
            const m = data.stage.match(/\((\d+)\/(\d+)\)$/);
            if (m) {
              percentSrc.textContent = `${Math.round((Number(m[1]) / Number(m[2])) * 100)}%`;
              fillSrc.style.width = `${Math.round((Number(m[1]) / Number(m[2])) * 100)}%`;
            }
            setNow(esc(data.stage));
            logLine("", `<b>${esc(data.status)}</b> ${esc(data.stage)}`);
          }
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
            <span style="color:var(--text-3);font-size:12.5px">${(t.source_ids || []).length ? `源 ${t.source_ids.length} 个` : "全部源"} · 上限 ${t.max_items} · 国内 ≤ ${t.domestic_max_ratio ?? 100}%</span>
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