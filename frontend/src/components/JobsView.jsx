import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { formatTime } from "../format.js";

const PAGE_SIZE = 50;

const COLUMNS = [
  { key: "jobName", label: "职位" },
  { key: "company", label: "公司" },
  { key: "location", label: "地点" },
  { key: "salary", label: "薪资" },
  { key: "education", label: "学历" },
  { key: "workYears", label: "经验" },
  { key: "searchKeyword", label: "搜索关键词" },
];

const ORDERS = [
  { value: "recent", label: "最近采集" },
  { value: "salary", label: "薪资从高到低" },
  { value: "salary_asc", label: "薪资从低到高" },
];

export default function JobsView() {
  const [keywords, setKeywords] = useState([]);
  const [filters, setFilters] = useState({
    keyword: "",
    q: "",
    order: "recent",
    min_salary: "",
    has_detail: "",
    applied: "",
  });
  const [page, setPage] = useState(0);
  const [data, setData] = useState({ total: 0, jobs: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [detail, setDetail] = useState(null);
  const [applying, setApplying] = useState(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    api.keywords().then((d) => setKeywords(d.keywords)).catch(() => {});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .jobs({
        ...filters,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filters, page]);

  // 输入框防抖：搜索条件一变就等 250ms 再打请求
  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  const update = (patch) => {
    setPage(0);
    setFilters((prev) => ({ ...prev, ...patch }));
  };

  const toggleDetail = async (jobId) => {
    if (expanded === jobId) {
      setExpanded(null);
      return;
    }
    setExpanded(jobId);
    setDetail(null);
    try {
      setDetail(await api.job(jobId));
    } catch (e) {
      setError(e.message);
    }
  };

  const applyJob = async (job) => {
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
      setError(e.message);
    } finally {
      setApplying(null);
    }
  };

  const pages = Math.ceil(data.total / PAGE_SIZE);

  return (
    <>
      <div className="controls">
        <input
          className="search"
          placeholder="搜索职位名 / 公司…"
          value={filters.q}
          onChange={(e) => update({ q: e.target.value })}
        />
        <select value={filters.order} onChange={(e) => update({ order: e.target.value })}>
          {ORDERS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
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

      <div className="meta list-meta">
        命中 <b>{data.total}</b> 条{loading ? " · 加载中…" : ""}
        {pages > 1 && (
          <span className="pager">
            <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              上一页
            </button>
            第 {page + 1} / {pages} 页
            <button disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
              下一页
            </button>
          </span>
        )}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {data.jobs.map((job) => (
              <Fragment key={job.jobId}>
                <tr>
                  <td className="job-name">
                    <button className="link" onClick={() => toggleDetail(job.jobId)}>
                      {job.jobName}
                    </button>
                    {job.companyTags?.length > 0 && (
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
                      {detail && detail.jobId === job.jobId && (
                        <JobDetail detail={detail} />
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {data.jobs.length === 0 && !loading && (
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

function JobDetail({ detail }) {
  const jd = detail.detail;
  return (
    <div className="jd">
      {detail.applications?.length > 0 && (
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
