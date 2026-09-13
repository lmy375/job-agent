/**
 * 顶栏的 profile 切换与新建。
 *
 * 放顶栏而不是配置页里，是因为**换 profile 换的是整个界面的数据**：
 * 职位列表、任务、库存卡、配置全是那个 profile 的。它不是一项设置，
 * 是「现在在看谁的数据」，所以得和标题并排、一直看得见。
 *
 * 切换成功后**整页重载**。所有视图的数据都换了，挨个刷新既容易漏，
 * 又会出现「列表已经是新 profile 的、抽屉里还开着旧 profile 的那条」这种
 * 半新半旧的状态——那比多等半秒糟得多。
 */

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import type { ProfileSummary } from "../types";

export default function ProfileMenu({ current, directory }: { current: string; directory: string }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<ProfileSummary[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setError("");
    api
      .profiles()
      .then((data) => setRows(data.profiles))
      .catch((e: unknown) => setError(errorMessage(e)));

    const close = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  /** 切换与新建都走这里：成功就重载，失败就把后端那句话显示出来。 */
  const run = async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    setError("");
    try {
      await action();
      window.location.reload();
    } catch (e) {
      setError(errorMessage(e));
      setBusy("");
    }
  };

  return (
    <div className="profile-menu" ref={box}>
      <button
        className="badge profile"
        title={`当前 profile：${directory}\n点击切换或新建`}
        onClick={() => setOpen(!open)}
      >
        {current} <span className="caret">▾</span>
      </button>

      {open && (
        <div className="profile-pop">
          <p className="muted">
            换 profile 换的是<b>整套数据</b>：职位库、简历、关键词、信号表全换，
            并写成命令行的默认 profile。
          </p>
          {error && <div className="alert error">{error}</div>}

          {rows === null && !error && <p className="muted">读取中…</p>}
          {rows?.map((row) => (
            <button
              key={row.name}
              className={row.isCurrent ? "profile-row current" : "profile-row"}
              disabled={busy !== "" || row.isCurrent}
              title={row.directory}
              onClick={() => run(row.name, () => api.switchProfile(row.name))}
            >
              <span className="profile-name">
                {row.isCurrent ? "● " : ""}
                {row.name}
              </span>
              <span className="muted">
                {row.jobs === null ? "还没采过" : `${row.jobs} 条职位`}
                {row.applied ? ` · 投了 ${row.applied}` : ""}
                {!row.hasResume && " · 缺简历"}
                {!row.hasPreferences && " · 缺偏好"}
              </span>
            </button>
          ))}

          {creating ? (
            <div className="profile-new">
              <input
                autoFocus
                value={name}
                placeholder="名字（字母、数字、- 和 _）"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && name.trim()) {
                    void run("new", () => api.createProfile(name.trim()));
                  }
                }}
              />
              <button
                className="btn"
                disabled={busy !== "" || !name.trim()}
                onClick={() => run("new", () => api.createProfile(name.trim()))}
              >
                {busy === "new" ? "创建中…" : "创建并切换"}
              </button>
              <p className="muted">
                新 profile 是一份<b>空模板</b>：没有简历、没有求职偏好、关键词是示例。
                建完先去「配置 → 提示词」把前两样填了，不然 LLM 打分没有判断依据。
              </p>
            </div>
          ) : (
            <button className="link profile-add" onClick={() => setCreating(true)}>
              + 新建 profile
            </button>
          )}
        </div>
      )}
    </div>
  );
}
