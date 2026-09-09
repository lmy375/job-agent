import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import type {
  ConfigPaths,
  ConfigResponse,
  PromptsResponse,
  ScoreSettings,
  ScoreSignal,
} from "../types";
import RescoreButton from "./RescoreButton";

/**
 * 配置页：改**搜索关键词**、**`[score]` 打分逻辑**、**LLM 打分提示词**，其余只读。
 *
 * 能改的只有这三处不是偷懒：它们都是「判断口径」，是求职过程里真正要反复调的
 * ——搜什么词、什么算对口、怎么判断一个岗好不好和自己够不够格。为了改一个权重
 * 或一句话去翻文件，是把最高频的动作放到了最远的地方。猎聘 token、模型接入点、
 * 并发、限速属于「怎么连」，一次配好就不动，也不该有回显密钥的接口。
 *
 * **保存就是改文件**：写回 `profiles/<名>/profile.toml` 再重新加载，
 * 所以 CLI、Web、agent 三条路读的永远是同一份——不存在「网页上改了但
 * 命令行跑的是另一套」。定点替换、不重排注释（`config/writer.py`）。
 */

/** 表单里的数字都存成字符串（直接绑在 input 上），提交时才转——与 TasksView 同口径。 */
interface SignalForm {
  name: string;
  weight: string;
  pattern: string;
}

interface ScoreForm {
  salaryFloorWan: string;
  titleMultiplier: string;
  requirePattern: string;
  requirePenalty: string;
  signals: SignalForm[];
}

function toForm(score: ScoreSettings): ScoreForm {
  return {
    salaryFloorWan: score.salary_floor_wan === null ? "" : String(score.salary_floor_wan),
    titleMultiplier: String(score.title_multiplier),
    requirePattern: score.require.pattern ?? "",
    requirePenalty: String(score.require.penalty),
    signals: score.signals.map((s) => ({
      name: s.name,
      weight: String(s.weight),
      pattern: s.pattern,
    })),
  };
}

/** 空串 / 非数字都当填错报出来，**不悄悄替换成 0**——那会静默改掉打分口径。 */
function toNumber(text: string, label: string, problems: string[]): number {
  const value = Number(text.trim());
  if (text.trim() === "" || !Number.isFinite(value)) {
    problems.push(`${label}要填一个数字`);
    return 0;
  }
  return value;
}

/**
 * 表单 → 请求体。
 *
 * 只拦「明显还没填完」的输入（空的数字、缺名字或正则），
 * 正则能不能编译交给后端——那条校验写在 `ScoreConfig` 上，
 * 在前端再实现一遍必然与后端不一致。
 */
function buildScore(form: ScoreForm): { payload?: ScoreSettings; problems: string[] } {
  const problems: string[] = [];

  const floorText = form.salaryFloorWan.trim();
  const floor = floorText === "" ? null : Number(floorText);
  if (floor !== null && (!Number.isFinite(floor) || floor < 0)) {
    problems.push("薪资门槛要填 0 以上的数字，或者留空表示不过滤");
  }
  const multiplier = toNumber(form.titleMultiplier, "职位名权重倍数", problems);
  const penalty = toNumber(form.requirePenalty, "不对口扣分", problems);

  const signals: ScoreSignal[] = [];
  form.signals.forEach((row, index) => {
    const name = row.name.trim();
    const pattern = row.pattern.trim();
    // 整行都空的当没加过（点了「加一条」又没填），不当成错误
    if (!name && !pattern && !row.weight.trim()) return;
    if (!name) problems.push(`第 ${index + 1} 条信号缺名字`);
    if (!pattern) problems.push(`第 ${index + 1} 条信号缺正则`);
    signals.push({
      name,
      weight: toNumber(row.weight, `第 ${index + 1} 条信号的权重`, problems),
      pattern,
    });
  });

  if (problems.length) return { problems };
  return {
    payload: {
      salary_floor_wan: floor,
      title_multiplier: multiplier,
      require: { pattern: form.requirePattern.trim() || null, penalty },
      signals,
    },
    problems,
  };
}

