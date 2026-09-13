/**
 * 配置表单的公共零件。
 *
 * 配置段有十来个、字段有几十个，每个都手写一遍 `<input value onChange>`
 * 只会让「加一个配置项」变成改三处。这里把「一段 = 一张字段表」固定下来：
 * 每个 tab 只写 `FieldSpec[]`（字段名、标签、那句解释），渲染与保存共用一份。
 *
 * 两条刻意的规矩：
 *
 * - **整段发回去**。段的模型是 `extra="forbid"`，而且字段间有联合校验
 *   （薪资上下限、sleep 区间），只发改动的那几个字段校验不出来。所以
 *   保存时是在**原始 values 上打补丁**再整段 PUT——字段表里没列的键
 *   （比如 `[score].signals`）原样带回去，不会被这张表吃掉。
 * - **校验交给后端**。这里只拦「明显没填完」（该填数字的填了字母），
 *   正则能不能编译、薪资上下限矛不矛盾都写在 pydantic 模型上，
 *   在前端再实现一遍必然与后端不一致。
 */

import { useEffect, useState } from "react";
import { api, errorMessage } from "../../api";
import type { ConfigResponse, SectionView } from "../../types";

export type FieldKind = "text" | "number" | "secret" | "select" | "bool";

export interface FieldSpec {
  /** 字段名。支持 `accounts.default.user_token` 这样的点分路径 */
  key: string;
  label: string;
  /** 标签下面那句解释。只说这个值有什么效果、填大填小会怎样；不讲实现，不重复字段名 */
  hint?: string;
  kind?: FieldKind;
  options?: { value: string; label: string }[];
  placeholder?: string;
  /** 留空时写回 `null`。对应后端 `| None` 的字段——留空就是「这项没配」 */
  nullable?: boolean;
  /**
   * 占多宽。
   *
   * - `"full"`：整行。长正则、UA、token 这类，截断了就看不出写的是什么。
   * - `"rest"`：从第一列铺到倒数第二列，把最后一格留给紧跟着它的那个字段。
   *   「硬性要求关键词 + 不匹配时扣分」这种「一个长输入 + 一个小数字」要并排，
   *   拆成两行读的人会以为它们没关系。
   */
  wide?: "full" | "rest";
}

/** 按点分路径取值。段里的子表（账号、接入点）就是这么定位的。 */
export function getPath(values: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((node, key) => {
    if (node === null || typeof node !== "object") return undefined;
    return (node as Record<string, unknown>)[key];
  }, values);
}

/** 按点分路径写值，沿途缺的层补成空对象。返回**新的**对象，不改原来那份。 */
export function setPath(
  values: Record<string, unknown>,
  path: string,
  value: unknown
): Record<string, unknown> {
  const keys = path.split(".");
  const last = keys.pop();
  if (last === undefined) return values;
  const out = { ...values };
  let node = out;
  keys.forEach((key) => {
    const child = node[key];
    const next =
      child !== null && typeof child === "object" ? { ...(child as Record<string, unknown>) } : {};
    node[key] = next;
    node = next;
  });
  node[last] = value;
  return out;
}

/** 值 → 输入框里的文本。`null` / `undefined` 都显示成空。 */
function toText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

/** 输入框里的文本 → 要写回去的值。填错的报出来，**不悄悄替换成 0**。 */
function fromText(field: FieldSpec, text: string, problems: string[]): unknown {
  const trimmed = text.trim();
  if (field.kind === "bool") return trimmed === "true";
  if (trimmed === "") {
    if (field.nullable) return null;
    problems.push(`${field.label}不能为空`);
    return "";
  }
  if (field.kind === "number") {
    const value = Number(trimmed);
    if (!Number.isFinite(value)) {
      problems.push(`${field.label}需填写数字`);
      return 0;
    }
    return value;
  }
  return trimmed;
}

/**
 * 一段配置的表单。
 *
 * `children` 放这张字段表表达不了的东西（关键词数组、信号表），
 * 它们和字段一起保存——同一段只发一次请求，不会出现「改了一半」。
 */
export function SectionForm({
  section,
  fields,
  title,
  hint,
  savedNotice,
  onSaved,
  onFailed,
  patch,
  children,
  footer,
}: {
  section: SectionView | undefined;
  fields: FieldSpec[];
  title: string;
  hint?: React.ReactNode;
  /** 保存成功后说的那句话。要说清「这一改，接下来该做什么」 */
  savedNotice: string;
  onSaved: (config: ConfigResponse, notice: string) => void;
  onFailed: (message: string) => void;
  /** 保存前再往 values 上打一层补丁（字段表表达不了的那部分） */
  patch?: () => { values?: Record<string, unknown>; problems: string[] };
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!section) return;
    const next: Record<string, string> = {};
    fields.forEach((field) => {
      next[field.key] = toText(getPath(section.values, field.key));
    });
    setTexts(next);
    // fields 是模块级常量，每次渲染都是同一份，不进依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  if (!section) return null;

  const save = async () => {
    const problems: string[] = [];
    let values = { ...section.values };
    fields.forEach((field) => {
      values = setPath(values, field.key, fromText(field, texts[field.key] ?? "", problems));
    });
    if (patch) {
      const extra = patch();
      problems.push(...extra.problems);
      if (extra.values) values = extra.values;
    }
    if (problems.length) {
      onFailed(problems.join("；"));
      return;
    }
    setSaving(true);
    try {
      onSaved(await api.updateSection(section.name, values), savedNotice);
    } catch (error) {
      onFailed(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="panel">
      <h3>
        {title} <code className="section-tag">[{section.name}]</code>
      </h3>
      {hint && <p className="muted">{hint}</p>}
      <div className="editor-row">
        {fields.map((field) => (
          <label key={field.key} className={field.wide && `grow-${field.wide}`}>
            {field.label}
            {field.kind === "select" ? (
              <select
                value={texts[field.key] ?? ""}
                onChange={(e) => setTexts({ ...texts, [field.key]: e.target.value })}
              >
                {field.nullable && <option value="">（不设置）</option>}
                {(field.options ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={field.kind === "secret" || field.wide ? "mono" : undefined}
                type={field.kind === "number" ? "number" : "text"}
                value={texts[field.key] ?? ""}
                placeholder={field.placeholder}
                onChange={(e) => setTexts({ ...texts, [field.key]: e.target.value })}
              />
            )}
            {field.hint && <span className="field-hint">{field.hint}</span>}
          </label>
        ))}
      </div>
      {children}
      <div className="form-actions">
        <button className="btn" disabled={saving} onClick={save}>
          {saving ? "保存中…" : "保存"}
        </button>
        <span className="muted" title={section.file}>
          保存至 {section.scope === "global" ? "config/config.toml" : "profile.toml"}
        </span>
        {footer}
      </div>
    </section>
  );
}
