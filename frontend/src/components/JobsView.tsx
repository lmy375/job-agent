import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { api, errorMessage } from "../api";
import type { JobsQuery } from "../api";
import { formatTime, jobKindLabel } from "../format";
import type { JobBundle, JobListResponse, JobRow, KeywordCount, LlmScoreTaskResult } from "../types";
import JobDrawer from "./JobDrawer";
import RescoreButton from "./RescoreButton";
import StatsStrip from "./StatsStrip";

/**
 * 职位列表。
 *
 * **刻意不分页**：本地单人用、职位数有限（一次采集几百到几千条），
 * 一次全取回来，排序与翻找都在浏览器里做——点表头即时重排，不用等请求。
 * 后端只在「命中数超过兜底上限」时才截断，那种情况下面会明说。
 *
 * 页面自上而下：**库存一览**（原「数据概览」页并进来的几张卡）、**操作区**
 * （重新打分、LLM 打分、批量选择）、筛选、表格。点一行在右侧拉出抽屉看细节与评估；
 * 批量模式下点一行是勾选。
 */

//: 可排序列的 key。写成联合类型而不是 string：排序状态里放了个不存在的列名，
//: 表现是「点了表头没反应」，编译期拦下来比在页面上找原因快
type SortKey =
  | "scoreRank"
  | "score"
  | "llmAppeal"
  | "llmFit"
  | "jobName"
  | "jobType"
  | "company"
  | "location"
  | "salary"
  | "education"
  | "workYears"
  | "searchKeyword";

//: 用来比较的值。null / undefined / 空串一律沉底，见下面的 sorted
type SortValue = string | number | null | undefined;

interface Column {
  key: SortKey;
  label: string;
  get: (job: JobRow) => SortValue;
  numeric?: boolean;
  className?: string;
}

//: 可点击排序的列。`get` 取出用来比较的值，null / undefined 一律排最后
const COLUMNS: Column[] = [
  { key: "scoreRank", label: "#", get: (j) => j.scoreRank, numeric: true, className: "rank" },
  { key: "score", label: "分", get: (j) => j.score, numeric: true, className: "score" },
  { key: "llmAppeal", label: "吸引", get: (j) => j.llmAppeal, numeric: true, className: "score" },
  { key: "llmFit", label: "胜任", get: (j) => j.llmFit, numeric: true, className: "score" },
  { key: "jobName", label: "职位", get: (j) => j.jobName },
  { key: "jobType", label: "来源", get: (j) => jobKindLabel(j.jobType) },
  { key: "company", label: "公司", get: (j) => j.company },
  { key: "location", label: "地点", get: (j) => j.location },
  { key: "salary", label: "薪资", get: (j) => j.salaryHighWan, numeric: true },
  { key: "education", label: "学历", get: (j) => j.education },
  { key: "workYears", label: "经验", get: (j) => j.workYears },
  { key: "searchKeyword", label: "搜索关键词", get: (j) => j.searchKeyword },
];

//: 后端排序只决定「被截断时留下哪些」，细排序在前端做
const FETCH_ORDER = "score" as const;

//: 单条打分任务的轮询间隔。任务在后台队列里跑，这里只是等它结束好刷新那一行
const POLL_MS = 2000;

/** 筛选条件都存成字符串：它们直接绑在 input / select 上，空串 = 不筛。 */
interface Filters {
  keyword: string;
  q: string;
  /** `""` 两类都看 / `"2"` 只看 HR 岗位 / `"1"` 只看猎头岗位 */
  job_type: string;
  min_salary: string;
  has_detail: string;
  applied: string;
  llm_scored: string;
}

interface Sort {
  key: SortKey;
  desc: boolean;
}

const EMPTY: JobListResponse = { total: 0, limit: 0, jobs: [] };

