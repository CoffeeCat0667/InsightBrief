// 平台只读展示: 26 平台卡片
import { api, toastErr } from "../api.js";
import { esc } from "../util.js";

export async function platformsView(root) {
  root.innerHTML = `<div class="grid"><div class="skeleton" style="height:90px"></div><div class="skeleton" style="height:90px"></div><div class="skeleton" style="height:90px"></div></div>`;
  try {
    const items = await api.get("/api/platforms");
    if (!Array.isArray(items) || !items.length) {
      root.innerHTML = `<div class="empty-hint">无平台数据</div>`;
      return;
    }
    root.innerHTML = `
      <div class="grid">
        ${items.map((p) => `
          <div class="card platform-card">
            <h3>${esc(p.name)}</h3>
            <span class="pid">${esc(p.platform_id)}</span>
            ${p.category_label ? `<span class="badge mute">${esc(p.category_label)}</span>` : ""}
            <span class="srcs">源: ${(p.source_ids || []).map(esc).join(", ") || "—"}</span>
          </div>`).join("")}
      </div>`;
  } catch (e) {
    toastErr(e.message);
    root.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`;
  }
}