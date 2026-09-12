import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { formatTime } from "../format";
import type { LlmScoreStatus, OverviewResponse, ScoreStatus } from "../types";

/**
 * 职位页顶部的库存一览：**只报库存，不做分析**。
 *
 * 多少职位、抓了多少 JD、投了多少、薪资什么水位、分数新不新鲜。
 * 它原来是单独一个「数据概览」页，合并进职位页是因为这些数字的用途只有一个：
 * 决定下一步在列表上做什么——分数过期就点「重新打分」，JD 没抓就去采集。
 * 数字和动作分在两页，看到提醒还得切过去，等于没提醒。
 * 赛道 / 技能分布这类市场分析不在这个仓库里（见 CLAUDE.md）。
 */

/** 落库分数的新鲜度：过期或有漏打的必须说出来，不能让人把旧分数当成现在的。 */
function scoreNote(score: ScoreStatus): { text: string; warn: boolean } {
  if (score.scored === 0) return { text: "还没打过分，点右边「重新打分」", warn: true };
  if (score.stale) return { text: "打分逻辑改过但没重算，点「重新打分」", warn: true };
  if (score.missing > 0) return { text: `${score.missing} 条有 JD 却没打分，点「重新打分」`, warn: true };
  return { text: `最近 ${formatTime(score.scoredAt)}`, warn: false };
}

/**
 * LLM 打分的覆盖率提示。
 *
 * 「还有多少没打」刻意**不**说成待办：按条计费，大部分没打过是常态，
 * 天天喊「还差 3000 条」只会让人学会忽略这一格。真该提醒的是口径不一致——
 * 库里混着别的模型或旧提示词判出来的分数，那些和现在这批没法比。
 */
function llmNote(llm: LlmScoreStatus): { text: string; warn: boolean } {
  if (llm.scored === 0) return { text: "还没打过，点行末的「LLM」试一条", warn: false };
  if (llm.stale)
    return { text: `${llm.scored - llm.current} 条是别的模型或旧提示词判的，不可比`, warn: true };
  return { text: `最近 ${formatTime(llm.scoredAt)}`, warn: false };
}

export default function StatsStrip({ refreshToken }: { refreshToken: number }) {
  const [stats, setStats] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState("");

  //: 列表每次重新取数就跟着刷一次：打完分、投完递，卡片上的数字得和表格同步
  useEffect(() => {
    api.stats().then(setStats).catch((e: unknown) => setError(errorMessage(e)));
  }, [refreshToken]);

  if (error) return <div className="alert error">{error}</div>;
  if (!stats) return null;

  const score = scoreNote(stats.score);
  const llm = llmNote(stats.llmScore);
  const applied = Object.values(stats.applications).reduce((a, b) => a + b, 0);
  const appliedNote = Object.entries(stats.applications)
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");

  return (
    <div className="stats-strip">
      <Stat value={stats.jobs} label="职位" />
      <Stat value={stats.details.ok || 0} label="已抓到 JD" note={`待抓 ${stats.pendingDetails} 条`} />
      {stats.salary.floorWan != null && (
        <Stat
          value={`${stats.salary.meetsFloorPct}%`}
          label={`上限 ≥ ${stats.salary.floorWan} 万`}
          note={`${stats.salary.meetsFloor} / ${stats.salary.parsed} 条解析出薪资`}
        />
      )}
      <Stat value={stats.score.scored} label="已打分" note={score.text} warn={score.warn} />
      <Stat
        value={`${stats.llmScore.scored} / ${stats.llmScore.scorable}`}
        label="LLM 打分覆盖"
        note={llm.text}
        warn={llm.warn}
      />
      <Stat value={applied} label="投递记录" note={appliedNote || "还没投过"} />
    </div>
  );
}

function Stat({
  value,
  label,
  note,
  warn,
}: {
  value: number | string;
  label: string;
  note?: string;
  warn?: boolean;
}) {
  return (
    <div className="stat" title={note}>
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
      {note && <div className={warn ? "stat-n warn" : "stat-n"}>{note}</div>}
    </div>
  );
}