export default function JobsView({ onTaskCreated }: { onTaskCreated?: () => void }) {
  const [keywords, setKeywords] = useState<KeywordCount[]>([]);
  const [filters, setFilters] = useState<Filters>({
    keyword: "",
    q: "",
    job_type: "",
    min_salary: "",
    has_detail: "",
    applied: "",
    llm_scored: "",
  });
  //: 排序状态：列 key + 方向。默认按分数从高到低（分诊结果就是拿来这么看的）
  const [sort, setSort] = useState<Sort>({ key: "score", desc: true });
  const [data, setData] = useState<JobListResponse>(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  //: 抽屉里打开的那条。`detail` 是它的完整包，请求没回来之前为 null
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<JobBundle | null>(null);
  const [applying, setApplying] = useState<number | null>(null);
  //: 批量选择模式。**只有开了它复选框才出现**——平时那一列只是在几十行里抢视线
  const [selecting, setSelecting] = useState(false);
  //: 勾中的 jobId。LLM 打分按条计费，所以「打哪些」必须是人明确选出来的
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  //: 正在被单条打分的 jobId → 后台任务 id。行上的按钮据此显示「打分中」
  const [scoring, setScoring] = useState<Map<number, string>>(new Map());
  //: 每次列表重新取数就 +1，顶部库存卡跟着刷新——打完分、投完递数字得同步
  const [statsToken, setStatsToken] = useState(0);

  useEffect(() => {
    api.keywords().then((d) => setKeywords(d.keywords)).catch(() => {});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    setStatsToken((n) => n + 1);
    const params: JobsQuery = { ...filters, order: FETCH_ORDER };
    api
      .jobs(params)
      .then(setData)
      .catch((e: unknown) => setError(errorMessage(e)))
      .finally(() => setLoading(false));
  }, [filters]);

  // 输入框防抖：筛选条件一变就等 250ms 再打请求
  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  //: 换筛选条件就清空勾选：勾了 30 条、一改关键词只剩 3 条在屏幕上，
  //: 然后点「给选中的打分」——花的是那 30 条的钱，看不见的那 27 条最容易出事
  const update = (patch: Partial<Filters>) => {
    setSelected(new Set());
    setFilters((prev) => ({ ...prev, ...patch }));
  };

  const toggleSort = (key: SortKey) => {
    setSort((prev) => {
      if (prev.key !== key) {
        // 换列时给个合理的初始方向：分数、薪资、名次这类数字列先看「最靠前的」
        const column = COLUMNS.find((c) => c.key === key);
        return { key, desc: column?.numeric ? key !== "scoreRank" : false };
      }
      return { key, desc: !prev.desc };
    });
  };

  const sorted = useMemo(() => {
    const column = COLUMNS.find((c) => c.key === sort.key);
    if (!column) return data.jobs;
    const dir = sort.desc ? -1 : 1;
    return [...data.jobs].sort((a, b) => {
      const x = column.get(a);
      const y = column.get(b);
      // 没值的一律沉底，不管升序降序——「没打分」不是「分最低」
      const xMissing = x === null || x === undefined || x === "";
      const yMissing = y === null || y === undefined || y === "";
      if (xMissing || yMissing) return xMissing && yMissing ? 0 : xMissing ? 1 : -1;
      if (column.numeric) return (Number(x) - Number(y)) * dir;
      return String(x).localeCompare(String(y), "zh") * dir;
    });
  }, [data.jobs, sort]);

  // ---------------------------------------------------------------- 批量选择

  const toggleSelecting = () => {
    setSelecting((on) => !on);
    setSelected(new Set());
  };

  const toggleOne = (jobId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(jobId)) next.add(jobId);
      return next;
    });
  };

  const allSelected = sorted.length > 0 && sorted.every((j) => selected.has(j.jobId));
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(sorted.map((j) => j.jobId)));

  // ---------------------------------------------------------------- LLM 打分

  /** 批量：把一批 jobId 送进 LLM 打分任务。**按条计费，所以每次都要人点头。** */
  const runLlmScoreBatch = async (ids: number[]) => {
    if (!ids.length) return;
    const ok = window.confirm(
      `将对 ${ids.length} 条职位调用模型打分。\n\n` +
        "按条计费；同模型、同提示词已经打过的会自动跳过。\n" +
        "任务在后台跑，进度和日志在「采集任务」页看，可以随时取消。"
    );
    if (!ok) return;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const { task } = await api.createTask({ kind: "llm_score", params: { job_ids: ids } });
      setNotice(`已提交 LLM 打分任务 ${task.id}（${ids.length} 条），去「采集任务」看进度。`);
      setSelected(new Set());
      setSelecting(false);
      onTaskCreated?.();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  };

  /**
   * 单条：行上那颗按钮。一次点击 = 一条 = 一次计费，点击本身就是确认，不再弹窗。
   * 已经打过的行会**强制重打**——否则点了只会被「口径没变默认跳过」吃掉，什么都不发生。
   * 任务仍然走后台队列，这里留在本页轮询，结束了只刷新列表，不跳走。
   */
  const runLlmScoreOne = async (job: JobRow) => {
    if (scoring.has(job.jobId)) return;
    setError("");
    setNotice("");
    try {
      const { task } = await api.createTask({
        kind: "llm_score",
        params: { job_ids: [job.jobId], llm_force: job.llmAppeal !== null },
      });
      setScoring((prev) => new Map(prev).set(job.jobId, task.id));
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  //: 用 ref 拿最新的 openId，轮询回调里才不会读到过期的闭包
  const openIdRef = useRef(openId);
  openIdRef.current = openId;

  useEffect(() => {
    if (scoring.size === 0) return;
    const timer = setInterval(async () => {
      let touched = false;
      for (const [jobId, taskId] of scoring) {
        try {
          const { task } = await api.task(taskId);
          if (task.status === "pending" || task.status === "running") continue;
          touched = true;
          setScoring((prev) => {
            const next = new Map(prev);
            next.delete(jobId);
            return next;
          });
          if (task.status === "succeeded" && task.result) {
            setNotice(`[${jobId}] ${describeLlmResult(task.result as LlmScoreTaskResult)}`);
          } else if (task.status === "failed") {
            setError(`[${jobId}] LLM 打分失败：${task.error ?? "未知原因"}`);
          } else {
            setNotice(`[${jobId}] LLM 打分任务已取消。`);
          }
          // 抽屉正开着这条就一起刷新，评估结果直接出现在眼前
          if (openIdRef.current === jobId) {
            api.job(jobId).then(setDetail).catch(() => {});
          }
        } catch (e) {
          setError(errorMessage(e));
        }
      }
      if (touched) load();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [scoring, load]);

  // ---------------------------------------------------------------- 抽屉

  const openDrawer = useCallback(async (jobId: number) => {
    setOpenId(jobId);
    setDetail(null);
    try {
      setDetail(await api.job(jobId));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  const closeDrawer = useCallback(() => {
    setOpenId(null);
    setDetail(null);
  }, []);

  /** 点整行：批量模式下是勾选，否则打开抽屉。行内的按钮、链接、复选框自己处理，不冒泡到这里。 */
  const onRowClick = (e: MouseEvent<HTMLTableRowElement>, job: JobRow) => {
    const target = e.target as HTMLElement;
    if (target.closest("button, a, input, label")) return;
    if (selecting) toggleOne(job.jobId);
    else openDrawer(job.jobId);
  };

  // ---------------------------------------------------------------- 投递

  const applyJob = async (job: JobRow) => {
    // 投递不可撤销，必须先确认
    const ok = window.confirm(
      `确认投递？\n\n${job.jobName}\n${job.company} · ${job.salary}\n\n` +
        "猎聘没有撤回投递的接口，投出去就无法取消。"
    );
    if (!ok) return;
    setApplying(job.jobId);
    setNotice("");
    try {
      const result = await api.applyJob(job.jobId);
      setNotice(`[${job.jobId}] ${result.message}`);
      load();
      if (openId === job.jobId) api.job(job.jobId).then(setDetail).catch(() => {});
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setApplying(null);
    }
  };

  const truncated = data.total > data.jobs.length;
  const openJob = openId === null ? null : (data.jobs.find((j) => j.jobId === openId) ?? null);
  const colSpan = COLUMNS.length + 1 + (selecting ? 1 : 0);

  return (
    <>
      <StatsStrip refreshToken={statsToken} />

      {/* 操作区：会改库、会花钱的动作都在这一排，和筛选条件分开 */}
      <div className="toolbar">
        <div className="toolbar-group">
          <RescoreButton onDone={load} />
          <span className="divider" />
          <button
            className="btn small ghost"
            disabled={submitting || sorted.length === 0}
            onClick={() => runLlmScoreBatch(sorted.map((j) => j.jobId))}
            title="给当前筛选结果里的全部职位做 LLM 打分（按条计费，已用同一模型与提示词打过的会自动跳过）"
          >
            LLM 打分当前 {sorted.length} 条
          </button>
          <button
            className={selecting ? "btn small ghost active" : "btn small ghost"}
            onClick={toggleSelecting}
            title="进入批量选择：每行出现复选框，点行即勾选，然后给选中的做 LLM 打分"
          >
            {selecting ? "退出批量选择" : "批量选择"}
          </button>
        </div>
        <div className="toolbar-meta">
          命中 <b>{data.total}</b> 条{loading ? " · 加载中…" : ""}
          <span className="muted"> · 点表头排序 · 点行看详情</span>
        </div>
      </div>

      {selecting && (
        <div className="bulkbar">
          <span className={selected.size ? "" : "muted"}>
            已选 <b>{selected.size}</b> 条
          </span>
          <button className="btn small ghost" onClick={toggleAll} disabled={sorted.length === 0}>
            {allSelected ? "取消全选" : `全选当前 ${sorted.length} 条`}
          </button>
          <button
            className="btn small"
            disabled={submitting || selected.size === 0}
            onClick={() => runLlmScoreBatch([...selected])}
            title="让模型给选中的职位打两个维度的分（岗位吸引力 / 胜任匹配度）"
          >
            {submitting ? "提交中…" : `给选中的 ${selected.size} 条 LLM 打分`}
          </button>
          <span className="muted">
            按条计费，已用同一模型与提示词打过的会自动跳过；换筛选条件会清空勾选。
          </span>
        </div>
      )}

      <div className="controls">
        <input
          className="search"
          placeholder="搜索职位名 / 公司…"
          value={filters.q}
          onChange={(e) => update({ q: e.target.value })}
        />
        <label>
          年薪上限 ≥
          <input
            className="num"
            type="number"
            min="0"
            step="10"
            placeholder="万元"
            value={filters.min_salary}
            onChange={(e) => update({ min_salary: e.target.value })}
          />
          万
        </label>
        <select value={filters.job_type} onChange={(e) => update({ job_type: e.target.value })}>
          <option value="">岗位来源：全部</option>
          <option value="2">只看 HR 岗位</option>
          <option value="1">只看猎头岗位</option>
        </select>
        <select value={filters.has_detail} onChange={(e) => update({ has_detail: e.target.value })}>
          <option value="">JD：全部</option>
          <option value="true">已抓到 JD</option>
          <option value="false">未抓到 JD</option>
        </select>
        <select value={filters.applied} onChange={(e) => update({ applied: e.target.value })}>
          <option value="">投递：全部</option>
          <option value="true">已投递</option>
          <option value="false">未投递</option>
        </select>
        <select
          value={filters.llm_scored}
          onChange={(e) => update({ llm_scored: e.target.value })}
        >
          <option value="">LLM 打分：全部</option>
          <option value="true">已打分</option>
          <option value="false">未打分</option>
        </select>
      </div>

      <div className="chips">
        <button
          className={filters.keyword === "" ? "chip active" : "chip"}
          onClick={() => update({ keyword: "" })}
        >
          全部
        </button>
        {keywords.map((k) => (
          <button
            key={k.keyword}
            className={filters.keyword === k.keyword ? "chip active" : "chip"}
            onClick={() => update({ keyword: k.keyword })}
          >
            {k.keyword} <span className="count">{k.count}</span>
          </button>
        ))}
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert">{notice}</div>}
      {truncated && (
        <div className="alert error">
          命中 {data.total} 条，只返回了前 {data.jobs.length} 条（后端兜底上限{" "}
          {data.limit}）。下面的排序只在这批里生效——收紧筛选条件再看。
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {selecting && (
                <th className="pick">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    title="全选当前筛选结果（换筛选条件会清空勾选）"
                  />
                </th>
              )}
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className={sort.key === c.key ? "sortable sorted" : "sortable"}
                  onClick={() => toggleSort(c.key)}
                  title="点击按这一列排序"
                >
                  {c.label}
                  {sort.key === c.key && <span className="arrow">{sort.desc ? "↓" : "↑"}</span>}
                </th>
              ))}
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((job) => (
              <tr
                key={job.jobId}
                className={rowClass(job, {
                  active: openId === job.jobId,
                  picked: selecting && selected.has(job.jobId),
                })}
                onClick={(e) => onRowClick(e, job)}
              >
                {selecting && (
                  <td className="pick">
                    <input
                      type="checkbox"
                      checked={selected.has(job.jobId)}
                      onChange={() => toggleOne(job.jobId)}
                    />
                  </td>
                )}
                <td className="rank">{job.scoreRank ?? "—"}</td>
                <td className="score">
                  {job.score === null ? (
                    <span className="muted" title="还没打分：抓到 JD 后点「重新打分」">
                      —
                    </span>
                  ) : (
                    <span title={scoreTitle(job)}>{Math.round(job.score)}</span>
                  )}
                </td>
                <td className="score">
                  <LlmCell value={job.llmAppeal} reasons={job.llmAppealReasons} job={job} />
                </td>
                <td className="score">
                  <LlmCell value={job.llmFit} reasons={job.llmFitReasons} job={job} />
                </td>
                <td className="job-name">
                  {job.jobName}
                  {job.companyTags.length > 0 && (
                    <span className="tags">
                      {job.companyTags.slice(0, 3).map((t) => (
                        <span key={t} className="tag">
                          {t}
                        </span>
                      ))}
                    </span>
                  )}
                </td>
                <td>
                  <span className={job.jobType === "1" ? "kind hunter" : "kind"}>
                    {jobKindLabel(job.jobType)}
                  </span>
                </td>
                <td>
                  {job.company}
                  {job.companySize && <div className="sub">{job.companySize}</div>}
                </td>
                <td>{job.location}</td>
                <td className="salary">
                  {job.salary}
                  {job.salaryHighWan && <div className="sub">≈{job.salaryHighWan} 万/年</div>}
                </td>
                <td>{job.education}</td>
                <td>{job.workYears}</td>
                <td>
                  <span className="kw">{job.searchKeyword}</span>
                </td>
                <td className="actions">
                  {job.jobDetailUrl && (
                    <a href={job.jobDetailUrl} target="_blank" rel="noreferrer" title="打开猎聘原页">
                      原页
                    </a>
                  )}
                  <button
                    className="btn small ghost"
                    disabled={scoring.has(job.jobId)}
                    onClick={() => runLlmScoreOne(job)}
                    title={
                      job.llmAppeal === null
                        ? "只给这一条做 LLM 打分（按条计费，点击即提交）"
                        : "已打过分；再点会用当前模型与提示词强制重打"
                    }
                  >
                    {scoring.has(job.jobId) ? "打分中…" : job.llmAppeal === null ? "LLM" : "重打"}
                  </button>
                  <button
                    className="btn small"
                    disabled={applying === job.jobId}
                    onClick={() => applyJob(job)}
                  >
                    {applying === job.jobId ? "投递中…" : "投递"}
                  </button>
                </td>
              </tr>
            ))}
            {sorted.length === 0 && !loading && (
              <tr>
                <td colSpan={colSpan} className="empty">
                  没有数据。先在「采集任务」里跑一次搜索。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {openJob && (
        <JobDrawer
          job={openJob}
          detail={detail && detail.jobId === openJob.jobId ? detail : null}
          scoring={scoring.has(openJob.jobId)}
          applying={applying === openJob.jobId}
          onClose={closeDrawer}
          onLlmScore={runLlmScoreOne}
          onApply={applyJob}
        />
      )}
    </>
  );
}

function rowClass(job: JobRow, state: { active: boolean; picked: boolean }): string {
  const classes = ["clickable"];
  if (job.offTrack) classes.push("off-track");
  if (state.active) classes.push("active");
  if (state.picked) classes.push("selected");
  return classes.join(" ");
}

/** 单条打分任务跑完后给人看的一句话：四个计数里非零的那个才是发生了的事。 */
function describeLlmResult(result: LlmScoreTaskResult): string {
  if (result.failed) return `LLM 打分失败：${result.errors[0] ?? "未知原因"}`;
  if (result.skipped) return "LLM 打分已跳过：同模型、同提示词已打过（要重打就再点一次）。";
  if (result.scored) return `LLM 打分完成（${result.provider} / ${result.model}）。`;
  return "LLM 打分任务结束。";
}

/**
 * 一个 LLM 分数格。没打过就是一个破折号——**不写 0**：
 * 「没判过」和「判了 1 分」是两回事，混成同一个数字会让排序骗人。
 */
function LlmCell({
  value,
  reasons,
  job,
}: {
  value: number | null;
  reasons: string[];
  job: JobRow;
}) {
  if (value === null) {
    return (
      <span className="muted" title="还没送模型打分：点这一行右侧的「LLM」">
        —
      </span>
    );
  }
  const lines = [...reasons];
  if (job.llmModel) lines.push(`模型：${job.llmProvider} / ${job.llmModel}`);
  if (job.llmScoredAt) lines.push(`打分时间：${formatTime(job.llmScoredAt)}`);
  return <span title={lines.join("\n")}>{value}</span>;
}

/** 悬停时把命中/扣分理由摆出来：分数本身不可信，理由才让人能复核排序。 */
function scoreTitle(job: JobRow): string {
  const lines: string[] = [];
  if (job.scoreHits.length) lines.push(`+ ${job.scoreHits.join("、")}`);
  if (job.scorePenalties.length) lines.push(`− ${job.scorePenalties.join("、")}`);
  if (job.scoredAt) lines.push(`打分时间：${formatTime(job.scoredAt)}`);
  return lines.join("\n") || "无命中信号";
}
