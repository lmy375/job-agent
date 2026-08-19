/**
 * 后端 API 封装。
 *
 * 所有请求都从这里走：错误统一转成 Error（带后端的中文 detail），
 * 组件里就不需要各自判断 res.ok 了。
 */

const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // 后端在极端情况下可能返回非 JSON（如代理层的错误页），别让解析错误盖掉真实原因
    if (!res.ok) throw new Error(`请求失败（HTTP ${res.status}）：${text.slice(0, 200)}`);
    throw new Error("响应不是合法 JSON");
  }
  if (!res.ok) {
    throw new Error(data?.detail || `请求失败（HTTP ${res.status}）`);
  }
  return data;
}

function query(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  health: () => request("/health"),
  config: () => request("/config"),
  keywords: () => request("/keywords"),
  stats: () => request("/stats"),
  trackStats: () => request("/stats/tracks"),
  jobs: (params) => request(`/jobs${query(params)}`),
  job: (jobId) => request(`/jobs/${jobId}`),
  applyJob: (jobId, jobKind) =>
    request(`/jobs/${jobId}/apply`, {
      method: "POST",
      body: JSON.stringify({ job_kind: jobKind ?? null }),
    }),
  applications: () => request("/applications"),
  tasks: () => request("/tasks"),
  task: (taskId) => request(`/tasks/${taskId}`),
  createTask: (payload) =>
    request("/tasks", { method: "POST", body: JSON.stringify(payload) }),
  cancelTask: (taskId) => request(`/tasks/${taskId}/cancel`, { method: "POST" }),
};
