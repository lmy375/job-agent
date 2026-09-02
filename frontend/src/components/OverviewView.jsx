import { useEffect, useState } from "react";
import { api } from "../api.js";
import { formatTime } from "../format.js";

/** 落库分数的新鲜度：过期或有漏打的必须说出来，不能让人把旧分数当成现在的。 */
function scoreNote(score) {
  if (score.scored === 0) return { text: "还没打过分——跑 job score", warn: true };
  if (score.stale) return { text: "[score] 改过但没重新打分——跑 job score", warn: true };
  if (score.missing > 0)
    return { text: `${score.missing} 条有 JD 却没打分——跑 job score`, warn: true };
  return { text: `最近一次 ${formatTime(score.scoredAt)}`, warn: false };
}

export default function OverviewView() {
  const [stats, setStats] = useState(null);
  const [config, setConfig] = useState(null);
  // /api/config 返回 { settings, paths }：settings 就是脱敏后的配置树
  const settings = config?.settings;
  const [error, setError] = useState("");

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message));
    api.config().then(setConfig).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      {error && <div className="alert error">{error}</div>}

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
            value={Object.values(stats.applications).reduce((a, b) => a + b, 0)}
            label="投递记录"
            note={Object.entries(stats.applications)
              .map(([k, v]) => `${k}:${v}`)
              .join("  ")}
          />
        </div>
      )}

      {config && (
        <>
          <h3 className="section-title">当前配置</h3>
          <p className="muted">
            当前 profile 是 <code>{config.paths.profile}</code>——一个 profile 就是一个人 /
            一种求职场景，简历、关键词、数据库都在它自己的目录里，和别的 profile 互不可见。
            配置是文件：跟人无关的改 <code>{config.paths.configFile}</code>，
            随人而变的改 <code>{config.paths.profileFile}</code>，改完重启服务生效。
            Web 端只读，避免出现「页面上改了但 CLI 跑的是另一套」。
          </p>
          <div className="table-wrap">
            <table className="kv">
              <tbody>
                <Row k="profile" v={`${config.paths.profile}（${config.paths.profileDir}）`} />
                <Row k="全局配置" v={config.paths.configFile} />
                <Row k="profile 配置" v={config.paths.profileFile} />
                <Row k="数据库" v={config.paths.database} />
                <Row k="简历" v={config.paths.resume} />
                <Row k="求职偏好" v={config.paths.preferences} />
                <Row
                  k="猎聘账号"
                  v={`${settings.profile.account}（token ${
                    settings.liepin.accounts[settings.profile.account]?.user_token
                      ? "已配置"
                      : "未配置"
                  }）`}
                />
                <Row k="搜索地点" v={settings.search.address} />
                <Row
                  k="薪资门槛"
                  v={`${settings.search.salary_kind || "—"} ${
                    settings.search.salary_floor
                      ? settings.search.salary_floor / 10000 + " 万起"
                      : "不限"
                  }`}
                />
                <Row k="搜索关键词（顺序即优先级）" v={settings.search.keywords.join("、")} />
                <Row k="接口限速" v={`${settings.liepin.rate_limit_per_min} 次/分钟`} />
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function Stat({ value, label, note, warn }) {
  return (
    <div className="stat">
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
      {note && <div className={warn ? "stat-n warn" : "stat-n"}>{note}</div>}
    </div>
  );
}

function Row({ k, v }) {
  return (
    <tr>
      <th>{k}</th>
      <td className="mono">{v}</td>
    </tr>
  );
}
