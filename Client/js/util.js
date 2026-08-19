// 通用工具: 格式化 / 徽章 / 状态色 / 逃逸
export const fmtTime = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export const fmtDateTime = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

export const escapeHtml = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

export const esc = escapeHtml;

export const CATEGORY_LABELS = {
  politics: "政治",
  economy: "经济",
  culture: "文化",
  technology: "科技",
  other: "其他",
};

export const catBadge = (cat) =>
  `<span class="cat cat-${esc(cat || "other")}">${esc(CATEGORY_LABELS[cat] || "其他")}</span>`;

export const statusBadge = (st) => {
  const map = {
    pending: ["mute", "待运行"],
    running: ["info", "运行中"],
    completed: ["ok", "已完成"],
    failed: ["err", "失败"],
    skipped: ["mute", "已跳过"],
    cancelled: ["warn", "已取消"],
  };
  const [cls, label] = map[st] || ["mute", st];
  const dot = st === "running" ? `<span class="dot"></span>` : "";
  return `<span class="badge ${cls}">${dot}${label}</span>`;
};

export const deferred = () => {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

export const debounce = (fn, ms = 350) => {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
};

export const pager = (page, pages, total, onChange) => {
  const prev = page > 1 ? `<button class="btn ghost sm" data-pg="${page - 1}">上一页</button>` : "";
  const next = page < pages ? `<button class="btn ghost sm" data-pg="${page + 1}">下一页</button>` : "";
  return `
    <div class="pager">
      ${prev}
      <span class="page-info">第 ${page} / ${Math.max(pages, 1)} 页 · 共 ${total} 条</span>
      ${next}
    </div>`;
};