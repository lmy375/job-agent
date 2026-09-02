import { useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import JobsView from "./components/JobsView";
import TasksView from "./components/TasksView";
import OverviewView from "./components/OverviewView";
import ConfigView from "./components/ConfigView";
import type { ConfigPaths, HealthResponse } from "./types";

type TabKey = "jobs" | "tasks" | "overview" | "config";

const TABS: { key: TabKey; label: string }[] = [
  { key: "jobs", label: "职位" },
  { key: "tasks", label: "采集任务" },
  { key: "overview", label: "数据概览" },
  { key: "config", label: "配置" },
];

export default function App() {
  const [tab, setTab] = useState<TabKey>("jobs");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [profile, setProfile] = useState<ConfigPaths | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch((e: unknown) => setError(errorMessage(e)));
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
      {tab === "config" && <ConfigView />}
    </div>
  );
}
