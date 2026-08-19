// 登录 / 注册视图
import { api, store, toast, toastErr } from "../api.js";

export async function authView(root) {
  root.innerHTML = `
    <div class="auth-card">
      <div class="auth-brand">
        <span class="brand-mark">IB</span>
        <div>
          <h1>InsightBrief</h1>
          <p>新闻采集 · 自动翻译 · AI 简报</p>
        </div>
      </div>
      <div class="tabs">
        <button class="tab active" data-tab="login">登录</button>
        <button class="tab" data-tab="register">注册</button>
      </div>
      <form id="auth-form" novalidate>
        <div id="tab-login">
          <div class="field">
            <label class="label">用户名</label>
            <input class="input" name="username" placeholder="用户名" autocomplete="username" required>
          </div>
          <div class="field">
            <label class="label">密码</label>
            <input class="input" type="password" name="password" placeholder="密码" autocomplete="current-password" required>
          </div>
        </div>
        <div id="tab-register" class="hidden">
          <div class="field">
            <label class="label">用户名</label>
            <input class="input" name="username" placeholder="3-64 位字母/数字/下划线" autocomplete="username" required>
          </div>
          <div class="field">
            <label class="label">密码</label>
            <input class="input" type="password" name="password" placeholder="至少 8 位" autocomplete="new-password" required>
          </div>
          <div class="field">
            <label class="label">邮箱(可选)</label>
            <input class="input" type="email" name="email" placeholder="xxx@example.com" autocomplete="email">
          </div>
        </div>
        <button class="btn lg auth-submit" type="submit" id="auth-submit">登录</button>
      </form>
      <div class="auth-hint">抓取与简报任务在服务端后台执行, 刷新页面不中断;</div>
    </div>`;

      const tabs = root.querySelectorAll(".tab");
      const loginTab = root.querySelector("#tab-login");
      const registerTab = root.querySelector("#tab-register");
      const submit = root.querySelector("#auth-submit");

      // 关闭注册入口时隐藏注册选项卡
      let registrationEnabled = true;
      tabs.forEach((t) => t.addEventListener("click", () => {
        tabs.forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        const mode = t.dataset.tab;
        loginTab.classList.toggle("hidden", mode !== "login");
        registerTab.classList.toggle("hidden", mode !== "register");
        submit.textContent = mode === "login" ? "登录" : "注册并登录";
      }));
      try {
        const reg = await api.get("/api/auth/registration");
        registrationEnabled = reg.enabled !== false;
      } catch { /* 默认开放 */ }
      if (!registrationEnabled) {
        root.querySelectorAll('.tab[data-tab="register"]').forEach((x) => x.classList.add("hidden"));
        root.querySelector("#tab-register").classList.add("hidden");
      }

  root.querySelector("#auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const mode = root.querySelector(".tab.active").dataset.tab;
    // 注意: 两 tab 存在同名控件, form.name 命名访问返回 RadioNodeList(无 value) —
    // 必须按 tab 取可见区内的控件
    const sel = mode === "login" ? "#tab-login" : "#tab-register";
    const username = root.querySelector(`${sel} input[name=username]`).value.trim();
    const password = root.querySelector(`${sel} input[name=password]`).value;
    submit.disabled = true;
    submit.textContent = "请稍候...";
    try {
      if (mode === "login") {
        const data = await api.postForm("/api/auth/login", { username, password });
        store.setAuth(data.access_token, data.user);
        toast(`欢迎回来, ${data.user.username}`, "ok");
      } else {
        const email = root.querySelector(`${sel} input[name=email]`).value.trim() || undefined;
        await api.post("/api/auth/register", { username, password, email });
        const data = await api.postForm("/api/auth/login", { username, password });
        store.setAuth(data.access_token, data.user);
        toast("注册成功, 已自动登录", "ok");
      }
      setTimeout(() => location.reload(), 400);
    } catch (err) {
      toastErr(err.message || "操作失败");
      submit.disabled = false;
      submit.textContent = mode === "login" ? "登录" : "注册并登录";
    }
  });
}