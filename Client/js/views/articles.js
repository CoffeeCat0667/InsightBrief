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
      const contents = (a.contents || []).map((c) => {
        if (c.type === "image") {
          return `<div style="text-align:center;margin:10px 0"><img src="${esc(c.content)}" alt="${esc(c.desc || "")}" style="max-width:100%;border-radius:6px;display:inline-block" loading="lazy">${c.desc && c.desc !== c.content ? `<div style="color:var(--text-3);font-size:12.5px;margin-top:4px">${esc(c.desc)}</div>` : ""}</div>`;
        }
        if (c.type === "video") {
          return `<div style="text-align:center;margin:10px 0"><video src="${esc(c.content)}" controls style="max-width:100%;border-radius:6px;display:inline-block"></video></div>`;
        }
        return `<div class="content-block">${esc(c.content)}</div>`;
      }).join("");
      const cnInTitle = /[\u4e00-\u9fff]/.test((a.title || "") + (a.language || ""));
      const isForeign = !cnInTitle;
      overlay.querySelector(".card").innerHTML = `
        <button class="icon-btn" style="position:absolute;right:14px;top:14px" aria-label="关闭">✕</button>
        <div class="detail-head">
          <h2 id="dt-title">${esc(a.translated_title || a.title)}</h2>
          ${a.translated_title ? `<div id="dt-sub" style="color:var(--text-3);font-size:14px;margin-bottom:8px">${esc(a.title)}</div>` : ""}
          <div class="detail-meta">
            <span>${esc(a.source_name || a.source_id)}</span>
            ${a.category ? catBadge(a.category) : ""}
            <span>作者: ${esc(a.author_name || "—")}</span>
            <span>语言: ${esc(a.language || "—")}</span>
            <span>发表于 ${fmtTime(a.publish_time)}</span>
          </div>
          <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
            <a class="btn ghost sm" href="${esc(a.url)}" target="_blank" rel="noopener">查看原文 ↗</a>
            ${isForeign ? `<button class="btn ghost sm" id="tr-btn">翻译</button>` : ""}
          </div>
        </div>
        <div class="detail-body">
          ${a.summary ? `<div><div class="section-title">AI 摘要</div><div class="content-block" style="color:var(--text-2)">${esc(a.summary)}</div></div>` : ""}
          ${a.translated_content ? `<div><div class="section-title">全文翻译</div><div class="translated-block">${esc(a.translated_content)}</div></div>` : ""}
          <div id="orig-box"><div class="section-title">原文内容 (${(a.contents || []).length} 片段)</div>${contents || `<div class="empty-hint">此来源为摘要型, 未抓取正文片段</div>`}</div>
        </div>`;
      overlay.querySelector("button").addEventListener("click", () => overlay.remove());

      const trBtn = overlay.querySelector("#tr-btn");
      if (trBtn) {
        const origTitle = a.translated_title || a.title;
        const origSub = a.translated_title ? a.title : "";
        const origBody = overlay.querySelector("#orig-box").innerHTML;
        const text = (a.contents || []).filter((c) => c.type === "text").map((c) => c.content).join("\n\n").trim();
        let showingCn = false;
        trBtn.addEventListener("click", async () => {
          if (!showingCn) {
            if (!text) { toastErr("无正文可翻译"); return; }
            trBtn.disabled = true;
            trBtn.textContent = "翻译中... (长文约 1-2 分钟)";
            try {
              const r = await api.post("/api/translate", { text, title: a.title || undefined });
              const cnTitle = r.translated_title || origTitle;
              const cnBody = r.translated;
              overlay.querySelector("#dt-title").textContent = cnTitle;
              const sub = overlay.querySelector("#dt-sub");
              if (sub) sub.textContent = a.title;
              else if (a.title && cnTitle !== a.title) {
                const subEl = document.createElement("div");
                subEl.id = "dt-sub";
                subEl.style.cssText = "color:var(--text-3);font-size:14px;margin-bottom:8px";
                subEl.textContent = a.title;
                overlay.querySelector("#dt-title").after(subEl);
              }
              overlay.querySelector("#orig-box").innerHTML =
                `<div class="section-title">中文译文 (临时)</div><div class="translated-block">${cnBody.split(/\n{2,}/).map((p) => `<p style="margin:0 0 10px">${esc(p)}</p>`).join("")}</div>`;
              showingCn = true;
              trBtn.textContent = "显示原文";
            } catch (e) {
              toastErr(`翻译失败: ${e.message}`);
              trBtn.textContent = "翻译";
            }
            trBtn.disabled = false;
          } else {
            overlay.querySelector("#dt-title").textContent = origTitle;
            const sub = overlay.querySelector("#dt-sub");
            if (origSub) sub.textContent = origSub;
            else if (sub) sub.remove();
            overlay.querySelector("#orig-box").innerHTML = origBody;
            showingCn = false;
            trBtn.textContent = "翻译";
          }
        });
      }
    } catch (e) {
      overlay.querySelector(".card").innerHTML = `<div class="empty-hint">${esc(e.message)}</div>`;
    }
  }

  render();
}