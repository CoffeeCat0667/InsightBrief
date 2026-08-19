// 管理面板: 注册开关 / 用户管理 / LLM 配置 / 非管理员可见选项卡 (admin only)
import { api, toastErr, toastOk } from "../api.js";
import { esc, fmtDateTime } from "../util.js";

const TAB_LABELS = {
  articles: "文章",
  brief: "简报",
  crawl: "抓取任务",
  sources: "新闻源",
};

export async function adminView(root) {
  root.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-top:0">注册入口</div>
      <label class="toggle-inline">
        <span class="switch"><input type="checkbox" id="reg-enabled"><span class="track"></span></span>
        <span>允许公开注册</span>
      </label>
      <button class="btn sm" id="reg-save" style="margin-left:10px">保存</button>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-top:0">LLM 配置</div>
      <div class="field"><label class="label">base_url</label>
        <input class="input" id="llm-base"></div>
      <div class="field"><label class="label">api_key</label>
        <input class="input" id="llm-key" type="password" autocomplete="off"></div>
      <div class="field"><label class="label">model_id</label>
        <input class="input" id="llm-model"></div>
      <div style="display:flex;gap:10px;align-items:center">
        <button class="btn" id="llm-save">测试并保存</button>
        <span id="llm-status" style="color:var(--text-3);font-size:12.5px"></span>
      </div>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div class="section-title" style="margin-top:0">非管理员可见选项卡</div>
      <div class="chips" id="tab-chips">
        ${Object.entries(TAB_LABELS).map(([k, v]) =>
          `<button class="chip active" data-tab="${k}">${v}</button>`).join("")}
      </div>
      <div style="margin-top:10px"><button class="btn sm" id="tabs-save">保存</button></div>
    </div>

    <div class="card">
      <div class="section-title" style="margin-top:0">用户管理</div>
      <div id="admin-users"><div class="skeleton" style="height:60px"></div></div>
    </div>`;

  // ---- 注册开关 ----
  const regEnabled = root.querySelector("#reg-enabled");
  try { const r = await api.get("/api/admin/registration"); regEnabled.checked = r.enabled !== false; } catch { /* */ }
  root.querySelector("#reg-save").addEventListener("click", async () => {
    try { await api.put("/api/admin/registration", { enabled: regEnabled.checked }); toastOk("注册入口已更新"); }
    catch (e) { toastErr(e.message); }
  });

  // ---- LLM 配置 ----
  const llmBase = root.querySelector("#llm-base");
  const llmKey = root.querySelector("#llm-key");
  const llmModel = root.querySelector("#llm-model");
  const llmStatus = root.querySelector("#llm-status");
  try {
    const c = await api.get("/api/admin/llm");
    llmBase.value = c.base_url || "";
    llmKey.value = c.api_key || "";
    llmModel.value = c.model_id || "";
  } catch (e) { toastErr(e.message); }
  root.querySelector("#llm-save").addEventListener("click", async () => {
    if (!llmBase.value.trim() || !llmKey.value.trim() || !llmModel.value.trim()) {
      llmStatus.textContent = "三个字段均不能为空";
      return;
    }
    llmStatus.textContent = "连通性检查中...";
    try {
      const c = await api.put("/api/admin/llm", {
        base_url: llmBase.value.trim(),
        api_key: llmKey.value.trim(),
        model_id: llmModel.value.trim(),
      });
      llmBase.value = c.base_url; llmKey.value = c.api_key; llmModel.value = c.model_id;
      llmStatus.textContent = "✓ 模型可用, 已写入并保存";
      toastOk("LLM 配置已更新");
    } catch (e) {
      llmStatus.textContent = `✗ 未保存: ${e.message}`;
      toastErr(e.message);
    }
  });

  // ---- 非管理员选项卡 ----
  const chipBox = root.querySelector("#tab-chips");
  const chosen = new Set(Object.keys(TAB_LABELS));
  chipBox.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    c.classList.toggle("active");
    if (c.classList.contains("active")) chosen.add(c.dataset.tab);
    else chosen.delete(c.dataset.tab);
  }));
  try {
    const t = await api.get("/api/admin/tabs");
    const enabled = new Set(t.tabs || []);
    chipBox.querySelectorAll(".chip").forEach((c) => {
      const on = enabled.has(c.dataset.tab);
      c.classList.toggle("active", on);
      if (on) chosen.add(c.dataset.tab); else chosen.delete(c.dataset.tab);
    });
  } catch (e) { toastErr(e.message); }
  root.querySelector("#tabs-save").addEventListener("click", async () => {
    if (!chosen.size) { toastErr("至少保留一个可见选项卡"); return; }
    try { await api.put("/api/admin/tabs", { tabs: [...chosen] }); toastOk("选项卡可见性已更新"); }
    catch (e) { toastErr(e.message); }
  });

  // ---- 用户管理 ----
  await renderUsers(root);
}

async function renderUsers(root) {
  const box = root.querySelector("#admin-users");
  let users = [];
  try { users = await api.get("/api/admin/users"); } catch (e) { box.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`; return; }
  if (!users.length) { box.innerHTML = `<div class="empty-hint">暂无用户</div>`; return; }
  box.innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr><th>ID</th><th>用户名</th><th>邮箱</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
      <tbody>${users.map((u) => `<tr>
        <td>${u.id}</td>
        <td><b>${esc(u.username)}</b></td>
        <td>${esc(u.email || "—")}</td>
        <td>${esc(u.role_code || "—")}</td>
        <td>${u.is_active ? "启用" : "禁用"}</td>
        <td style="color:var(--text-3)">${fmtDateTime(u.created_at)}</td>
        <td><button class="btn ghost sm" data-edit-user="${u.id}">编辑</button></td>
      </tr>`).join("")}</tbody>
    </table></div>`;
  box.querySelectorAll("[data-edit-user]").forEach((b) => b.addEventListener("click", () => {
    const u = users.find((x) => x.id === Number(b.dataset.editUser));
    editUserModal(root, u, renderUsers);
  }));
}

function editUserModal(root, user, onDone) {
  const overlay = document.createElement("div");
  overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:60;display:flex;align-items:flex-start;justify-content:center;padding:30px 16px;overflow-y:auto`;
  overlay.innerHTML = `
    <div class="card" style="max-width:460px;width:100%">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <b style="font-size:16px">编辑用户: ${esc(user.username)}</b>
        <button class="icon-btn">✕</button>
      </div>
      <form id="user-edit-form">
        <div class="field"><label class="label">用户名</label>
          <input class="input" id="edit-username" value="${esc(user.username)}"></div>
        <div class="field"><label class="label">密码 (留空不改)</label>
          <input class="input" id="edit-password" type="password" autocomplete="new-password" placeholder="至少 8 位"></div>
        <div class="field"><label class="label">角色</label>
          <select class="select" id="edit-role">
            <option value="user" ${user.role_code !== "admin" ? "selected" : ""}>普通用户</option>
            <option value="admin" ${user.role_code === "admin" ? "selected" : ""}>管理员</option>
          </select></div>
        <div style="display:flex;gap:10px;justify-content:flex-end">
          <button type="button" class="btn ghost" data-close>取消</button>
          <button type="submit" class="btn">保存</button>
        </div>
      </form>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector("[data-close]").addEventListener("click", close);
  overlay.querySelector(".icon-btn").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); }, { once: true });
  overlay.querySelector("#user-edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      username: overlay.querySelector("#edit-username").value.trim(),
      role: overlay.querySelector("#edit-role").value,
    };
    const pw = overlay.querySelector("#edit-password").value;
    if (pw) body.password = pw;
    try {
      await api.patch(`/api/admin/users/${user.id}`, body);
      toastOk(`用户 ${user.username} 已更新`);
      close();
      onDone(root);
    } catch (err) { toastErr(err.message); }
  });
}
