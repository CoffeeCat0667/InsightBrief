// 审计日志 (admin only): 筛选(action/user_id) + 分页表格 + detail JSON 展开
import { api, toastErr } from "../api.js";
import { esc, fmtDateTime, pager } from "../util.js";

const PAGE_SIZE = 20;
const ACTIONS = [
  "user.register", "user.register_failed",
  "user.login", "user.login_failed",
  "source.create", "source.update", "source.delete", "source.disable",
  "crawl_task.create", "crawl_task.cancel",
  "brief_task.create", "brief_task.cancel",
];

export async function auditView(root) {
  root.innerHTML = `
    <div class="toolbar">
      <select class="select" id="a-action" style="min-width:200px">
        <option value="">全部动作</option>
        ${ACTIONS.map((a) => `<option value="${a}">${a}</option>`).join("")}
      </select>
      <input class="input" id="a-user" type="number" placeholder="用户 ID" style="width:120px">
      <button class="btn ghost" id="a-reset">重置</button>
    </div>
    <div id="a-table"><div class="skeleton" style="height:60px;margin-bottom:8px"></div></div>
    <div id="a-pager" style="margin-top:14px"></div>`;

  const tableBox = root.querySelector("#a-table");
  const pagerBox = root.querySelector("#a-pager");
  const actionEl = root.querySelector("#a-action");
  const userEl = root.querySelector("#a-user");
  let state = { page: 1 };

  const go = (page = 1) => {
    state.page = page;
    render();
  };
  actionEl.addEventListener("change", () => go(1));
  userEl.addEventListener("input", () => go(1));
  root.querySelector("#a-reset").addEventListener("click", () => {
    actionEl.value = "";
    userEl.value = "";
    go(1);
  });

  async function render() {
    try {
      const data = await api.get("/api/audit-logs", {
        action: actionEl.value || undefined,
        user_id: userEl.value ? Number(userEl.value) : undefined,
        page: state.page,
        page_size: PAGE_SIZE,
      });
      if (!data.items.length) {
        tableBox.innerHTML = `<div class="empty-hint">无审计记录</div>`;
        pagerBox.innerHTML = "";
        return;
      }
      tableBox.innerHTML = `
        <div class="table-wrap"><table>
          <thead><tr><th>ID</th><th>时间</th><th>用户</th><th>动作</th><th>对象</th><th>IP</th><th>详情</th></tr></thead>
          <tbody>
            ${data.items.map((r) => `<tr>
              <td class="mono">${r.id}</td>
              <td style="color:var(--text-3);white-space:nowrap;font-size:12.5px">${fmtDateTime(r.created_at)}</td>
              <td>${r.user_id ?? "—"}</td>
              <td><span class="badge accent">${esc(r.action)}</span></td>
              <td class="mono">${esc(r.target_type || "—")}${r.target_id != null ? ` / ${esc(String(r.target_id))}` : ""}</td>
              <td class="mono">${esc(r.ip || "—")}</td>
              <td><button class="btn ghost sm" data-detail="${r.id}">查看</button></td>
            </tr>`).join("")}
          </tbody></table></div>`;
      tableBox.querySelectorAll("[data-detail]").forEach((b) => b.addEventListener("click", () => {
        const row = b.closest("tr");
        const next = row.nextElementSibling;
        if (next && next.classList.contains("detail-row")) {
          next.remove();
          b.textContent = "查看";
          return;
        }
        const r = data.items.find((x) => x.id === Number(b.dataset.detail));
        const json = JSON.stringify(r.detail || {}, null, 2);
        b.textContent = "收起";
        row.insertAdjacentHTML("afterend", `<tr class="detail-row"><td colspan="7"><pre class="detail-json">${esc(json)}</pre></td></tr>`);
      }));
      pagerBox.innerHTML = pager(data.page, data.pages, data.total, go);
      pagerBox.querySelectorAll("[data-pg]").forEach((b) => b.addEventListener("click", () => go(Number(b.dataset.pg))));
    } catch (e) { toastErr(e.message); }
  }
  render();
}