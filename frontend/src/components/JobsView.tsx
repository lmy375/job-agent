import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import type { JobsQuery } from "../api";
import { formatTime, jobKindLabel } from "../format";
import type { JobBundle, JobListResponse, JobRow, KeywordCount } from "../types";
import RescoreButton from "./RescoreButton";

/**
 * 职位列表。
 *
 * **刻意不分页**：本地单人用、职位数有限（一次采集几百到几千条），
 * 一次全取回来，排序与翻找都在浏览器里做——点表头即时重排，不用等请求。
 * 后端只在「命中数超过兜底上限」时才截断，那种情况下面会明说。
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
  const [expanded, setExpanded] = useState<number | null>(null);
  const [detail, setDetail] = useState<JobBundle | null>(null);
  const [applying, setApplying] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  //: 勾中的 jobId。LLM 打分按条计费，所以「打哪些」必须是人明确选出来的
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.keywords().then((d) => setKeywords(d.keywords)).catch(() => {});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
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

  const toggleOne = (jobId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(jobId)) next.add(jobId);
      return next;
    });
  };

  const allSelected = sorted.length > 0 && sorted.every((j) => selected.has(j.jobId));
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(sorted.map((j) => j.jobId)));

  /** 把一批 jobId 送进 LLM 打分任务。**按条计费，所以每次都要人点头。** */
  const runLlmScore = async (ids: number[]) => {
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
      onTaskCreated?.();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  };

  const toggleDetail = async (jobId: number) => {
    if (expanded === jobId) {
      setExpanded(null);
      return;
    }
    setExpanded(jobId);
    setDetail(null);
    try {
      setDetail(await api.job(jobId));
    } catch (e) {
      setError(errorMessage(e));
    }
  };

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
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setApplying(null);
    }
  };

  const truncated = data.total > data.jobs.length;

  return (
    <>
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

      <div className="meta list-meta">
        命中 <b>{data.total}</b> 条{loading ? " · 加载中…" : ""}
        <span className="muted"> · 点表头排序 · 分数落库后会过期，改了打分逻辑就重打一次</span>
        <RescoreButton onDone={load} />
      </div>

      <div className="bulkbar">
        <span className={selected.size ? "" : "muted"}>已选 {selected.size} 条</span>
        <button
          className="btn small"
          disabled={submitting || selected.size === 0}
          onClick={() => runLlmScore([...selected])}
          title="让模型给选中的职位打两个维度的分（岗位吸引力 / 胜任匹配度）"
        >
          {submitting ? "提交中…" : "给选中的 LLM 打分"}
        </button>
        <button
          className="btn small ghost"
          disabled={submitting || sorted.length === 0}
          onClick={() => runLlmScore(sorted.map((j) => j.jobId))}
          title="给当前筛选结果里的全部职位打分"
        >
          打分当前 {sorted.length} 条
        </button>
        <span className="muted">
          按条计费，已用同一模型与提示词打过的会自动跳过；口径与提示词在「配置」页改。
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="pick">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  title="全选当前筛选结果（换筛选条件会清空勾选）"
                />
              </th>
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
              <Fragment key={job.jobId}>
                <tr className={job.offTrack ? "off-track" : undefined}>
                  <td className="pick">
                    <input
                      type="checkbox"
                      checked={selected.has(job.jobId)}
                      onChange={() => toggleOne(job.jobId)}
                    />
                  </td>
                  <td className="rank">{job.scoreRank ?? "—"}</td>
                  <td className="score">
                    {job.score === null ? (
                      <span className="muted" title="还没打分：抓到 JD 后跑 job score">
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
                    <button className="link" onClick={() => toggleDetail(job.jobId)}>
                      {job.jobName}
                    </button>
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
                      <a href={job.jobDetailUrl} target="_blank" rel="noreferrer">
                        原页
                      </a>
                    )}
                    <button
                      className="btn small"
                      disabled={applying === job.jobId}
                      onClick={() => applyJob(job)}
                    >
                      {applying === job.jobId ? "投递中…" : "投递"}
                    </button>
                  </td>
                </tr>
                {expanded === job.jobId && (
                  <tr className="detail-row">
                    <td colSpan={COLUMNS.length + 2}>
                      {!detail && <div className="muted">加载中…</div>}
                      {detail && detail.jobId === job.jobId && <JobDetail detail={detail} />}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {sorted.length === 0 && !loading && (
              <tr>
                <td colSpan={COLUMNS.length + 2} className="empty">
                  没有数据。先在「采集任务」里跑一次搜索。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
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
      <span className="muted" title="还没送模型打分：勾上这一行，点上面的「LLM 打分」">
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

function Reasons({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="reasons">
      <span className="reasons-title">{title}</span>
      <ul>
        {items.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </div>
  );
}

function JobDetail({ detail }: { detail: JobBundle }) {
  const jd = detail.detail;
  // 解构出来 TS 才能顺着 `score !== null` 收窄类型。score / scoreRank / hits
  // 是同一次 job score 一起落库的，有命中信号就一定有分数
  const { score } = detail;
  const hasSignals = detail.scoreHits.length > 0 || detail.scorePenalties.length > 0;
  return (
    <div className="jd">
      {score !== null && hasSignals && (
        <div className="jd-meta">
          <span>
            分 {Math.round(score)} · 全库第 {detail.scoreRank} 名
          </span>
          {detail.scoreHits.length > 0 && <span>命中：{detail.scoreHits.join("、")}</span>}
          {detail.scorePenalties.length > 0 && (
            <span>扣分：{detail.scorePenalties.join("、")}</span>
          )}
          <span className="muted">分数只做分诊，该不该投要读下面的 JD</span>
        </div>
      )}
      {detail.llmAppeal !== null && (
        <div className="llm-verdict">
          <div className="jd-meta">
            <span>
              岗位吸引力 <b>{detail.llmAppeal}</b>/10 · 胜任匹配度 <b>{detail.llmFit}</b>/10
            </span>
            <span className="muted">
              {detail.llmProvider} / {detail.llmModel}
              {detail.llmScoredAt ? ` · ${formatTime(detail.llmScoredAt)}` : ""}
            </span>
            <span className="muted">两个分数并列，不合成总分</span>
          </div>
          <Reasons title="值不值得投" items={detail.llmAppealReasons} />
          <Reasons title="够不够得着" items={detail.llmFitReasons} />
        </div>
      )}
      {detail.applications.length > 0 && (
        <div className="alert">
          投递记录：
          {detail.applications.map((a) => (
            <div key={a.id}>
              {formatTime(a.appliedAt)} · {a.status} · {a.message}
            </div>
          ))}
        </div>
      )}
      {!jd && <div className="muted">还没抓过这条职位的 JD（去「采集任务」跑一次抓详情）。</div>}
      {jd && (
        <>
          <div className="jd-meta">
            {jd.industry && <span>行业：{jd.industry}</span>}
            {jd.experienceRequirements && <span>经验：{jd.experienceRequirements}</span>}
            {jd.educationRequirements && <span>学历：{jd.educationRequirements}</span>}
            {jd.datePosted && <span>发布：{jd.datePosted}</span>}
            <span>抓取状态：{jd.status}</span>
          </div>
          <pre>{jd.description || "（无正文）"}</pre>
        </>
      )}
    </div>
  );
}
