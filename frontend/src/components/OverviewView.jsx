import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function OverviewView() {
  const [stats, setStats] = useState(null);
  const [tracks, setTracks] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState("");
  const [loadingTracks, setLoadingTracks] = useState(false);

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message));
    api.config().then(setConfig).catch((e) => setError(e.message));
  }, []);

  const loadTracks = () => {
    setLoadingTracks(true);
    api
      .trackStats()
      .then(setTracks)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingTracks(false));
  };

  return (
    <>
      {error && <div className="alert error">{error}</div>}

      {stats && (
        <div className="stat-grid">
          <Stat value={stats.jobs} label="职位总数" />
          <Stat value={stats.details.ok || 0} label="已抓到 JD" note={`待抓 ${stats.pendingDetails} 条`} />
          <Stat
            value={`${stats.salary.meets100Pct}%`}
            label="薪资上限真正 ≥100 万"
            note={`${stats.salary.meets100}/${stats.salary.parsed} 条`}
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

      <h3 className="section-title">
        赛道分布
        {!tracks && (
          <button className="btn small" onClick={loadTracks} disabled={loadingTracks}>
            {loadingTracks ? "统计中…" : "开始统计"}
          </button>
        )}
      </h3>
      {!tracks && (
        <p className="muted">
          需要把全部 JD 跑一遍分类规则，耗时数秒，结果会缓存到数据变化为止。
        </p>
      )}
      {tracks && (
        <>
          <p className="muted">按 JD 正文去重后共 {tracks.total} 份有效 JD。</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>赛道</th>
                  <th>JD 数</th>
                  <th>年薪中位区间</th>
                  <th>90 分位</th>
                  <th>≥100 万占比</th>
                  <th>主要角色</th>
                </tr>
              </thead>
              <tbody>
                {tracks.tracks.map((t) => (
                  <tr key={t.track}>
                    <td>
                      <b>{t.track}</b>
                    </td>
                    <td>{t.count}</td>
                    <td className="salary">
                      {t.salaryMedianLow ?? "—"}–{t.salaryMedianHigh ?? "—"} 万
                    </td>
                    <td>{t.salaryP90High ?? "—"} 万</td>
                    <td>
                      {t.salaryParsed
                        ? `${Math.round((t.meets100 / t.salaryParsed) * 100)}%`
                        : "—"}
                    </td>
                    <td className="sub">
                      {t.roles
                        .slice(0, 3)
                        .map(([role, n]) => `${role}(${n})`)
                        .join("、")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {config && (
        <>
          <h3 className="section-title">当前配置</h3>
          <p className="muted">
            配置是文件，改它请编辑 <code>{config.paths.configFile}</code>，改完重启服务生效。
            Web 端只读，避免出现「页面上改了但 CLI 跑的是另一套」。
          </p>
          <div className="table-wrap">
            <table className="kv">
              <tbody>
                <Row k="配置文件" v={config.paths.configFile} />
                <Row k="数据库" v={config.paths.database} />
                <Row k="简历" v={config.paths.resume} />
                <Row k="报告输出" v={`${config.paths.report}${config.reportExists ? "" : "（尚未生成）"}`} />
                <Row k="insights 素材" v={config.paths.insightsDir} />
                <Row k="token" v={config.token || "未配置"} />
                <Row k="搜索地点" v={config.search.address} />
                <Row
                  k="薪资门槛"
                  v={`${config.search.salary_kind || "—"} ${
                    config.search.salary_floor ? config.search.salary_floor / 10000 + " 万起" : "不限"
                  }`}
                />
                <Row
                  k="启用的关键词"
                  v={config.search.groups
                    .filter((g) => g.enabled)
                    .map((g) => `${g.track}：${g.keywords.join("、")}`)
                    .join("　|　")}
                />
                <Row k="接口限速" v={`${config.liepin.rate_limit_per_min} 次/分钟`} />
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function Stat({ value, label, note }) {
  return (
    <div className="stat">
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
      {note && <div className="stat-n">{note}</div>}
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
