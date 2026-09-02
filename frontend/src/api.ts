/**
 * 后端 API 封装。
 *
 * 所有请求都从这里走：错误统一转成 Error（带后端的中文 detail），
 * 组件里就不需要各自判断 res.ok 了。
 *
 * 每个方法的返回类型都钉在 `types.ts` 的接口上——后端字段改名时，
 * 报错会落在真正用到它的那一行，而不是等页面渲染出空白。
 */

import type {
  ApplicationsResponse,
  ApplyResponse,
  ConfigResponse,
  CreateTaskRequest,
  HealthResponse,
  JobBundle,
  JobListResponse,
  KeywordsResponse,
  OverviewResponse,
  TaskListResponse,
  TaskResponse,
} from "./types";

const BASE = "/api";

/** 后端出错时的响应体（`schemas.ErrorResponse`）。 */
interface ErrorBody {
  detail?: string;
  type?: string;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // 后端在极端情况下可能返回非 JSON（如代理层的错误页），别让解析错误盖掉真实原因
    if (!res.ok) throw new Error(`请求失败（HTTP ${res.status}）：${text.slice(0, 200)}`);
    throw new Error("响应不是合法 JSON");
  }
  if (!res.ok) {
    throw new Error((data as ErrorBody | null)?.detail || `请求失败（HTTP ${res.status}）`);
  }
  return data as T;
}

/** 查询串里允许出现的值。空串 / null / undefined 一律不发，交给后端的默认值。 */
type QueryValue = string | number | boolean | null | undefined;

function query(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/** `/api/jobs` 的筛选条件。都是可选的，对应后端那一串 `Query(...) = None`。 */
export interface JobsQuery extends Record<string, QueryValue> {
  keyword?: string;
  q?: string;
  min_salary?: string | number;
  has_detail?: string | boolean;
  applied?: string | boolean;
  scored?: string | boolean;
  order?: "score" | "recent" | "salary" | "salary_asc";
  limit?: number;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  config: () => request<ConfigResponse>("/config"),
  keywords: () => request<KeywordsResponse>("/keywords"),
  stats: () => request<OverviewResponse>("/stats"),
  jobs: (params: JobsQuery) => request<JobListResponse>(`/jobs${query(params)}`),
  job: (jobId: number) => request<JobBundle>(`/jobs/${jobId}`),
  applyJob: (jobId: number, jobKind?: "1" | "2") =>
    request<ApplyResponse>(`/jobs/${jobId}/apply`, {
      method: "POST",
      body: JSON.stringify({ job_kind: jobKind ?? null }),
    }),
  applications: () => request<ApplicationsResponse>("/applications"),
  tasks: () => request<TaskListResponse>("/tasks"),
  task: (taskId: string) => request<TaskResponse>(`/tasks/${taskId}`),
  createTask: (payload: CreateTaskRequest) =>
    request<TaskResponse>("/tasks", { method: "POST", body: JSON.stringify(payload) }),
  cancelTask: (taskId: string) =>
    request<TaskResponse>(`/tasks/${taskId}/cancel`, { method: "POST" }),
};

/**
 * 从 catch 到的东西里取出能给人看的一句话。
 *
 * catch 的类型是 `unknown`（什么都可能被 throw），所以不能直接 `e.message`。
 */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
