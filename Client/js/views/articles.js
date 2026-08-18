// 文章: 列表 / 搜索 / 分类筛选 / 详情
import { api, toastErr } from "../api.js";
import { CATEGORY_LABELS, catBadge, debounce, esc, fmtTime, pager } from "../util.js";

const PAGE_SIZE = 15;

async function loadSources() {
  try {
    const page = await api.get("/api/sources", { page_size: 100 });
    return page.items || [];
  } catch {
    return [];
  }
}

export async function articlesView(root) {
  const sources = await loadSources();
  root.innerHTML = `
    <div class="toolbar">
      <input class="input grow" id="kw" placeholder="搜索关键词(原文/译文)..." style="max-width:340px">
      <select class="select" id="f-source">
        <option value="">全部来源</option>
        ${sources.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}
      </select>
      <div class="chips" id="f-cat">
        <button class="chip active" data-cat="">全部</button>
        ${Object.entries(CATEGORY_LABELS).filter(([k]) => k !== "other").map(([k, v]) =>
          `<button class="chip" data-cat="${k}">${v}</button>`).join("")}
      </div>
    </div>
    <div id="article-list"><div class="skeleton" style="height:70px;margin-bottom:12px"></div><div class="skeleton" style="height:70px;margin-bottom:12px"></div></div>
    <div id="article-pager"></div>`;

  let state = { page: 1, kw: "", source: "", cat: "" };
  const listEl = root.querySelector("#article-list");
  const pagerEl = root.querySelector("#article-pager");
  const search = () => { state.page = 1; render(); };

  root.querySelector("#kw").addEventListener("input", debounce((e) => {
    state.kw = e.target.value.trim();
    search();
  }));
  root.querySelector("#f-source").addEventListener("change", (e) => { state.source = e.target.value; search(); });
  root.querySelectorAll("#f-cat .chip").forEach((c) => c.addEventListener("click", () => {
    root.querySelectorAll("#f-cat .chip").forEach((x) => x.classList.remove("active"));
    c.classList.add("active");
    state.cat = c.dataset.cat;
    search();
  }));

  async function render() {
    listEl.innerHTML = `<div class="skeleton" style="height:70px;margin-bottom:12px"></div><div class="skeleton" style="height:70px;margin-bottom:12px"></div>`;
    try {
      let page;
      if (state.kw) {
        page = await api.get("/api/articles/search", {
          keyword: state.kw, source_id: state.source || undefined, page: state.page, page_size: PAGE_SIZE,
        });
      } else {
        page = await api.get("/api/articles", {
          source_id: state.source || undefined, category: state.cat || undefined, page: state.page, page_size: PAGE_SIZE,
        });
      }
      renderList(page);
    } catch (e) {
      toastErr(e.message);
      listEl.innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`;
    }
  }

  function renderList(page) {
    if (!page.items.length) {
      listEl.innerHTML = `<div class="empty-hint">暂无文章 — 去「抓取任务」页发起一次抓取</div>`;
      pagerEl.innerHTML = "";
      return;
    }
    listEl.innerHTML = page.items.map((a) => `
      <div class="card clickable article-item" data-id="${a.id}">
        <div>
          ${a.translated_title ? `<div class="article-title-cn article-title">${esc(a.translated_title)}</div>
            <div class="article-title-en article-title">${esc(a.title)}</div>`
          : `<div class="article-title article-title-cn">${esc(a.title)}</div>`}
        </div>
        <div class="article-meta">
          <span>${esc(a.source_name || a.source_id)}</span>
          ${a.category ? catBadge(a.category) : ""}
          <span>发表于 ${fmtTime(a.publish_time)}</span>
          <span>入库 ${fmtTime(a.created_at)}</span>
        </div>
        ${a.summary ? `<div class="article-summary">${esc(a.summary)}</div>` : ""}
      </div>`).join("");
    listEl.querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => openDetail(c.dataset.id)));
    pagerEl.innerHTML = pager(page.page, page.pages, page.total, (pg) => { state.page = pg; render(); });
    pagerEl.querySelectorAll("[data-pg]").forEach((b) => b.addEventListener("click", () => {
      state.page = Number(b.dataset.pg);
      render();
      window.scrollTo({ top: 0 });
    }));
  }

  async function openDetail(id) {
    const overlay = document.createElement("div");
    overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:60;display:flex;align-items:flex-start;justify-content:center;padding:30px 16px;overflow-y:auto;backdrop-filter:blur(3px)`;
    overlay.innerHTML = `<div class="card" style="max-width:860px;width:100%;position:relative">
      <button class="icon-btn" style="position:absolute;right:14px;top:14px" aria-label="关闭">✕</button>
      <div style="height:60px" class="skeleton"></div></div>`;
    document.body.appendChild(overlay);
    overlay.querySelector("button").addEventListener("click", () => overlay.remove());
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") overlay.remove(); }, { once: true });

    overlay.querySelector(".card").innerHTML = `<div class="detail-head">
      <h2>${esc("加载中...")}</h2></div>`;
    try {
      const a = await api.get(`/api/articles/${id}`);
      const contents = (a.contents || []).map((c) =>
        c.type === "media"
          ? `<div class="content-block media">📷 ${esc(c.desc || "媒体")}: ${esc(c.content)}</div>`
          : `<div class="content-block">${esc(c.content)}</div>`).join("");
      overlay.querySelector(".card").innerHTML = `
        <button class="icon-btn" style="position:absolute;right:14px;top:14px" aria-label="关闭">✕</button>
        <div class="detail-head">
          <h2>${esc(a.translated_title || a.title)}</h2>
          ${a.translated_title ? `<div style="color:var(--text-3);font-size:14px;margin-bottom:8px">${esc(a.title)}</div>` : ""}
          <div class="detail-meta">
            <span>${esc(a.source_name || a.source_id)}</span>
            ${a.category ? catBadge(a.category) : ""}
            <span>作者: ${esc(a.author_name || "—")}</span>
            <span>语言: ${esc(a.language || "—")}</span>
            <span>发表于 ${fmtTime(a.publish_time)}</span>
          </div>
          <a class="btn ghost sm" href="${esc(a.url)}" target="_blank" rel="noopener">查看原文 ↗</a>
        </div>
        <div class="detail-body">
          ${a.summary ? `<div><div class="section-title">AI 摘要</div><div class="content-block" style="color:var(--text-2)">${esc(a.summary)}</div></div>` : ""}
          ${a.translated_content ? `<div><div class="section-title">全文翻译</div><div class="translated-block">${esc(a.translated_content)}</div></div>` : ""}
          <div><div class="section-title">原文内容 (${contents ? (a.contents || []).length : 0} 片段)</div>${contents || `<div class="empty-hint">此来源为摘要型, 未抓取正文片段</div>`}</div>
        </div>`;
      overlay.querySelector("button").addEventListener("click", () => overlay.remove());
    } catch (e) {
      overlay.querySelector(".card").innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`;
    }
  }

  render();
}