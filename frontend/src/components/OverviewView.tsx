import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { formatTime } from "../format";
import type { LlmScoreStatus, OverviewResponse, ScoreStatus } from "../types";
import RescoreButton from "./RescoreButton";

/**
 * 数据概览：**只报库存，不做分析**。
 *
 * 多少职位、抓了多少 JD、投了多少、薪资什么水位。赛道 / 技能分布这类市场分析
 * 不在这个仓库里（见 CLAUDE.md）。配置在「配置」页，这里不重复显示一遍——
 * 同一份配置在两个页面各渲染一次，改了一处就会有一处看着是旧的。
 */

/** 落库分数的新鲜度：过期或有漏打的必须说出来，不能让人把旧分数当成现在的。 */
function scoreNote(score: ScoreStatus): { text: string; warn: boolean } {
  if (score.scored === 0) return { text: "还没打过分——点上面的「重新打分」", warn: true };
  if (score.stale)
    return { text: "打分逻辑改过但没重算——点上面的「重新打分」", warn: true };
  if (score.missing > 0)
    return { text: `${score.missing} 条有 JD 却没打分——点上面的「重新打分」`, warn: true };
  return { text: `最近一次 ${formatTime(score.scoredAt)}`, warn: false };
}

/**
 * LLM 打分的覆盖率提示。
 *
 * 「还有多少没打」刻意**不**说成待办：按条计费，大部分没打过是常态，
 * 天天喊「还差 3000 条」只会让人学会忽略这一格。真该提醒的是口径不一致——
 * 库里混着别的模型或旧提示词判出来的分数，那些和现在这批没法比。
 */
function llmNote(llm: LlmScoreStatus): { text: string; warn: boolean } {
  if (llm.scored === 0)
    return { text: "还没打过——去「职位」页勾几条试试", warn: false };
  if (llm.stale)
    return {
      text: `其中 ${llm.scored - llm.current} 条是别的模型或旧提示词判的，不可比`,
      warn: true,
    };
  return { text: `最近一次 ${formatTime(llm.scoredAt)}`, warn: false };
}

export default function OverviewView() {
  const [stats, setStats] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.stats().then(setStats).catch((e: unknown) => setError(errorMessage(e)));
  }, []);

  useEffect(load, [load]);

  return (
    <>
      {error && <div className="alert error">{error}</div>}

      <h3 className="section-title">
        库存概览
        {/* 分数是落库的，会过期——报出过期的地方就该能当场重算 */}
        <RescoreButton onDone={load} />
      </h3>

      {stats && (
        <div className="stat-grid">
          <Stat value={stats.jobs} label="职位总数" />
          <Stat value={stats.details.ok || 0} label="已抓到 JD" note={`待抓 ${stats.pendingDetails} 条`} />
          {stats.salary.floorWan != null && (
            <Stat
              value={`${stats.salary.meetsFloorPct}%`}
              label={`薪资上限真正 ≥${stats.salary.floorWan} 万`}
              note={`${stats.salary.meetsFloor}/${stats.salary.parsed} 条`}
            />
          )}
          <Stat
            value={stats.score.scored}
            label="已打分"
            note={scoreNote(stats.score).text}
            warn={scoreNote(stats.score).warn}
          />
          <Stat
            value={`${stats.llmScore.scored}/${stats.llmScore.scorable}`}
            label="LLM 打分覆盖"
            note={llmNote(stats.llmScore).text}
            warn={llmNote(stats.llmScore).warn}
          />
          <Stat
            value={Object.values(stats.applications).reduce((a, b) => a + b, 0)}
            label="投递记录"
            note={Object.entries(stats.applications)
              .map(([k, v]) => `${k}:${v}`)
              .join("  ")}
          />
        </div>
      )}

      {stats && stats.keywords.length > 0 && (
        <>
          <h3 className="section-title">各搜索关键词的职位数</h3>
          <p className="muted">
            纯库存计数，不带任何赛道 / 分类判断。关键词本身在「配置」页改。
          </p>
          <div className="chips">
            {stats.keywords.map((k) => (
              <span key={k.keyword} className="chip">
                {k.keyword} <span className="count">{k.count}</span>
              </span>
            ))}
          </div>
        </>
      )}
    </>
  );
}

interface StatProps {
  value: number | string;
  label: string;
  note?: string;
  warn?: boolean;
}

function Stat({ value, label, note, warn }: StatProps) {
  return (
    <div className="stat">
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
      {note && <div className={warn ? "stat-n warn" : "stat-n"}>{note}</div>}
    </div>
  );
}
