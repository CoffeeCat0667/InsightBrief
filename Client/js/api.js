// API 封装: Bearer 注入 / 401 登出 / 统一错误 toast
const TOKEN_KEY = "ib_token";
const USER_KEY = "ib_user";
const TABS_KEY = "ib_tabs";

export const store = {
  get token() { return localStorage.getItem(TOKEN_KEY) || ""; },
  get user() {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); }
    catch { return null; }
  },
  get tabs() { return JSON.parse(localStorage.getItem(TABS_KEY) || "null"); },
  setAuth(token, user, tabs = null) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    if (tabs) localStorage.setItem(TABS_KEY, JSON.stringify(tabs));
  },
  setTabs(tabs) { localStorage.setItem(TABS_KEY, JSON.stringify(tabs)); },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(TABS_KEY);
  },
};

export function toast(msg, kind = "info", ms = 3200) {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<span>${msg}</span>`;
  root.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity 0.3s";
    setTimeout(() => el.remove(), 320);
  }, ms);
}

export const toastOk = (m) => toast(m, "ok");
export const toastErr = (m) => toast(m, "err");
export const toastWarn = (m) => toast(m, "warn");

let onUnauthorized = null;
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

// 查询参数构建
export function qs(params = {}) {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    usp.set(k, v);
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

async function request(method, path, { body, form, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (form !== undefined) headers["Content-Type"] = "application/x-www-form-urlencoded";
  if (auth && store.token) headers["Authorization"] = `Bearer ${store.token}`;

  let resp;
  try {
    let bodyStr = undefined;
    if (body !== undefined) bodyStr = JSON.stringify(body);
    else if (form !== undefined) {
      // 过滤 undefined/null, 防止 URLSearchParams 跳过值导致字段静默丢失
      const clean = {};
      for (const [k, v] of Object.entries(form)) {
        if (v !== undefined && v !== null) clean[k] = String(v);
      }
      bodyStr = new URLSearchParams(clean).toString();
    }
    resp = await fetch(path, {
      method,
      headers,
      body: bodyStr,
    });
  } catch (e) {
    toastErr("网络请求失败: 请确认服务已启动");
    throw e;
  }
  return handle(resp);
}

async function handle(resp) {
  if (resp.status === 401 && store.token) {
    store.clear();
    if (onUnauthorized) onUnauthorized();
    throw new Error("登录已过期");
  }
  let payload = null;
  try { payload = await resp.json(); } catch { /* 非 JSON 响应 */ }
  if (!resp.ok) {
    const message = payload?.error?.message || `请求失败 (HTTP ${resp.status})`;
    const err = new Error(message);
    err.status = resp.status;
    err.code = payload?.error?.code;
    throw err;
  }
  return payload?.data;
}

export const api = {
  get: (path, params) => request("GET", path + qs(params)),
  post: (path, body) => request("POST", path, { body }),
  postForm: (path, form) => request("POST", path, { form }),
  patch: (path, body) => request("PATCH", path, { body }),
  delete: (path) => request("DELETE", path),
};