// Hash 路由 + 布局渲染 + 角色门卫 + 主题(跟随系统 + 手动覆盖)
import { store, setUnauthorizedHandler, toast } from "./api.js";
import { esc } from "./util.js";
import { authView } from "./views/auth.js";
import { articlesView } from "./views/articles.js";
import { crawlView } from "./views/crawl.js";
import { briefView } from "./views/brief.js";
import { sourcesView } from "./views/sources.js";
import { auditView } from "./views/audit.js";
import { platformsView } from "./views/platforms.js";

const THEME_KEY = "ib_theme"; // auto | light | dark

const NAV = [
  { hash: "articles", icon: "i-news", label: "文章" },
  { hash: "brief", icon: "i-brief", label: "简报" },
  { hash: "crawl", icon: "i-crawl", label: "抓取任务" },
  { hash: "sources", icon: "i-source", label: "新闻源" },
  { hash: "platforms", icon: "i-server", label: "平台" },
  { hash: "audit", icon: "i-audit", label: "审计日志", admin: true },
];

const VIEWS = {
  articles: articlesView,
  brief: briefView,
  crawl: crawlView,
  sources: sourcesView,
  platforms: platformsView,
  audit: auditView,
};

let layoutReady = false;

export const isAdmin = () => store.user?.role?.code === "admin";

const $ = (id) => document.getElementById(id);

function applyTheme() {
  const mode = localStorage.getItem(THEME_KEY) || "auto";
  const dark = mode === "dark" || (mode === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  const btn = $("theme-toggle");
  if (btn) {
    const cur = mode === "auto" ? (dark ? "dark" : "light") : mode;
    btn.innerHTML = `<svg><use href="#${cur === "dark" ? "i-sun" : "i-moon"}"/></svg>`;
  }
}

function renderLayout() {
  $("auth-shell").classList.add("hidden");
  $("app-shell").classList.remove("hidden");
  $("side-nav").innerHTML = NAV
    .filter((n) => !n.admin || isAdmin())
    .map((n) => `
      <button class="nav-item" data-hash="${n.hash}">
        <svg><use href="#${n.icon}"/></svg><span>${n.label}</span>
      </button>`)
    .join("");
  const u = store.user || {};
  $("user-avatar").textContent = (u.username || "?").slice(0, 2).toUpperCase();
  $("user-name").textContent = u.username || "";
  const roleEl = $("user-role");
  roleEl.textContent = isAdmin() ? "admin" : "user";
  roleEl.className = `role-badge ${isAdmin() ? "admin" : ""}`;

  $("side-nav").querySelectorAll(".nav-item").forEach((el) => {
    el.addEventListener("click", () => {
      location.hash = `#/${el.dataset.hash}`;
      document.querySelector(".sidebar")?.classList.remove("open");
    });
  });
  $("logout-btn").addEventListener("click", () => {
    store.clear();
    location.hash = "#/";
    location.reload();
  });
  $("theme-toggle").addEventListener("click", () => {
    const cur = localStorage.getItem(THEME_KEY) || "auto";
    const next = cur === "auto" ? "light" : cur === "light" ? "dark" : "auto";
    localStorage.setItem(THEME_KEY, next);
    applyTheme();
    toast(next === "auto" ? "主题: 跟随系统" : `主题: ${next === "light" ? "浅色" : "深色"}`, "info", 1600);
  });
  $("nav-toggle").addEventListener("click", () => {
    document.querySelector(".sidebar")?.classList.toggle("open");
  });
  applyTheme();
}

function renderAuth() {
  layoutReady = false;
  $("app-shell").classList.add("hidden");
  $("auth-shell").classList.remove("hidden");
  applyTheme();
  authView($("auth-shell"));
}

async function route() {
  if (!store.token || !store.user) {
    renderAuth();
    return;
  }
  if (!layoutReady) {
    renderLayout();
    layoutReady = true;
  }
  let hash = (location.hash || "#/articles").replace(/^#\/?/, "").split("/")[0] || "articles";
  let view = VIEWS[hash] || articlesView;
  if (view.admin && !isAdmin()) {
    view = articlesView;
    hash = "articles";
  }
  $("side-nav").querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.hash === hash);
  });
  const def = NAV.find((n) => n.hash === hash);
  $("page-title").textContent = def ? def.label : "文章";
  $("view-root").innerHTML = `<div class="skeleton" style="height:90px;margin-bottom:14px"></div>`;
  try {
    await view($("view-root"));
  } catch (e) {
    toast(e?.message || "视图加载失败", "err");
    $("view-root").innerHTML = `<div class="empty-hint">${esc(e?.message || "加载失败")}</div>`;
  }
}

setUnauthorizedHandler(() => {
  location.hash = "#/";
  location.reload();
});

window.addEventListener("hashchange", route);
applyTheme();
document.addEventListener("DOMContentLoaded", route);