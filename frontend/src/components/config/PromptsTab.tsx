/**
 * 「提示词」页：发给模型的全部自由文本。
 *
 * 四份 Markdown，分成两类：
 *
 * - **判断依据**（`resume.md` / `preferences.md`）是「你是谁、你想要什么」。
 *   它们没有内置默认，本来就该是用户自己的东西，空着就是空着。
 *   `preferences.md` 里的求职期望**决定**岗位吸引力的分数区间，
 *   所以它比提示词本身更常改。
 * - **方法论**（`score_appeal.md` / `score_fit.md`）是「怎么判断」。
 *   它们有内置默认，profile 里的文件只是**覆盖**；清空 = 删掉覆盖文件、
 *   回到内置默认，而不是「存一份空的」。
 *
 * 两类都改完就该重打分：库里已有的 LLM 分数是按旧文本判的，和新的不可比。
 */

import { useEffect, useState } from "react";
import { api, errorMessage } from "../../api";
import type { DocKind, DocView, PromptsResponse } from "../../types";

const DOC_META: Record<DocKind, { title: string; hint: string; placeholder: string }> = {
  resume: {
    title: "简历",
    hint: "用于评估「胜任匹配度」。建议写明工作年限、负责过的系统、团队规模与技术栈。模型仅依据此处内容判断，未写明的经历视为不具备。",
    placeholder: "# 姓名\n\n## 经历\n- 2020–2025 某公司，后端 / 平台，带 5 人",
  },
  preferences: {
    title: "求职偏好",
    hint: "用于评估「岗位吸引力」。建议写明期望方向、明确排除的方向、薪资底线与口径、地点及其他硬性要求。与期望方向不符的职位，薪资再高也不会获得高分。",
    placeholder: "# 求职偏好\n\n## 想要的方向\n\n## 明确不看\n\n## 薪资底线（税前）",
  },
};

export default function PromptsTab({
  onFailed,
  onNotice,
}: {
  onFailed: (message: string) => void;
  onNotice: (message: string) => void;
}) {
  const [docs, setDocs] = useState<Record<string, DocView>>({});
  const [docTexts, setDocTexts] = useState<Record<string, string>>({});
  const [prompts, setPrompts] = useState<PromptsResponse | null>(null);
  const [appealText, setAppealText] = useState("");
  const [fitText, setFitText] = useState("");
  const [saving, setSaving] = useState("");

  const applyDocs = (list: DocView[]) => {
    setDocs(Object.fromEntries(list.map((doc) => [doc.kind, doc])));
    setDocTexts(Object.fromEntries(list.map((doc) => [doc.kind, doc.content])));
  };

  const applyPrompts = (data: PromptsResponse) => {
    setPrompts(data);
    setAppealText(data.appeal.content);
    setFitText(data.fit.content);
  };

  useEffect(() => {
    api
      .docs()
      .then((data) => applyDocs(data.docs))
      .catch((e: unknown) => onFailed(errorMessage(e)));
    api.prompts().then(applyPrompts).catch((e: unknown) => onFailed(errorMessage(e)));
    // 只在挂载时拉一次；回调是父级的 setState，进依赖会变成每次渲染都重拉
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveDoc = async (kind: DocKind) => {
    setSaving(kind);
    try {
      const data = await api.updateDoc(kind, docTexts[kind] ?? "");
      applyDocs(data.docs);
      onNotice(
        `${DOC_META[kind].title}已保存。已有的 LLM 分数基于修改前的内容生成，` +
          "如需统一评分标准，请到「职位」页重新打分。"
      );
    } catch (e) {
      onFailed(errorMessage(e));
    } finally {
      setSaving("");
    }
  };

  const savePrompts = async () => {
    setSaving("prompts");
    try {
      applyPrompts(await api.updatePrompts({ appeal: appealText, fit: fitText }));
      onNotice(
        "提示词已保存。内容与默认方法论完全一致时不会另存为自定义版本。" +
          "已有的 LLM 分数基于修改前的提示词生成，如需统一评分标准，请到「职位」页重新打分。"
      );
    } catch (e) {
      onFailed(errorMessage(e));
    } finally {
      setSaving("");
    }
  };

  return (
    <>
      <section className="panel">
        <h3>评分依据</h3>
        <p className="muted">
          这两份内容会随提示词一并提交给模型，<b>没有默认值</b>，需要自行填写。
          暂时无法确定的部分请填写 <code>&lt;待补&gt;</code>，不要虚构——
          模型会将其作为事实用于评分。
        </p>
        {(Object.keys(DOC_META) as DocKind[]).map((kind) => (
          <div className="prompt-editor" key={kind}>
            <label>
              <span>
                {DOC_META[kind].title}
                <span
                  className={docs[kind]?.exists ? "badge" : "badge warn"}
                  title={docs[kind]?.path}
                >
                  {docs[kind]?.exists ? "已填写" : "未填写"}
                </span>
              </span>
              <textarea
                className="mono"
                rows={12}
                value={docTexts[kind] ?? ""}
                placeholder={DOC_META[kind].placeholder}
                onChange={(e) => setDocTexts({ ...docTexts, [kind]: e.target.value })}
              />
            </label>
            <p className="muted">{DOC_META[kind].hint}</p>
            <div className="form-actions">
              <button className="btn" disabled={saving !== ""} onClick={() => saveDoc(kind)}>
                {saving === kind ? "保存中…" : `保存${DOC_META[kind].title}`}
              </button>
              <span className="muted" title={docs[kind]?.path}>
                {docs[kind]?.path?.split("/").slice(-2).join("/")}
              </span>
            </div>
          </div>
        ))}
      </section>

      {prompts && (
        <section className="panel">
          <h3>打分方法论</h3>
          <p className="muted">
            两段提示词各对应一个评分维度，模型在一次调用中同时给出两项分数。此处描述的是
            <b>评分方法</b>，期望的求职方向请写在上方的求职偏好中。清空后恢复为默认方法论；
            输出格式由系统固定，不受此处内容影响。当前模型：
            <code>{prompts.modelLabel}</code>，提示词版本 <code>{prompts.fingerprint}</code>。
          </p>
          <PromptEditor
            title="维度一 · 岗位吸引力"
            hint="从求职者角度评估这份工作是否值得投递：以求职偏好中的期望方向确定分数区间，再结合薪资水平、公司规模与发展阶段、职位描述的专业程度等因素在区间内调整。"
            view={prompts.appeal}
            value={appealText}
            onChange={setAppealText}
          />
          <PromptEditor
            title="维度二 · 胜任匹配度"
            hint="从招聘方角度评估获得这份工作的可能性：硬性条件是否满足、核心经历是否匹配、技术栈与职级的差距有多大。"
            view={prompts.fit}
            value={fitText}
            onChange={setFitText}
          />
          <div className="form-actions">
            <button className="btn" disabled={saving !== ""} onClick={savePrompts}>
              {saving === "prompts" ? "保存中…" : "保存提示词"}
            </button>
          </div>
        </section>
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
            {view.isDefault ? "默认内容" : "已自定义"}
          </span>
        </span>
        <textarea
          className="mono"
          rows={12}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
      <p className="muted">{hint}</p>
    </div>
  );
}
