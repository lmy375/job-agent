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
  JobKind,
  JobListResponse,
  KeywordsResponse,
  OverviewResponse,
  PromptsResponse,
  PromptsUpdate,
  ScoreRefreshResponse,
  ScoreSettings,
  TaskListResponse,
  TaskResponse,
} from "./types";

const BASE = "/api";

/**
 * 后端出错时的响应体。
 *
 * 两种形状：自己抛的是 `schemas.ErrorResponse`（`detail` 是一句话），
 * 请求体校验失败是 FastAPI 自己的 422（`detail` 是一串 `{loc, msg}`）。
 * 后者一定要展开——配置页把 `[score]` 整段发过去，「哪条信号的正则写错了」
 * 全在 `loc` 里，丢掉它页面上只会显示一句没用的「请求失败」。
 */
interface ErrorBody {
  detail?: string | ValidationError[];
  type?: string;
}

interface ValidationError {
  loc?: (string | number)[];
  msg?: string;
}

function errorText(body: ErrorBody | null, status: number): string {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((item) => {
        // loc 形如 ["body", "signals", 3, "pattern"]，"body" 对用户没意义
        const where = (item.loc ?? []).filter((part) => part !== "body").join(".");
        return where ? `${where}：${item.msg ?? ""}` : (item.msg ?? "");
      })
      .join("；");
  }
  return `请求失败（HTTP ${status}）`;
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
    throw new Error(errorText(data as ErrorBody | null, res.status));
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
  /** 职位类型：`"2"` HR 岗位 / `"1"` 猎头岗位；空串 = 两类都看 */
  job_type?: string;
  min_salary?: string | number;
  has_detail?: string | boolean;
  applied?: string | boolean;
  scored?: string | boolean;
  /** 是否已 LLM 打分。挑「还没打过的那批」批量送模型时用 */
  llm_scored?: string | boolean;
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
  applyJob: (jobId: number, jobKind?: JobKind) =>
    request<ApplyResponse>(`/jobs/${jobId}/apply`, {
      method: "POST",
      body: JSON.stringify({ job_kind: jobKind ?? null }),
    }),
  applications: () => request<ApplicationsResponse>("/applications"),
  /** 按当前 `[score]` 重新打分并整表落库（= 命令行的 `job score`）。 */
  refreshScores: () => request<ScoreRefreshResponse>("/scores/refresh", { method: "POST" }),
  /** 改写 `[search].keywords`（顺序即优先级），写回 profile.toml 并重新加载。 */
  updateKeywords: (keywords: string[]) =>
    request<ConfigResponse>("/config/keywords", {
      method: "PUT",
      body: JSON.stringify({ keywords }),
    }),
  /** 改写整个 `[score]` 段。改完分数就过期了，得再点一次重新打分。 */
  updateScore: (score: ScoreSettings) =>
    request<ConfigResponse>("/config/score", { method: "PUT", body: JSON.stringify(score) }),
  /** LLM 打分的两段提示词（内置默认也会返回全文，页面上能直接改）。 */
  prompts: () => request<PromptsResponse>("/config/prompts"),
  /** 改写提示词。**空串 = 删掉覆盖文件、回到内置默认**。 */
  updatePrompts: (payload: PromptsUpdate) =>
    request<PromptsResponse>("/config/prompts", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
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
