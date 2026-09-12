import { useEffect } from "react";
import type { ReactNode } from "react";
import { formatTime, jobKindLabel } from "../format";
import type { JobBundle, JobRow } from "../types";

/**
 * 右侧抽屉：一条职位的全部细节与评估。
 *
 * 点表格里任意一行就打开，覆盖在列表右侧而不是插进表格里——列表保持原样，
 * 眼睛不用在几十行里找刚才展开的那一条；换一行看只是换抽屉里的内容。
 * Esc、点遮罩、点右上角都能关。
 */
export default function JobDrawer({
  job,
  detail,
  scoring,
  applying,
  onClose,
  onLlmScore,
  onApply,
}: {
  /** 列表里的那一行：抽屉一打开就有，不用等详情请求 */
  job: JobRow;
  /** 详情请求回来的完整包；还没回来时为 null */
  detail: JobBundle | null;
  scoring: boolean;
  applying: boolean;
  onClose: () => void;
  onLlmScore: (job: JobRow) => void;
  onApply: (job: JobRow) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // 抽屉开着时锁住页面滚动：滚轮该滚的是抽屉里的 JD，不是底下的列表
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  //: 分数字段两边都有，详情回来之前先用列表那份，别让抽屉一开先闪一下空白
  const row: JobRow = detail ?? job;
  const jd = detail?.detail ?? null;
  const applied = (detail?.applications ?? []).some((a) => a.status === "ok");

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={job.jobName}>
        <header className="drawer-head">
          <div className="drawer-title">
            <h2>{job.jobName}</h2>
            <div className="drawer-sub">
              <span>{job.company}</span>
              {job.companySize && <span>{job.companySize}</span>}
              {job.financingStage && <span>{job.financingStage}</span>}
              <span className={job.jobType === "1" ? "kind hunter" : "kind"}>
                {jobKindLabel(job.jobType)}
              </span>
            </div>
          </div>
          <button className="icon-btn" onClick={onClose} title="关闭（Esc）" aria-label="关闭">
            ×
          </button>
        </header>

        <div className="drawer-body">
          <div className="fact-grid">
            <Fact label="薪资">
              <span className="salary">{job.salary}</span>
              {job.salaryHighWan !== null && (
                <span className="sub">
                  ≈ {job.salaryLowWan ?? "?"}–{job.salaryHighWan} 万/年（税前）
                </span>
              )}
            </Fact>
            <Fact label="地点">{job.location || "—"}</Fact>
            <Fact label="学历">{job.education || "—"}</Fact>
            <Fact label="经验">{job.workYears || "—"}</Fact>
            <Fact label="行业">{job.industry || jd?.industry || "—"}</Fact>
            <Fact label="搜索关键词">
              <span className="kw">{job.searchKeyword}</span>
            </Fact>
          </div>
          {job.companyTags.length > 0 && (
            <div className="tags wrap">
              {job.companyTags.map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
          )}

          <div className="drawer-actions">
            {job.jobDetailUrl && (
              <a className="btn small ghost" href={job.jobDetailUrl} target="_blank" rel="noreferrer">
                打开原页 ↗
              </a>
            )}
            <button
              className="btn small ghost"
              disabled={scoring}
              onClick={() => onLlmScore(row)}
              title={
                row.llmAppeal === null
                  ? "让模型读 JD 与简历，给岗位吸引力 / 胜任匹配度各打一分"
                  : "已打过分；再打会用当前模型与提示词强制重判"
              }
            >
              {scoring ? "打分中…" : row.llmAppeal === null ? "LLM 打分" : "重新 LLM 打分"}
            </button>
            <button
              className="btn small"
              disabled={applying || applied}
              onClick={() => onApply(job)}
              title={applied ? "已投递过这条职位" : "投递不可撤销，点击后会再确认一次"}
            >
              {applying ? "投递中…" : applied ? "已投递" : "投递"}
            </button>
          </div>

          <Section title="关键词分诊" hint="只做分诊：把几百条砍到几十条，该不该投要读 JD">
            {row.score === null ? (
              <p className="muted">还没打分：抓到 JD 后点顶部的「重新打分」。</p>
            ) : (
              <>
                <div className="score-line">
                  <b className="big">{Math.round(row.score)}</b>
                  <span className="muted">
                    分 · 全库第 {row.scoreRank ?? "—"} 名
                    {row.offTrack && <span className="badge warn">未命中目标赛道</span>}
                  </span>
                </div>
                <Reasons title="加分" items={row.scoreHits} sign="+" />
                <Reasons title="扣分" items={row.scorePenalties} sign="−" />
                {row.scoredAt && <div className="sub">打分时间：{formatTime(row.scoredAt)}</div>}
              </>
            )}
          </Section>

          <Section title="LLM 评估" hint="两个分数并列，不合成总分">
            {row.llmAppeal === null || row.llmFit === null ? (
              <p className="muted">
                还没送模型打分。点上面的「LLM 打分」，按条计费，结果会落库并显示在这里。
              </p>
            ) : (
              <>
                <div className="llm-grid">
                  <div className="llm-box">
                    <div className="llm-num">
                      {row.llmAppeal}
                      <span className="denom">/10</span>
                    </div>
                    <div className="llm-label">岗位吸引力</div>
                    <div className="sub">这份工作值不值</div>
                    <Reasons items={row.llmAppealReasons} />
                  </div>
                  <div className="llm-box">
                    <div className="llm-num">
                      {row.llmFit}
                      <span className="denom">/10</span>
                    </div>
                    <div className="llm-label">胜任匹配度</div>
                    <div className="sub">你够不够格</div>
                    <Reasons items={row.llmFitReasons} />
                  </div>
                </div>
                <div className="sub">
                  模型：{row.llmProvider} / {row.llmModel}
                  {row.llmScoredAt ? ` · ${formatTime(row.llmScoredAt)}` : ""}
                </div>
              </>
            )}
          </Section>

          {detail && detail.applications.length > 0 && (
            <Section title="投递记录">
              <ul className="plain">
                {detail.applications.map((a) => (
                  <li key={a.id}>
                    <span className={`badge ${a.status === "ok" ? "succeeded" : "failed"}`}>
                      {a.status}
                    </span>{" "}
                    {formatTime(a.appliedAt)} · {a.message}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="职位描述">
            {!detail && <p className="muted">加载中…</p>}
            {detail && !jd && (
              <p className="muted">还没抓过这条职位的 JD（去「采集任务」跑一次抓详情）。</p>
            )}
            {jd && (
              <>
                <div className="jd-meta">
                  {jd.experienceRequirements && <span>经验：{jd.experienceRequirements}</span>}
                  {jd.educationRequirements && <span>学历：{jd.educationRequirements}</span>}
                  {jd.employmentType && <span>类型：{jd.employmentType}</span>}
                  {jd.datePosted && <span>发布：{jd.datePosted}</span>}
                  {jd.streetAddress && <span>地址：{jd.streetAddress}</span>}
                  <span>抓取状态：{jd.status}</span>
                </div>
                <pre className="jd-text">{jd.description || "（无正文）"}</pre>
              </>
            )}
          </Section>
        </div>
      </aside>
    </>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="fact">
      <div className="fact-label">{label}</div>
      <div className="fact-value">{children}</div>
    </div>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="drawer-section">
      <h3>
        {title}
        {hint && <span className="hint">{hint}</span>}
      </h3>
      {children}
    </section>
  );
}

function Reasons({ title, items, sign }: { title?: string; items: string[]; sign?: string }) {
  if (!items.length) return null;
  return (
    <div className="reasons">
      {title && <span className="reasons-title">{title}</span>}
      <ul className={sign ? "signed" : undefined}>
        {items.map((text) => (
          <li key={text}>
            {sign && <span className="sign">{sign} </span>}
            {text}
          </li>
        ))}
      </ul>
    </div>
  );
}
