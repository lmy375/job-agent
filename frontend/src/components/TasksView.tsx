import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { formatTime } from "../format";
import type { TaskDetail, TaskKind, TaskParamsInput, TaskStatus, TaskView } from "../types";

const POLL_MS = 2000;

const STATUS_LABEL: Record<TaskStatus, string> = {
  pending: "排队中",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const KIND_LABEL: Record<TaskKind, string> = {
  search: "搜索职位",
  detail: "抓取详情",
  llm_score: "LLM 打分",
};

//: 到了这几个状态就没什么可取消的了
const FINAL_STATUSES: TaskStatus[] = ["succeeded", "failed", "cancelled"];

/** 表单里的值。数字项都存成字符串（直接绑在 input 上），提交时才转。 */
interface Form {
  keywords: string;
  pages: string;
  limit: string;
  retryFailed: boolean;
  fetchDetail: boolean;
}

export default function TasksView() {
  const [tasks, setTasks] = useState<TaskView[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState<Form>({
    keywords: "",
    pages: "",
    limit: "",
    retryFailed: false,
    // 默认开：没有 JD 的库打不了分，搜完就抓才是常态
    fetchDetail: true,
  });

  const refresh = useCallback(async () => {
    try {
      const data = await api.tasks();
      setTasks(data.tasks);
      setRunning(data.running);
      if (selected) setDetail((await api.task(selected)).task);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [selected]);

  // 只在有任务在跑时轮询，闲置时不打无用请求
  useEffect(() => {
    refresh();
    if (!running && !selected) return undefined;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh, running, selected]);

  const submit = async (kind: TaskKind) => {
    setError("");
    const params: TaskParamsInput = {};
    if (kind === "search") {
      const keywords = form.keywords
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (keywords.length) params.keywords = keywords;
      if (form.pages) params.pages = Number(form.pages);
      params.fetch_detail = form.fetchDetail;
    }
    if (kind === "detail" || form.fetchDetail) {
      if (form.limit) params.limit = Number(form.limit);
      params.retry_failed = form.retryFailed;
    }
    try {
      const data = await api.createTask({ kind, params });
      setSelected(data.task.id);
      refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const cancel = async (taskId: string) => {
    if (!window.confirm("取消任务？已完成的进度都已入库，重跑会自动续上。")) return;
    try {
      await api.cancelTask(taskId);
      refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <>
      <div className="panels">
        <section className="panel">
          <h3>搜索职位</h3>
          <p className="muted">
            按 profile.toml 里的关键词批量搜索并入库，默认搜完接着抓 JD。
            留空即用配置里的全部关键词。接口限流按 token 记账，任务串行执行。
          </p>
          <label>
            关键词（逗号分隔，可留空）
            <input
              value={form.keywords}
              placeholder="AI Agent, 大模型"
              onChange={(e) => setForm({ ...form, keywords: e.target.value })}
            />
          </label>
          <label>
            每个关键词翻几页（1–6，留空取配置）
            <input
              type="number"
              min="1"
              max="6"
              value={form.pages}
              onChange={(e) => setForm({ ...form, pages: e.target.value })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.fetchDetail}
              onChange={(e) => setForm({ ...form, fetchDetail: e.target.checked })}
            />
            搜完自动抓 JD（关掉只入库列表；没有 JD 就没法打分）
          </label>
          <button className="btn" onClick={() => submit("search")}>
            {form.fetchDetail ? "开始搜索并抓 JD" : "只搜列表"}
          </button>
        </section>

        <section className="panel">
          <h3>抓取详情</h3>
          <p className="muted">
            单独把库里还没抓的 JD 补上（搜索那边关掉了自动抓、或上次被限流打断时用）。
            串行 + 随机休眠，单条约 4 秒，进度实时落库，中断后重跑会自动跳过已完成的。
            下面两项对「搜完自动抓」同样生效。
          </p>
          <label>
            本次最多抓多少条（留空 = 全部待抓）
            <input
              type="number"
              min="1"
              value={form.limit}
              onChange={(e) => setForm({ ...form, limit: e.target.value })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.retryFailed}
              onChange={(e) => setForm({ ...form, retryFailed: e.target.checked })}
            />
            重试此前失败的
          </label>
          <button className="btn" onClick={() => submit("detail")}>
            开始抓取
          </button>
        </section>
      </div>

      {error && <div className="alert error">{error}</div>}

      <h3 className="section-title">任务列表</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>类型</th>
              <th>状态</th>
              <th>进度</th>
              <th>最近消息</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => (
              <tr key={task.id} className={selected === task.id ? "selected" : ""}>
                <td>{KIND_LABEL[task.kind] || task.kind}</td>
                <td>
                  <span className={`badge ${task.status}`}>
                    {STATUS_LABEL[task.status] || task.status}
                  </span>
                </td>
                <td className="progress-cell">
                  {task.percent !== null ? (
                    <>
                      <div className="progress">
                        <div className="progress-fill" style={{ width: `${task.percent}%` }} />
                      </div>
                      <span className="sub">
                        {task.current}/{task.total}
                      </span>
                    </>
                  ) : (
                    <span className="sub">—</span>
                  )}
                </td>
                <td className="msg">{task.message || task.error || ""}</td>
                <td className="sub">{formatTime(task.createdAt)}</td>
                <td className="actions">
                  <button className="btn small ghost" onClick={() => setSelected(task.id)}>
                    日志
                  </button>
                  {!FINAL_STATUSES.includes(task.status) && (
                    <button className="btn small" onClick={() => cancel(task.id)}>
                      取消
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {tasks.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  还没有任务。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && detail && (
        <section className="panel logs">
          <h3>
            任务 {detail.id} · {KIND_LABEL[detail.kind]} · {STATUS_LABEL[detail.status]}
            <button className="btn small ghost" onClick={() => setSelected(null)}>
              关闭
            </button>
          </h3>
          {detail.result && <pre className="result">{JSON.stringify(detail.result, null, 2)}</pre>}
          <pre className="log">{detail.logs.join("\n") || "（暂无日志）"}</pre>
        </section>
      )}
    </>
  );
}
