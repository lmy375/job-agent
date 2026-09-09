/**
 * 后端接口的响应类型。
 *
 * 逐一对应 `src/job_agent/web/schemas.py` 与 `core/storage/rows.py` 里的 pydantic
 * 模型——**后端改了字段这里就得跟着改**（CLAUDE.md：接口不做向后兼容，
 * 字段改了就同步改前端，不留兼容分支）。
 *
 * 两条翻译规则：
 * - `datetime` → `string`（ISO 8601）。后端刻意不预先格式化，展示是前端的事，
 *   见 `format.ts`。
 * - `Path` → `string`。
 *
 * 后端模型里带默认值的字段（`str = ""`、`list = []`）在这里是**必填**的：
 * 响应里一定有这个键，只是可能是空串 / 空数组。真正可能缺的是 `| None`，
 * 那些写成 `| null`。
 */

/**
 * `core/liepin/enums.py` 的 `JobKind`：**谁在招**。
 *
 * `"2"` = HR 岗位（企业自己挂的，详情页 /job/），`"1"` = 猎头岗位（详情页 /a/）。
 * 库里 `jobType` 仍然是裸字符串（老数据可能是空串），所以取标签时要兜底。
 */
export type JobKind = "1" | "2";

/** `core/storage/rows.py` 的 `JobRow`：`jobs` 表一行 + LEFT JOIN 上来的分数。 */
export interface JobRow {
  jobId: number;
  jobType: string;
  jobName: string;
  company: string;
  location: string;
  salary: string;
  /** 由 salary 文案解析出的年薪区间（万元，税前）；解析不出来时为 null */
  salaryLowWan: number | null;
  salaryHighWan: number | null;
  education: string;
  workYears: string;
  industry: string;
  companyTags: string[];
  financingStage: string;
  companySize: string;
  companyLogo: string;
  jobDetailUrl: string;
  searchKeyword: string;
  searchTime: string;

  // ---- 以下来自 job_scores：没跑过 job score 就整块是 null / 空数组
  score: number | null;
  /** 全库密集排名（按分数降序，1 起），与看的时候的过滤条件无关 */
  scoreRank: number | null;
  offTrack: boolean | null;
  scoreHits: string[];
  scorePenalties: string[];
  scoredAt: string | null;

  // ---- 以下来自 llm_scores：没送过模型就整块是 null / 空数组
  /** 岗位吸引力（1-10，从求职者角度：这份工作本身值多少分） */
  llmAppeal: number | null;
  /** 胜任匹配度（1-10，从招聘方角度：这个人拿到它的概率） */
  llmFit: number | null;
  llmAppealReasons: string[];
  llmFitReasons: string[];
  /** 判这条的模型。换了模型分数就不可比，所以逐行记 */
  llmProvider: string | null;
  llmModel: string | null;
  llmScoredAt: string | null;
}

/** `JobDetailRow`：解析出的 JD 字段 + 落库时才有的身份与状态。 */
export interface JobDetailRow {
  jobId: number;
  /** ok / no_jd / http_<code> / error:<类型> / blocked */
  status: string;
  fetchTime: string | null;
  title: string;
  description: string;
  responsibilities: string;
  requirements: string;
  industry: string;
  experienceRequirements: string;
  educationRequirements: string;
  employmentType: string;
  datePosted: string;
  companyName: string;
  companyUrl: string;
  streetAddress: string;
}

/** 一次投递尝试。 */
export interface ApplicationRow {
  id: number;
  jobId: number;
  status: string;
  message: string;
  appliedAt: string;
}

/** `JobBundle`：职位 + JD + 投递记录，详情面板一次取齐。 */
export interface JobBundle extends JobRow {
  detail: JobDetailRow | null;
  applications: ApplicationRow[];
}

export interface KeywordCount {
  keyword: string;
  count: number;
}

/** 整库薪资概览（万元，税前）。薪资解析不出来的行不计入。 */
export interface SalarySummary {
  parsed: number;
  /** 门槛来自当前 profile 的 `[score].salary_floor_wan`；没配就是 null */
  floorWan: number | null;
  meetsFloor: number;
  meetsFloorPct: number;
  avgHighWan: number;
}

/** 落库分数的新鲜度。概览靠它提醒「该重新打分了」。 */
export interface ScoreStatus {
  scored: number;
  /** 有 JD、却还没打分的条数 */
  missing: number;
  /** 落库分数用的信号表指纹与当前配置不一致 = 改过 [score] 但没重跑 */
  stale: boolean;
  scoredAt: string | null;
}

