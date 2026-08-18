// SSE 客户端: fetch + ReadableStream 手写解析 (原生 EventSource 无法携带 Authorization 头;
// 故此处用 fetch 流式读取, 兼容标准 SSE 行格式与心跳 `: ping`).
import { store } from "./api.js";

export async function streamEvents(path, { onEvent, signal } = {}) {
  const resp = await fetch(path, {
    headers: store.token ? { Authorization: `Bearer ${store.token}` } : {},
    signal,
  });
  if (!resp.ok) {
    let message = `SSE 连接失败 (HTTP ${resp.status})`;
    try {
      const p = await resp.json();
      message = p?.error?.message || message;
    } catch { /* ignore */ }
    throw new Error(message);
  }
  if (!resp.body) throw new Error("浏览器不支持流式响应");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let event = null;
  let dataLines = [];

  const dispatch = () => {
    if (!event || !dataLines.length) return;
    const raw = dataLines.join("\n");
    let parsed = raw;
    try { parsed = JSON.parse(raw); } catch { /* 非 JSON 载荷 */ }
    onEvent?.(event, parsed);
    event = null;
    dataLines = [];
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // 归一化行尾后再按空行切块
    const norm = decoder.decode(value, { stream: true }).replace(/\r\n|\r/g, "\n");
    buf += norm;
    let sep;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith(":")) continue; // 心跳/注释行
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      dispatch();
    }
  }
  // 流结束时处理残块 (无尾随空行)
  for (const line of buf.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  dispatch();
}