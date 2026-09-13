import { useEffect, useState } from "react";
import { api, errorMessage } from "./api";
import JobsView from "./components/JobsView";
import TasksView from "./components/TasksView";
import ConfigView from "./components/ConfigView";
import ProfileMenu from "./components/ProfileMenu";
import type { ConfigPaths, HealthResponse } from "./types";

type TabKey = "jobs" | "tasks" | "config";

const TABS: { key: TabKey; label: string }[] = [
  { key: "jobs", label: "职位" },
  { key: "tasks", label: "采集任务" },
  { key: "config", label: "配置" },
];

export default function App() {
  const [tab, setTab] = useState<TabKey>("jobs");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [profile, setProfile] = useState<ConfigPaths | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch((e: unknown) => setError(errorMessage(e)));
    // 一次只服务一个 profile。顶栏必须显示是谁的数据：几个 profile 的界面
    // 长得一模一样，看错了会把别人的岗位当成自己的。点它能切换或新建
    api.config().then((c) => setProfile(c.paths)).catch(() => {});
  }, []);

  return (
    <div className="app">
      <header>
        <h1>job-agent</h1>
        {profile && <ProfileMenu current={profile.profile} directory={profile.profileDir} />}
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
                  title="尚未填写猎聘 Token，请到「配置 - 职位采集」页填写"
                >
                  未配置 Token
                </span>
              )}
            </>
          )}
        </div>
      </header>

      {error && <div className="alert error">{error}</div>}

      {/* 提交 LLM 打分后自动切到任务页：任务在后台跑，进度和日志都在那边 */}
      {tab === "jobs" && <JobsView onTaskCreated={() => setTab("tasks")} />}
      {tab === "tasks" && <TasksView />}
      {tab === "config" && <ConfigView />}
    </div>
  );
}