/**
 * LLM 打分的覆盖率与口径一致性。
 *
 * 和 `ScoreStatus` 的关键差别：这里**没有** `missing`。关键词打分是全库刷新，
 * 漏一条就是没跑；LLM 打分按条计费，「大部分没打过」是常态，不算待办。
 */
export interface LlmScoreStatus {
  /** 库里有 JD、够格送模型的条数 */
  scorable: number;
  /** 已打过分的条数 */
  scored: number;
  /** 其中用当前提示词 + 当前模型判的有几条 */
  current: number;
  /** 存在别的模型或旧提示词判出来的分数——和现在这批不可比 */
  stale: boolean;
  scoredAt: string | null;
}

export interface JobListResponse {
  total: number;
  /** 兜底上限，不是页大小。`total > jobs.length` 就是被截断了 */
  limit: number;
  jobs: JobRow[];
}

export interface KeywordsResponse {
  keywords: KeywordCount[];
}

export interface ApplyResponse {
  jobId: number;
  /** ok / already_applied / closed / failed */
  status: string;
  message: string;
  label: string;
}

export interface ApplicationEntry extends ApplicationRow {
  jobName: string;
  company: string;
  salary: string;
}

export interface ApplicationsResponse {
  total: number;
  statusCounts: Record<string, number>;
  applications: ApplicationEntry[];
}

/** `/api/stats`：库内数据概览。`details` / `applications` 是「状态 -> 条数」。 */
export interface OverviewResponse {
  jobs: number;
  details: Record<string, number>;
  applications: Record<string, number>;
  salary: SalarySummary;
  keywords: KeywordCount[];
  pendingDetails: number;
  score: ScoreStatus;
  llmScore: LlmScoreStatus;
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  jobs: number;
  tokenConfigured: boolean;
}

/** `config/models.py` 的 `ConfigPaths`：当前生效的关键路径，都是绝对路径。 */
export interface ConfigPaths {
  profile: string;
  root: string;
  configFile: string | null;
  profileDir: string;
  profileFile: string | null;
  database: string;
  resume: string;
  preferences: string;
  /** LLM 打分提示词的覆盖文件位置。**不存在很正常**——那表示用的是内置默认 */
  appealPrompt: string;
  fitPrompt: string;
}

/**
 * 配置树里 Web 端**读到的那部分**。
 *
 * 刻意不照抄整个 `Settings`：那是几十个字段的树，抄一份在这里等于把配置表
 * 写两份，加个字段就会对不上。要多读一项就在这里加一项。
 *
 * 密钥字段在后端是 `Secret`（`SecretStr | None`），序列化后是 `"**********"`
 * 或 `null`——所以这里只能判断「配了没配」，拿不到明文。
 */
export interface AppSettings {
  profile: { account: string };
  search: {
    address: string | null;
    salary_kind: string | null;
    /** 元/年，展示时自己换算成万 */
    salary_floor: number | null;
    keywords: string[];
  };
  liepin: {
    accounts: Record<string, { user_token: string | null }>;
    rate_limit_per_min: number;
  };
  score: ScoreSettings;
  llm_score: { provider: string | null; concurrency: number };
}

/** `[score]` 里的一条信号：命中就加 `weight`，负权重即减分项。 */
export interface ScoreSignal {
  name: string;
  weight: number;
  pattern: string;
}

/**
 * `config/models.py` 的 `ScoreConfig`：打分门槛 + 匹配信号表。
 *
 * 既是 `/api/config` 里读到的那一段，也是 `PUT /api/config/score` 的**请求体**
 * ——后端那边请求体就是 `ScoreConfig` 本身（`ScoreUpdate` 直接继承它），
 * 所以这里一个类型管两个方向，字段表只有一份。
 *
 * 后端是 `extra="forbid"`：多发一个字段会 422，字段名必须一字不差。
 */
export interface ScoreSettings {
  /** 万元/年，税前；null = 不按薪资过滤 */
  salary_floor_wan: number | null;
  /** 职位名命中时的权重倍数 */
  title_multiplier: number;
  /** 职位名与 JD 都没命中 pattern = 连赛道都不对，扣 penalty 压到末尾 */
  require: { pattern: string | null; penalty: number };
  signals: ScoreSignal[];
}

/** `POST /api/scores/refresh`：一次重新打分的结果（= 命令行的 `job score`）。 */
export interface ScoreRefreshResponse {
  /** 打分并落库的条数（全量，未按门槛过滤） */
  scored: number;
  /** 按 JD 正文去重后还剩多少条 */
  unique: number;
  offTrack: number;
  fingerprint: string;
  status: ScoreStatus;
}

