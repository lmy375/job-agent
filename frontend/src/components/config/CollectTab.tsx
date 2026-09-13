/**
 * 「职位采集」页：搜什么、从哪搜、以什么节奏搜。
 *
 * 三段配置横跨两个文件：`[search]` 是「找什么」（profile.toml），
 * `[liepin]` 与 `[detail]` 是「怎么连」（config/config.toml）。页面上不按文件
 * 分，按**做一件事需要的东西**分——新用户填 token、配关键词、点一次搜索，
 * 应该在同一屏里走完，而不是先被告知「token 请去编辑另一个文件」。
 */

import { useState } from "react";
import type { ConfigResponse, SectionView } from "../../types";
import { SectionForm, type FieldSpec } from "./fields";

/** 猎聘接口认的枚举，和 `core/liepin/enums.py` 一一对应。 */
const SALARY_KINDS = [
  { value: "月薪", label: "月薪" },
  { value: "年薪", label: "年薪" },
];

const EDU_LEVELS = ["不限", "大专", "本科", "硕士", "博士"].map((v) => ({ value: v, label: v }));

const WORK_YEARS = ["不限", "应届", "1年以下", "1-3年", "3-5年", "5-10年", "10年以上"].map((v) => ({
  value: v,
  label: v,
}));

const SEARCH_FIELDS: FieldSpec[] = [
  {
    key: "address",
    label: "工作地点",
    hint: "填写城市名，模糊匹配；留空表示不限地点",
    nullable: true,
    placeholder: "北京",
  },
  {
    key: "salary_kind",
    label: "薪资口径",
    hint: "填写薪资区间时必须选择口径",
    kind: "select",
    options: SALARY_KINDS,
    nullable: true,
  },
  {
    key: "salary_floor",
    label: "薪资下限（元）",
    hint: "与该范围有交集的薪资区间都会保留，不要求职位下限高于该值。单位为元，按所选口径填写",
    kind: "number",
    nullable: true,
  },
  {
    key: "salary_cap",
    label: "薪资上限（元）",
    kind: "number",
    nullable: true,
  },
  { key: "edu_level", label: "学历", kind: "select", options: EDU_LEVELS, nullable: true },
  {
    key: "work_experience",
    label: "工作经验",
    kind: "select",
    options: WORK_YEARS,
    nullable: true,
  },
  {
    key: "max_pages",
    label: "每个关键词采集页数",
    hint: "每页 20 条，最多 6 页，即每个关键词最多采集 120 条",
    kind: "number",
  },
];

const DETAIL_FIELDS: FieldSpec[] = [
  {
    key: "sleep_min",
    label: "请求间隔下限（秒）",
    hint: "每次请求前随机等待一段时间，时长在下限与上限之间取值",
    kind: "number",
  },
  { key: "sleep_max", label: "请求间隔上限（秒）", kind: "number" },
  {
    key: "block_backoff",
    label: "受限后等待（秒）",
    hint: "被平台限制访问后，暂停多久再继续采集",
    kind: "number",
  },
  { key: "max_retries", label: "重试次数", kind: "number" },
  { key: "timeout", label: "超时（秒）", kind: "number" },
  {
    key: "user_agent",
    label: "User-Agent",
    hint: "抓取职位详情页时使用的浏览器标识，一般无需修改",
    wide: "full",
  },
];

export default function CollectTab({
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
  const search = sections.search;
  const account = config.settings.profile.account;
  const [keywordsText, setKeywordsText] = useState(() =>
    (config.settings.search.keywords ?? []).join("\n")
  );
  const keywordCount = keywordsText.split("\n").filter((line) => line.trim()).length;

  const liepinFields: FieldSpec[] = [
    {
      key: `accounts.${account}.user_token`,
      label: `猎聘 Token（账号 ${account}）`,
      hint: "搜索与投递都需要该凭证。在 liepin.com/mcp/auth 生成，失效后在此更新即可",
      kind: "secret",
      nullable: true,
      wide: "full",
    },
    {
      key: "rate_limit_per_min",
      label: "接口限速（次/分钟）",
      hint: "平台实测上限约为每分钟 10 次，超出后会被限制访问 20 分钟以上，建议保持默认值 8",
      kind: "number",
    },
    { key: "timeout", label: "超时（秒）", kind: "number" },
    {
      key: "base_url",
      label: "接口地址",
      hint: "猎聘开放接口地址，一般无需修改",
      wide: "full",
    },
  ];

  return (
    <>
      <SectionForm
        section={search}
        fields={SEARCH_FIELDS}
        title="搜索条件与关键词"
        hint={
          <>
            每行一个关键词，<b>顺序即优先级</b>：同一职位被多个关键词搜到时只保留一条，
            来源记为排在最前的那个关键词，因此请把最看重的方向放在前面。删除某行后不再
            使用该关键词搜索，已采集的职位不受影响。
          </>
        }
        savedNotice="搜索条件已保存，将在下次采集时生效。可到「采集任务」页发起一次搜索。"
        onSaved={onSaved}
        onFailed={onFailed}
        patch={() => ({
          values: {
            ...(search?.values ?? {}),
            keywords: keywordsText
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean),
          },
          problems: [],
        })}
      >
        <label>
          搜索关键词（一行一个）
          <textarea
            className="mono"
            rows={8}
            value={keywordsText}
            placeholder={"AI Agent\n大模型\nAI 应用"}
            onChange={(e) => setKeywordsText(e.target.value)}
          />
        </label>
        <span className="muted">共 {keywordCount} 个关键词</span>
      </SectionForm>

      <SectionForm
        section={sections.liepin}
        fields={liepinFields}
        title="猎聘账号与限速"
        hint={
          <>
            账号与限速由所有 profile 共用，保存在全局配置 <code>config/config.toml</code> 中。
            凭证以明文显示，便于核对与更新。如需同时保留多个账号，可在「高级」页的{" "}
            <code>[liepin.accounts.*]</code> 中添加，再由各 profile 指定使用哪一个。
          </>
        }
        savedNotice="账号与限速已保存。若采集时出现访问受限，请将限速调回 8，等待 20 分钟后重试。"
        onSaved={onSaved}
        onFailed={onFailed}
      />

      <SectionForm
        section={sections.detail}
        fields={DETAIL_FIELDS}
        title="职位详情抓取"
        hint="控制职位详情页的抓取速度。间隔越短采集越快，触发平台限制的概率也越高。"
        savedNotice="抓取参数已保存。"
        onSaved={onSaved}
        onFailed={onFailed}
      />
    </>
  );
}
