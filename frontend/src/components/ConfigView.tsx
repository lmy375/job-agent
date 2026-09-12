import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import type { ConfigResponse, SectionView } from "../types";
import AdvancedTab from "./config/AdvancedTab";
import CollectTab from "./config/CollectTab";
import PromptsTab from "./config/PromptsTab";
import ScoringTab from "./config/ScoringTab";

/**
 * 配置页：**页面上能改的就是全部配置项**。
 *
 * 这个 Web 端是求职系统的完整入口——一条 `job web` 起来之后，从填 token、
 * 配搜索条件，到调打分口径、改简历与提示词，再到投递，全程不必回终端。
 * 所以这里不设「只读的那一半」。
 *
 * 分四页，按**求职流程**排而不是按文件排：
 *
 * | 页 | 管什么 | 落在哪个文件 |
 * | --- | --- | --- |
 * | 职位采集 | 搜什么词、从哪搜、以什么节奏搜 | `[search]` + `[liepin]` + `[detail]` |
 * | 职位评分 | 关键词分诊 + LLM 打分的参数 | `[score]` + `[llm_score]` |
 * | 提示词 | 简历、求职偏好、两段打分方法论 | profile 目录下的 4 份 md |
 * | 高级 | 其余一切（接入点、端口、日志…） | 两个 toml 的全文编辑 |
 *
 * 一段配置横跨两个文件是常态（采集页就同时改 profile.toml 与 config.toml），
 * 按文件分会把「做一件事」拆到两页去。
 *
 * **保存就是改文件**：写回那两个 toml（或 profile 目录下的 md）再重新加载，
 * 所以 CLI、Web、`job agent` 三条路读的永远是同一份——不存在「网页上改了但
 * 命令行跑的是另一套」。表单保存只改真正变了的那几行，注释与对齐都留着
 * （`config/writer.py` 的按键定点替换）。
 */

type PageKey = "collect" | "scoring" | "prompts" | "advanced";

const PAGES: { key: PageKey; label: string }[] = [
  { key: "collect", label: "职位采集" },
  { key: "scoring", label: "职位评分" },
  { key: "prompts", label: "提示词" },
  { key: "advanced", label: "高级" },
];

export default function ConfigView() {
  const [page, setPage] = useState<PageKey>("collect");
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [sections, setSections] = useState<Record<string, SectionView>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  /**
   * 段的值每次都重新拉。
   *
   * 保存的响应给的是**生效的**配置树（路径已解析成绝对路径），拿它回填表单
   * 会把 `data/jobs.db` 显示成一长串绝对路径，下次保存就真写进文件了。
   * 表单要的是**文件里**那份，只能从 `/sections` 来。
   */
  const reloadSections = async () => {
    const data = await api.sections();
    setSections(Object.fromEntries(data.sections.map((item) => [item.name, item])));
  };

  useEffect(() => {
    Promise.all([api.config().then(setConfig), reloadSections()]).catch((e: unknown) =>
      setError(errorMessage(e))
    );
  }, []);

  const onSaved = (fresh: ConfigResponse, message: string) => {
    setConfig(fresh);
    setError("");
    setNotice(message);
    reloadSections().catch((e: unknown) => setError(errorMessage(e)));
  };

  const onFailed = (message: string) => {
    setError(message);
    setNotice("");
  };

  const onNotice = (message: string) => {
    setError("");
    setNotice(message);
  };

  return (
    <>
      <nav className="subtabs">
        {PAGES.map((item) => (
          <button
            key={item.key}
            className={page === item.key ? "subtab active" : "subtab"}
            onClick={() => setPage(item.key)}
          >
            {item.label}
          </button>
        ))}
        {config && (
          <span className="muted subtab-note" title={config.paths.profileDir}>
            profile <code>{config.paths.profile}</code>
          </span>
        )}
      </nav>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert">{notice}</div>}

      {config && page === "collect" && (
        <CollectTab
          sections={sections}
          config={config}
          onSaved={onSaved}
          onFailed={onFailed}
        />
      )}
      {config && page === "scoring" && (
        <ScoringTab
          sections={sections}
          config={config}
          onSaved={onSaved}
          onFailed={onFailed}
        />
      )}
      {page === "prompts" && <PromptsTab onFailed={onFailed} onNotice={onNotice} />}
      {page === "advanced" && <AdvancedTab onSaved={onSaved} onFailed={onFailed} />}
    </>
  );
}
