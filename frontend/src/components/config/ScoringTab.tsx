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
    hint: "只显示薪资上限不低于该值的职位。留空表示不过滤；该值不参与打分，不影响分数与排名",
    kind: "number",
    nullable: true,
  },
  {
    key: "title_multiplier",
    label: "职位名权重倍数",
    hint: "信号命中职位名称时，权重按该倍数计算",
    kind: "number",
  },
  {
    key: "require.pattern",
    label: "硬性要求关键词",
    hint: "职位名称与职位描述中均未出现这些词时扣分。留空表示不检查",
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
    hint: "同时发起的评分请求数，取值 1–16。设置过高可能触发模型服务的速率限制",
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
      if (!name) problems.push(`第 ${index + 1} 条信号缺少名称`);
      if (!pattern) problems.push(`第 ${index + 1} 条信号缺少正则表达式`);
      const weight = Number(row.weight.trim());
      if (row.weight.trim() === "" || !Number.isFinite(weight)) {
        problems.push(`第 ${index + 1} 条信号的权重需填写数字`);
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
      hint: "留空表示使用「高级」页 [agent] 中配置的默认接入点。更换模型后，已有分数与新分数不具可比性",
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
            信号表用于<b>初步筛选</b>：按关键词命中情况为职位加减权重，把数百条职位收窄到
            可以逐条审阅的范围，不用于判断是否值得投递。评分标准取决于个人求职方向，
            同一个词对不同求职者可能是正信号，也可能是负信号。正则表达式按原样填写，
            <code>\b</code> 等写法无需额外转义。
          </>
        }
        savedNotice="打分规则已保存。当前分数仍是上次计算的结果，点击「重新打分」按新规则重算全部职位。"
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
                <th>正则表达式（命中职位名称或职位描述时计入权重）</th>
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
          + 添加信号
        </button>
      </SectionForm>

      <SectionForm
        section={sections.llm_score}
        fields={llmFields}
        title="LLM 打分"
        hint={
          <>
            由模型阅读职位描述与简历，分别给出「岗位吸引力」与「胜任匹配度」两项评分。
            <b>按职位条数计费</b>，因此需在「职位」页选定范围后发起，不提供一次性全库打分。
            评分标准在「提示词」页配置。当前接入点：
            <code>{config.settings.llm_score.provider ?? "未指定（使用默认接入点）"}</code>
          </>
        }
        savedNotice="LLM 打分参数已保存。若更换了接入点，已有分数由此前的模型生成，与新分数不具可比性。"
        onSaved={onSaved}
        onFailed={onFailed}
      />
    </>
  );
}
