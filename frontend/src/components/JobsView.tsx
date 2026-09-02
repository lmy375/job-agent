import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import type { JobsQuery } from "../api";
import { formatTime } from "../format";
import type { JobBundle, JobListResponse, JobRow, KeywordCount } from "../types";

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
  | "jobName"
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
  { key: "jobName", label: "职位", get: (j) => j.jobName },
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
  min_salary: string;
  has_detail: string;
  applied: string;
}

interface Sort {
  key: SortKey;
  desc: boolean;
}

const EMPTY: JobListResponse = { total: 0, limit: 0, jobs: [] };

export default function JobsView() {
  const [keywords, setKeywords] = useState<KeywordCount[]>([]);
  const [filters, setFilters] = useState<Filters>({
    keyword: "",
    q: "",
    min_salary: "",
    has_detail: "",
    applied: "",
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

  const update = (patch: Partial<Filters>) => setFilters((prev) => ({ ...prev, ...patch }));

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
        <span className="muted">
          {" "}
          · 点表头排序 · 分数由 <code>job score</code> 落库，改了 [score] 记得重跑
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
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
                    <td colSpan={COLUMNS.length + 1}>
                      {!detail && <div className="muted">加载中…</div>}
                      {detail && detail.jobId === job.jobId && <JobDetail detail={detail} />}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {sorted.length === 0 && !loading && (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="empty">
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

/** 悬停时把命中/扣分理由摆出来：分数本身不可信，理由才让人能复核排序。 */
function scoreTitle(job: JobRow): string {
  const lines: string[] = [];
  if (job.scoreHits.length) lines.push(`+ ${job.scoreHits.join("、")}`);
  if (job.scorePenalties.length) lines.push(`− ${job.scorePenalties.join("、")}`);
  if (job.scoredAt) lines.push(`打分时间：${formatTime(job.scoredAt)}`);
  return lines.join("\n") || "无命中信号";
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
