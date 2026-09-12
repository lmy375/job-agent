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
    hint: "决定「胜任匹配度」那个分。写清年限、做过什么系统、带过多少人、技术栈——模型只看这里，简历里没写的一律按「没有」算。",
    placeholder: "# 姓名\n\n## 经历\n- 2020–2025 某公司，后端 / 平台，带 5 人",
  },
  preferences: {
    title: "求职偏好",
    hint: "决定「岗位吸引力」那个分的区间。写清想去什么方向、什么明确不看、薪资底线与口径、地点与硬约束。方向不对的岗位薪资再高也抬不出上限，靠的就是这份。",
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
        `${DOC_META[kind].title}已保存。库里已有的 LLM 分数是按旧内容判的，` +
          "和新的不可比——想要一套口径就到「职位」页重新打一遍。"
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
        "提示词已保存。和内置默认逐字相同的内容不会落盘（那样以后改进默认方法论才传得下来）。" +
          "库里已有的 LLM 分数与新提示词不可比，重新打一遍才是一套口径。"
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
        <h3>判断依据</h3>
        <p className="muted">
          这两份和提示词一起发给模型。它们<b>没有内置默认</b>——「你是谁、你想要什么」
          只能你自己写。写不全的地方留 <code>&lt;待补&gt;</code>，不要编，
          模型会照着编出来的内容打分。
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
                  {docs[kind]?.exists ? "已填写" : "还没有"}
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
            两段各管一个维度，模型一次调用同时给出两个分。这里写的是<b>怎么判断</b>，
            「想去什么方向」写在上面的求职偏好里。清空 = 回到内置默认；
            输出格式与 JSON Schema 那一截由代码拼，改不坏。当前模型：
            <code>{prompts.modelLabel}</code>，提示词指纹 <code>{prompts.fingerprint}</code>。
          </p>
          <PromptEditor
            title="维度一 · 岗位吸引力"
            hint="从求职者角度，以求职偏好里的期望为决定性标准——先按方向定分数区间，方向不对的岗位薪资再高也抬不出上限；其次才看薪资水位、公司体量与阶段、JD 专不专业、业务靠不靠谱。"
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
            {view.isDefault ? "内置默认" : "已自定义"}
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