export default function ConfigView() {
  const [paths, setPaths] = useState<ConfigPaths | null>(null);
  const [keywordsText, setKeywordsText] = useState("");
  const [score, setScore] = useState<ScoreForm | null>(null);
  const [account, setAccount] = useState("");
  const [tokenReady, setTokenReady] = useState(false);
  const [search, setSearch] = useState<{ address: string | null; salary: string } | null>(null);
  const [rateLimit, setRateLimit] = useState(0);
  const [llmProvider, setLlmProvider] = useState("");
  const [llmConcurrency, setLlmConcurrency] = useState(0);
  const [prompts, setPrompts] = useState<PromptsResponse | null>(null);
  const [appealText, setAppealText] = useState("");
  const [fitText, setFitText] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState("");

  /** 用一次响应把整页填满。保存后也走它——生效的永远是后端重新读到的那份。 */
  const apply = (config: ConfigResponse) => {
    const settings = config.settings;
    setPaths(config.paths);
    setKeywordsText(settings.search.keywords.join("\n"));
    setScore(toForm(settings.score));
    setAccount(settings.profile.account);
    setTokenReady(Boolean(settings.liepin.accounts[settings.profile.account]?.user_token));
    setSearch({
      address: settings.search.address,
      salary: `${settings.search.salary_kind || "—"} ${
        settings.search.salary_floor ? `${settings.search.salary_floor / 10000} 万起` : "不限"
      }`,
    });
    setRateLimit(settings.liepin.rate_limit_per_min);
    setLlmProvider(settings.llm_score.provider ?? "（跟随 [agent].provider）");
    setLlmConcurrency(settings.llm_score.concurrency);
  };

  /** 提示词也用一次响应把两个编辑框填满，保存后同样走它。 */
  const applyPrompts = (data: PromptsResponse) => {
    setPrompts(data);
    setAppealText(data.appeal.content);
    setFitText(data.fit.content);
  };

  useEffect(() => {
    api.config().then(apply).catch((e: unknown) => setError(errorMessage(e)));
    api.prompts().then(applyPrompts).catch((e: unknown) => setError(errorMessage(e)));
  }, []);

  const saveKeywords = async () => {
    const keywords = keywordsText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    setSaving("keywords");
    setError("");
    setNotice("");
    try {
      const config = await api.updateKeywords(keywords);
      apply(config);
      setNotice(
        `关键词已写进 ${config.paths.profileFile}（${config.settings.search.keywords.length} 个）。` +
          "去「采集任务」跑一次搜索才会按新词采集。"
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving("");
    }
  };

  const saveScore = async () => {
    if (!score) return;
    const { payload, problems } = buildScore(score);
    if (!payload) {
      setError(problems.join("；"));
      setNotice("");
      return;
    }
    setSaving("score");
    setError("");
    setNotice("");
    try {
      const config = await api.updateScore(payload);
      apply(config);
      setNotice(
        `打分逻辑已写进 ${config.paths.profileFile}。` +
          "库里的分数还是上一次算的——点「重新打分」才会按新规则重算全库排名。"
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving("");
    }
  };

  const savePrompts = async () => {
    setSaving("prompts");
    setError("");
    setNotice("");
    try {
      const data = await api.updatePrompts({ appeal: appealText, fit: fitText });
      applyPrompts(data);
      setNotice(
        "提示词已保存。库里已有的 LLM 分数是按旧提示词判的，" +
          "和新的不可比——想要一套口径就到「职位」页重新打一遍。"
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving("");
    }
  };

  const updateSignal = (index: number, patch: Partial<SignalForm>) =>
    setScore((prev) =>
      prev === null
        ? prev
        : {
            ...prev,
            signals: prev.signals.map((row, i) => (i === index ? { ...row, ...patch } : row)),
          }
    );

  const addSignal = () =>
    setScore((prev) =>
      prev === null
        ? prev
        : { ...prev, signals: [...prev.signals, { name: "", weight: "", pattern: "" }] }
    );

  const removeSignal = (index: number) =>
    setScore((prev) =>
      prev === null ? prev : { ...prev, signals: prev.signals.filter((_, i) => i !== index) }
    );

  const keywordCount = keywordsText.split("\n").filter((line) => line.trim()).length;

  return (
    <>
      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert">{notice}</div>}

      {/* 绝对路径放在下面那张表里：写在这段话里会把它撑成三行，反而看不清说的是什么 */}
      <p className="muted">
        这页改的是当前 profile 的 <code title={paths?.profileFile ?? ""}>profile.toml</code>
        ——按保存就是改那个文件，改完立刻重新加载，所以 CLI 与 <code>job agent</code>
        读到的永远是同一份。跟人无关的东西（猎聘 token、模型接入点、限速）住全局
        <code title={paths?.configFile ?? ""}>config/config.toml</code>，这页只读，
        密钥也不回显。
      </p>

      <section className="panel">
        <h3>搜索关键词</h3>
        <p className="muted">
          一行一个，<b>顺序就是优先级</b>：职位按 jobId 去重，每条记到的
          searchKeyword 是最先命中它的那个词，所以最想要的方向放最前面。
          不想再搜的词删掉即可（TOML 数组里注释掉的候选词不受影响，会原样留着）。
        </p>
        <textarea
          className="mono"
          rows={8}
          value={keywordsText}
          placeholder={"AI Agent\n大模型\nAI 应用"}
          onChange={(e) => setKeywordsText(e.target.value)}
        />
        <div className="form-actions">
          <button className="btn" disabled={saving !== ""} onClick={saveKeywords}>
            {saving === "keywords" ? "保存中…" : "保存关键词"}
          </button>
          <span className="muted">{keywordCount} 个</span>
        </div>
      </section>

      {score && (
        <section className="panel">
          <h3>打分逻辑（[score]）</h3>
          <p className="muted">
            整段都是「<b>你</b>想要什么」，不是通用规则——同一个词对做应用工程的人是
            负信号、对做算法的人是最强的正信号。打分只做<b>分诊</b>（把几百条砍到几十条），
            该不该投要读 JD。正则直接写，<code>\b</code> 之类不用转义（存成 TOML
            字面量字符串）。
          </p>
          <div className="editor-row">
            <label>
              薪资门槛（万元/年，税前；留空 = 不过滤）
              <input
                type="number"
                min="0"
                step="5"
                value={score.salaryFloorWan}
                placeholder="不限"
                onChange={(e) => setScore({ ...score, salaryFloorWan: e.target.value })}
              />
            </label>
            <label>
              职位名权重倍数（职位名比正文更能代表岗位本质）
              <input
                type="number"
                min="0"
                step="0.5"
                value={score.titleMultiplier}
                onChange={(e) => setScore({ ...score, titleMultiplier: e.target.value })}
              />
            </label>
            <label>
              不对口扣分（负数）
              <input
                type="number"
                step="1"
                value={score.requirePenalty}
                onChange={(e) => setScore({ ...score, requirePenalty: e.target.value })}
              />
            </label>
          </div>
          <label>
            必须命中的赛道词（职位名与 JD 里都找不到就扣上面那一刀；留空 = 不兜底）
            <input
              className="mono"
              value={score.requirePattern}
              placeholder="(?a:\bagent\b)|智能体|大模型"
              onChange={(e) => setScore({ ...score, requirePattern: e.target.value })}
            />
          </label>

          <div className="table-wrap">
            <table className="signals">
              <thead>
                <tr>
                  <th className="w-name">信号名</th>
                  <th className="w-weight">权重</th>
                  <th>正则（命中职位名或 JD 正文就加权重）</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {score.signals.map((row, index) => (
                  <tr key={index}>
                    <td>
                      <input
                        value={row.name}
                        placeholder="AI Agent / 智能体"
                        onChange={(e) => updateSignal(index, { name: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        step="1"
                        value={row.weight}
                        onChange={(e) => updateSignal(index, { weight: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        className="mono"
                        value={row.pattern}
                        placeholder="(?a:\bagent\b)|智能体"
                        onChange={(e) => updateSignal(index, { pattern: e.target.value })}
                      />
                    </td>
                    <td className="actions">
                      <button className="btn small ghost" onClick={() => removeSignal(index)}>
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
                {score.signals.length === 0 && (
                  <tr>
                    <td colSpan={4} className="empty">
                      一条信号都没有，所有岗位都会是 0 分，排序没有意义。
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="form-actions">
            <button className="btn ghost" disabled={saving !== ""} onClick={addSignal}>
              加一条信号
            </button>
            <button className="btn" disabled={saving !== ""} onClick={saveScore}>
              {saving === "score" ? "保存中…" : "保存打分逻辑"}
            </button>
            <RescoreButton />
            <span className="muted">
              正权重 {score.signals.filter((s) => Number(s.weight) > 0).length} 条 / 负权重{" "}
              {score.signals.filter((s) => Number(s.weight) < 0).length} 条
            </span>
          </div>
        </section>
      )}

      {prompts && (
        <section className="panel">
          <h3>LLM 打分提示词</h3>
          <p className="muted">
            两段各管一个维度，模型一次调用同时给出两个分。这里写的是<b>方法论</b>
            （怎么判断），「你想去什么方向、什么不看」不用写在这里——简历与
            <code>preferences.md</code> 会一起发给模型。留空 = 恢复内置默认；
            输出格式那一截由代码拼，改不坏。当前模型：<code>{prompts.modelLabel}</code>
            ，提示词指纹 <code>{prompts.fingerprint}</code>。
          </p>
          <PromptEditor
            title="维度一 · 岗位吸引力"
            hint="从求职者角度：薪资水位、公司体量与阶段、JD 写得专不专业、业务靠不靠谱、是否落在你的方向里。"
            view={prompts.appeal}
            value={appealText}
            onChange={setAppealText}
          />
          <PromptEditor
            title="维度二 · 胜任匹配度"
            hint="从招聘方角度：硬门槛过不过、核心经历贴不贴、技术栈和职级差多少——拿到这份工作的概率。"
            view={prompts.fit}
            value={fitText}
            onChange={setFitText}
          />
          <div className="form-actions">
            <button className="btn" disabled={saving !== ""} onClick={savePrompts}>
              {saving === "prompts" ? "保存中…" : "保存提示词"}
            </button>
            <span className="muted">并发 {llmConcurrency} · 接入点 {llmProvider}（只读）</span>
          </div>
        </section>
      )}

      {paths && (
        <>
          <h3 className="section-title">路径与账号（只读）</h3>
          <div className="table-wrap">
            <table className="kv">
              <tbody>
                <Row k="profile" v={`${paths.profile}（${paths.profileDir}）`} />
                <Row k="全局配置" v={paths.configFile} />
                <Row k="profile 配置" v={paths.profileFile} />
                <Row k="数据库" v={paths.database} />
                <Row k="简历" v={paths.resume} />
                <Row k="求职偏好" v={paths.preferences} />
                <Row k="打分提示词（吸引力）" v={promptPath(paths.appealPrompt, prompts?.appeal.isDefault)} />
                <Row k="打分提示词（胜任度）" v={promptPath(paths.fitPrompt, prompts?.fit.isDefault)} />
                <Row k="猎聘账号" v={`${account}（token ${tokenReady ? "已配置" : "未配置"}）`} />
                <Row k="搜索地点" v={search?.address ?? null} />
                <Row k="搜索薪资门槛" v={search?.salary ?? null} />
                <Row k="接口限速" v={`${rateLimit} 次/分钟`} />
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

/**
 * 一个维度的提示词编辑框。
 *
 * 内置默认也照样把全文填进来（而不是留空 + 一句「用的是默认」）：
 * 要改就得先看见改什么，让人先去仓库里翻一遍默认提示词是最没必要的一步。
 */
function PromptEditor({
  title,
  hint,
  view,
  value,
  onChange,
}: {
  title: string;
  hint: string;
  view: { isDefault: boolean; path: string };
  value: string;
  onChange: (text: string) => void;
}) {
  return (
    <div className="prompt-editor">
      <label>
        <span>
          {title}
          <span className={view.isDefault ? "badge" : "badge warn"} title={view.path}>
            {view.isDefault ? "内置默认" : "已自定义"}
          </span>
        </span>
        <textarea className="mono" rows={12} value={value} onChange={(e) => onChange(e.target.value)} />
      </label>
      <p className="muted">{hint}</p>
    </div>
  );
}

/** 提示词文件那一行：文件不存在很正常，得说清楚「不存在 = 用内置默认」。 */
function promptPath(path: string, isDefault: boolean | undefined): string {
  if (isDefault === undefined) return path;
  return isDefault ? `${path}（不存在，用内置默认）` : path;
}

/** 配置表的一行。`v` 可能是 null（比如没有全局配置文件），渲染成空格子。 */
function Row({ k, v }: { k: string; v: string | null }) {
  return (
    <tr>
      <th>{k}</th>
      <td className="mono">{v}</td>
    </tr>
  );
}
