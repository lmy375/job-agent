import { useEffect, useState } from "react";
import { api } from "./api.js";
import JobsView from "./components/JobsView.jsx";
import TasksView from "./components/TasksView.jsx";
import OverviewView from "./components/OverviewView.jsx";

const TABS = [
  { key: "jobs", label: "职位" },
  { key: "tasks", label: "采集任务" },
  { key: "overview", label: "数据概览" },
];

export default function App() {
  const [tab, setTab] = useState("jobs");
  const [health, setHealth] = useState(null);
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(e.message));
    // 一次只服务一个 profile（job web -p <名字>）。顶栏必须显示是谁的数据：
    // 几个 profile 的界面长得一模一样，看错了会把别人的岗位当成自己的
    api.config().then((c) => setProfile(c.paths)).catch(() => {});
  }, []);

  return (
    <div className="app">
      <header>
        <h1>job-agent</h1>
        {profile && (
          <span className="badge profile" title={profile.profileDir}>
            {profile.profile}
          </span>
        )}
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={tab === t.key ? "tab active" : "tab"}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="meta">
          {health && (
            <>
              共 <b>{health.jobs}</b> 条职位
              {!health.tokenConfigured && (
                <span
                  className="badge warn"
                  title="config/config.toml 的 [liepin.accounts.*] 里没有 user_token"
                >
                  未配置 token
                </span>
              )}
            </>
          )}
        </div>
      </header>

      {error && <div className="alert error">{error}</div>}

      {tab === "jobs" && <JobsView />}
      {tab === "tasks" && <TasksView />}
      {tab === "overview" && <OverviewView />}
    </div>
  );
}
