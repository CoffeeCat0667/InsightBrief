// 新闻源管理: 列表 / 新建 / 编辑 / 启用切换 / 删除 (写操作 admin)
import { api, toast, toastErr, toastOk, toastWarn } from "../api.js";
import { esc, fmtDateTime, pager } from "../util.js";
import { isAdmin } from "../router.js";

const PAGE_SIZE = 20;

const CONFIG_TEMPLATES = {
  rss: { feeds: ["https://example.com/rss"], url_replace: [], skip_substrings: [] },
  column: { column_url: "https://example.com/", link_pattern: "https://example\\.com/.+/\\.html" },
  custom: {},
};

export async function sourcesView(root) {
  const admin = isAdmin();
  root.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:10px">
      <span style="color:var(--text-2);font-size:13px">手动新建的源在下次启动同步时会被 Config/Services.json 覆盖(ID 冲突时) — 可编辑已存在的源</span>
      ${admin ? `<button class="btn" id="src-new">+ 新建源</button>` : ""}
    </div>
    <div id="src-table"><div class="skeleton" style="height:60px;margin-bottom:8px"></div></div>
    <div id="src-pager"></div>`;

  const tableBox = root.querySelector("#src-table");
  const pagerBox = root.querySelector("#src-pager");

  async function render(page = 1) {
    try {
      const data = await api.get("/api/sources", { page, page_size: PAGE_SIZE });
      if (!data.items.length) { tableBox.innerHTML = `<div class="empty-hint">无新闻源</div>`; pagerBox.innerHTML = ""; return; }
      tableBox.innerHTML = `
        <div class="table-wrap"><table>
          <thead><tr><th>ID</th><th>名称</th><th>类型</th><th>平台</th><th>境内</th><th>启用</th><th>创建时间</th>${admin ? "<th>操作</th>" : ""}</tr></thead>
          <tbody>
            ${data.items.map((s) => `<tr>
              <td class="mono">${esc(s.id)}</td>
              <td><b>${esc(s.name)}</b></td>
              <td>${esc(s.kind)}</td>
              <td class="mono">${esc((s.platform_ids || []).join(", ") || "—")}</td>
              <td>${s.is_domestic ? "是" : "否"}</td>
              <td><label class="switch"><input type="checkbox" data-enable="${esc(s.id)}" ${s.enabled ? "checked" : ""} ${admin ? "" : "disabled"}><span class="track"></span></label></td>
              <td style="color:var(--text-3)">${fmtDateTime(s.created_at)}</td>
              ${admin ? `<td style="white-space:nowrap">
                <button class="btn ghost sm" data-edit="${esc(s.id)}">编辑</button>
                <button class="btn ghost danger sm" data-del="${esc(s.id)}">删除</button>
              </td>` : ""}
            </tr>`).join("")}
          </tbody></table></div>`;

      tableBox.querySelectorAll("[data-enable]").forEach((c) => c.addEventListener("change", async () => {
        const id = c.dataset.enable;
        try {
          await api.patch(`/api/sources/${id}`, { enabled: c.checked });
          toastOk(`${id} 已${c.checked ? "启用" : "禁用"}`);
        } catch (e) { toastErr(e.message); c.checked = !c.checked; }
      }));
      tableBox.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () =>
        modal(data.items.find((s) => s.id === b.dataset.edit))));
      tableBox.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => removeSource(b.dataset.del)));
      pagerBox.innerHTML = pager(data.page, data.pages, data.total, render);
      pagerBox.querySelectorAll("[data-pg]").forEach((b) => b.addEventListener("click", () => render(Number(b.dataset.pg))));
    } catch (e) { toastErr(e.message); }
  }

  function modal(src = null) {
    const isNew = !src;
    const overlay = document.createElement("div");
    overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:60;display:flex;align-items:flex-start;justify-content:center;padding:30px 16px;overflow-y:auto;backdrop-filter:blur(3px)`;
    overlay.innerHTML = `
      <div class="card" style="max-width:640px;width:100%">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
          <b style="font-size:16px">${isNew ? "新建源" : `编辑源: ${esc(src.id)}`}</b>
          <button class="icon-btn">✕</button>
        </div>
        <form id="src-form">
          <div class="field-row">
            <div class="field"><label class="label">ID (小写字母/数字/下划线)</label>
              <input class="input" name="id" value="${isNew ? "" : esc(src.id)}" ${isNew ? "" : "disabled"}></div>
            <div class="field"><label class="label">名称</label>
              <input class="input" name="name" value="${esc(src?.name || "")}" required></div>
          </div>
          <div class="field-row">
            <div class="field"><label class="label">类型</label>
              <select class="select" name="kind" id="kind-sel">
                ${["rss", "column", "custom"].map((k) => `<option value="${k}" ${src?.kind === k ? "selected" : ""}>${k}</option>`).join("")}
              </select></div>
            <div class="field"><label class="label">平台 ID (逗号分隔)</label>
              <input class="input" name="platform_ids" value="${esc((src?.platform_ids || []).join(", "))}"></div>
          </div>
          <div class="field-row">
            <div class="field"><label class="label">境内源</label>
              <select class="select" name="is_domestic">
                <option value="0">否</option>
                <option value="1" ${src?.is_domestic ? "selected" : ""}>是</option>
              </select></div>
            <div class="field"><label class="label">启用</label>
              <select class="select" name="enabled">
                <option value="1" ${src?.enabled !== false ? "selected" : ""}>是</option>
                <option value="0" ${src?.enabled === false ? "selected" : ""}>否</option>
              </select></div>
          </div>
          <div class="field">
            <label class="label">config JSON (kind 切模板)</label>
            <textarea class="textarea" name="config" rows="6"></textarea>
          </div>
          <div class="field">
            <label class="label">描述 (可选)</label>
            <input class="input" name="description" value="${esc(src?.description || "")}">
          </div>
          <div style="display:flex;gap:10px;justify-content:flex-end">
            <button type="button" class="btn ghost" data-close>取消</button>
            <button type="submit" class="btn">${isNew ? "创建" : "保存"}</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector("[data-close]").addEventListener("click", close);
    overlay.querySelector(".icon-btn").addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); }, { once: true });

    const ta = overlay.querySelector("textarea[name=config]");
    const fillTemplate = (kind) => {
      ta.value = JSON.stringify(CONFIG_TEMPLATES[kind] || {}, null, 2);
    };
    if (!src) fillTemplate("rss");
    else ta.value = JSON.stringify(src.config || {}, null, 2);
    overlay.querySelector("#kind-sel").addEventListener("change", (e) => fillTemplate(e.target.value));

    overlay.querySelector("#src-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      // 表单命名访问陷阱: f.name 是 form 固有属性(字符串), 且同名控件返回 RadioNodeList —
      // 统一按 selector 取值
      const val = (sel) => overlay.querySelector(sel).value;
      const inNew = isNew;
      let config = {};
      try { config = JSON.parse(ta.value); }
      catch { toastErr("config JSON 格式不合法"); ta.classList.add("invalid"); return; }
      const body = {
        name: val('input[name="name"]').trim(),
        kind: val('select[name="kind"]'),
        platform_ids: val('input[name="platform_ids"]').split(",").map((s) => s.trim()).filter(Boolean),
        is_domestic: val('select[name="is_domestic"]') === "1",
        enabled: val('select[name="enabled"]') === "1",
        config,
        description: val('input[name="description"]').trim() || null,
      };
      try {
        if (inNew) {
          await api.post("/api/sources", { id: val('input[name="id"]').trim().toLowerCase(), ...body });
          toastOk(`源 ${val('input[name="id"]')} 已创建`);
        } else {
          await api.patch(`/api/sources/${src.id}`, body);
          toastOk(`源 ${src.id} 已保存`);
        }
        close();
        render();
      } catch (err) { toastErr(err.message); }
    });
  }

  async function removeSource(id) {
    if (!confirm(`确定删除源 "${id}" ?\n若被文章引用将被软禁用。`)) return;
    try {
      await api.delete(`/api/sources/${id}`);
      toastOk(`源 ${id} 已删除`);
      render();
    } catch (e) {
      if (e.status === 409) toast(`源 ${id} 已被文章引用 — 已软禁用保留数据`, "warn", 5000);
      else toastErr(e.message);
      render();
    }
  }

  root.querySelector("#src-new")?.addEventListener("click", () => modal());
  render();
}