export interface ConfigResponse {
  settings: AppSettings;
  paths: ConfigPaths;
}

// ---- LLM 打分提示词

/** 一个维度的提示词。`isDefault` 为真表示 profile 里没有覆盖文件。 */
export interface PromptView {
  content: string;
  isDefault: boolean;
  /** 覆盖文件该放的位置（不存在也给出来，好知道往哪写） */
  path: string;
}

/** `GET/PUT /api/config/prompts`。 */
export interface PromptsResponse {
  appeal: PromptView;
  fit: PromptView;
  /** 两段最终文本的指纹。它一变，库里已有的 LLM 分数就不再可比 */
  fingerprint: string;
  /** 这份提示词会配哪个模型跑（provider / model） */
  modelLabel: string;
}

/** 改写提示词。**空串 = 删掉覆盖文件、回到内置默认**，不是「存一份空的」。 */
export interface PromptsUpdate {
  appeal: string;
  fit: string;
}

// ---- 后台任务

export type TaskKind = "search" | "detail" | "llm_score";

export type TaskStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

/**
 * 采集任务的参数**快照**（`TaskView.params` 里回来的那份）。
 *
 * 后端每个字段都有默认值，所以响应里一定齐全——按 kind 只有其中一部分有意义，
 * 其余是默认值。
 */
export interface TaskParams {
  /** 仅 search：只搜这些关键词 */
  keywords: string[] | null;
  /** 仅 search：每个关键词翻几页（1–6） */
  pages: number | null;
  /** 仅 search：搜完接着抓 JD */
  fetch_detail: boolean;
  /** 抓 JD 时本次最多抓多少条 */
  limit: number | null;
  /** 抓 JD 时连之前失败的一起重试 */
  retry_failed: boolean;
  /** 仅 llm_score：给这些 jobId 打分（**必填**，按条计费，没有默认全打） */
  job_ids: number[] | null;
  /** 仅 llm_score：同模型同提示词已打过的也重打 */
  llm_force: boolean;
  /** 仅 llm_score：并发上限（1–16），省略取配置里的值 */
  llm_concurrency: number | null;
}

/**
 * 提交任务时给的参数：**省略哪项就用后端的默认值**，所以整体是 Partial。
 *
 * 跟 `TaskParams` 分开写不是重复：回来的快照一定齐全，发出去的可以只填几项，
 * 混成一个类型就得把响应也当成「可能没有」，读的时候要多判一次不存在的情况。
 */
export type TaskParamsInput = Partial<TaskParams>;

export interface CreateTaskRequest {
  kind: TaskKind;
  params: TaskParamsInput;
}

export interface SearchKeywordResult {
  keyword: string;
  found: number;
  new: number;
  truncated: boolean;
  error: string | null;
}

export interface DetailTaskResult {
  total: number;
  fetched: number;
  statuses: Record<string, number>;
  elapsedSeconds: number;
  abortedReason: string | null;
}

export interface SearchTaskResult {
  totalFound: number;
  totalNew: number;
  keywords: SearchKeywordResult[];
  /** 限流中止时未搜的关键词 */
  remaining: string[];
  /** params.fetch_detail 为真时，同一个任务顺带抓的 JD 结果 */
  detail: DetailTaskResult | null;
}

/** 一次批量 LLM 打分的账单。四个计数加起来 = requested。 */
export interface LlmScoreTaskResult {
  requested: number;
  scored: number;
  skipped: number;
  failed: number;
  cancelled: number;
  provider: string;
  model: string;
  fingerprint: string;
  errors: string[];
}

/** 任务产出。哪种取决于 kind，前端只原样展示，不按 kind 分支解读。 */
export type TaskResult = SearchTaskResult | DetailTaskResult | LlmScoreTaskResult;

export interface TaskView {
  id: string;
  kind: TaskKind;
  status: TaskStatus;
  params: TaskParams;
  message: string;
  current: number | null;
  total: number | null;
  percent: number | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  cancelRequested: boolean;
  result: TaskResult | null;
  error: string | null;
}

/** 任务详情：比列表多一份日志（列表接口刻意不带，几十个任务会把响应撑爆）。 */
export interface TaskDetail extends TaskView {
  logs: string[];
}

export interface TaskResponse {
  task: TaskDetail;
}

export interface TaskListResponse {
  tasks: TaskView[];
  /** 正在执行或排队中的任务 id */
  running: string | null;
}
