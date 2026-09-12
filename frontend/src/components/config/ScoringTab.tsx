/**
 * 「职位评分」页：两层打分放在一起。
 *
 * 第一层 `[score]` 是关键词**分诊**（本地计算、几千条一两秒、可重跑），
 * 第二层 `[llm_score]` 是让模型读 JD（按条计费、结果落库）。它们回答的是
 * 同一个问题的两半，所以对着调才有意义——分诊把几百条砍到几十条，
 * 剩下的才值得花钱送模型。
 *
 * 信号表不走通用字段表：它是一个**数组**，加减行、逐条改权重，
 * 用 `FieldSpec[]` 表达不了。它和 `[score]` 的其余字段一起保存（同一段一次请求）。
 */

import { useEffect, useState } from "react";
import type { ConfigResponse, ScoreSignal, SectionView } from "../../types";
import RescoreButton from "../RescoreButton";
import { SectionForm, type FieldSpec } from "./fields";

const SCORE_FIELDS: FieldSpec[] = [
  {
    key: "salary_floor_wan",
    label: "薪资门槛（万元/年，税前）",
    hint: "留空 = 不过滤。只影响「这次看什么」，不进库里的名次",
    kind: "number",
    nullable: true,
  },
  {
    key: "title_multiplier",
    label: "职位名权重倍数",
    hint: "信号命中职位名时权重乘这个数——职位名比正文更能代表岗位本质",
    kind: "number",
  },
  {
    key: "require.pattern",
    label: "硬性要求关键词",
    hint: "职位名与 JD 正文都不匹配这些词就大额扣分；留空 = 不检查",
    nullable: true,
    wide: "rest",
    placeholder: "(?a:\\bagent\\b)|智能体|大模型",
  },
  {
    key: "require.penalty",
    label: "不匹配时扣分（负数）",
    kind: "number",
  },
];

const LLM_FIELDS: FieldSpec[] = [
  {
    key: "concurrency",
    label: "并发上限",
    hint: "1–16。再高多半先撞上各家的每分钟请求数限流",
    kind: "number",
  },
];

/** 表单里的数字都存成字符串（直接绑在 input 上），提交时才转。 */
interface SignalForm {
  name: string;
  weight: string;
  pattern: string;
}

export default function ScoringTab({
  sections,
  config,
  onSaved,
  onFailed,
}: {
  sections: Record<string, SectionView>;
  config: ConfigResponse;
  onSaved: (config: ConfigResponse, notice: string) => void;
  onFailed: (message: string) => void;
}) {
  const score = sections.score;
  const [signals, setSignals] = useState<SignalForm[]>([]);

  useEffect(() => {
    const rows = (score?.values.signals ?? []) as ScoreSignal[];
    setSignals(rows.map((row) => ({ ...row, weight: String(row.weight) })));
  }, [score]);

  /** 信号表 → 要写回 `[score]` 的那部分。整行都空的当没加过，不报错。 */
  const patchSignals = () => {
    const problems: string[] = [];
    const rows: ScoreSignal[] = [];
    signals.forEach((row, index) => {
      const name = row.name.trim();
      const pattern = row.pattern.trim();
      if (!name && !pattern && !row.weight.trim()) return;
      if (!name) problems.push(`第 ${index + 1} 条信号缺名字`);
      if (!pattern) problems.push(`第 ${index + 1} 条信号缺正则`);
      const weight = Number(row.weight.trim());
      if (row.weight.trim() === "" || !Number.isFinite(weight)) {
        problems.push(`第 ${index + 1} 条信号的权重要填一个数字`);
      }
      rows.push({ name, weight, pattern });
    });
    return { values: { ...(score?.values ?? {}), signals: rows }, problems };
  };

  const update = (index: number, patch: Partial<SignalForm>) =>
    setSignals((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  const providerOptions = Object.keys(config.settings.agent?.providers ?? {}).map((name) => ({
    value: name,
    label: name,
  }));

  const llmFields: FieldSpec[] = [
    {
      key: "provider",
      label: "模型接入点",
      hint: "留空 = 跟随 [agent].provider。换了模型，库里的旧分数就不可比",
      kind: "select",
      options: providerOptions,
      nullable: true,
    },
    ...LLM_FIELDS,
  ];

  return (
    <>
      <SectionForm
        section={score}
        fields={SCORE_FIELDS}
        title="关键词打分"
        hint={
          <>
            整段都是「<b>你</b>想要什么」，不是通用规则——同一个词对做应用工程的人是
            负信号、对做算法的人是最强的正信号。打分只做<b>分诊</b>（把几百条砍到几十条），
            该不该投要读 JD。正则直接写，<code>\b</code> 之类不用转义（存成 TOML
            字面量字符串）。
          </>
        }
        savedNotice="打分逻辑已保存。库里的分数还是上一次算的——点「重新打分」才会按新规则重算全库排名。"
        onSaved={onSaved}
        onFailed={onFailed}
        patch={patchSignals}
        footer={
          <>
            <RescoreButton />
            <span className="muted">
              正权重 {signals.filter((s) => Number(s.weight) > 0).length} 条 / 负权重{" "}
              {signals.filter((s) => Number(s.weight) < 0).length} 条
            </span>
          </>
        }
      >
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
              {signals.map((row, index) => (
                <tr key={index}>
                  <td>
                    <input
                      value={row.name}
                      onChange={(e) => update(index, { name: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      step="1"
                      value={row.weight}
                      onChange={(e) => update(index, { weight: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      className="mono"
                      value={row.pattern}
                      onChange={(e) => update(index, { pattern: e.target.value })}
                    />
                  </td>
                  <td>
                    <button
                      className="link"
                      onClick={() => setSignals(signals.filter((_, i) => i !== index))}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          className="link"
          onClick={() => setSignals([...signals, { name: "", weight: "", pattern: "" }])}
        >
          + 加一条信号
        </button>
      </SectionForm>

      <SectionForm
        section={sections.llm_score}
        fields={llmFields}
        title="LLM 打分"
        hint={
          <>
            让模型读 JD 与简历，给「岗位吸引力」与「胜任匹配度」两个分。
            <b>按条计费</b>，所以在「职位」页挑好条目再打，没有「一键全打」。
            怎么判断写在「提示词」页。当前：<code>{config.settings.llm_score.provider ?? "（跟随 agent）"}</code>
          </>
        }
        savedNotice="LLM 打分参数已保存。换了接入点的话，库里按旧模型判的分数与新的不可比。"
        onSaved={onSaved}
        onFailed={onFailed}
      />
    </>
  );
}
