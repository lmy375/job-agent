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
    hint: "服务端模糊匹配；留空 = 不限地点",
    nullable: true,
    placeholder: "北京",
  },
  {
    key: "salary_kind",
    label: "薪资口径",
    hint: "填了薪资区间就必须选一个",
    kind: "select",
    options: SALARY_KINDS,
    nullable: true,
  },
  {
    key: "salary_floor",
    label: "薪资下限（元）",
    hint: "按区间「重叠」过滤，不是「下限 ≥ 该值」。年薪口径填 1000000 这种",
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
    label: "每个关键词翻几页",
    hint: "上限 6（接口本身就只给这么多）。一页 40 条左右",
    kind: "number",
  },
];

const DETAIL_FIELDS: FieldSpec[] = [
  {
    key: "sleep_min",
    label: "请求间隔下限（秒）",
    hint: "详情页是普通网页、不走 API，节奏得自己控",
    kind: "number",
  },
  { key: "sleep_max", label: "请求间隔上限（秒）", kind: "number" },
  {
    key: "block_backoff",
    label: "被挡后退避（秒）",
    hint: "遇 403 / 429 停多久再试",
    kind: "number",
  },
  { key: "max_retries", label: "重试次数", kind: "number" },
  { key: "timeout", label: "超时（秒）", kind: "number" },
  { key: "user_agent", label: "User-Agent", wide: "full" },
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
      label: `猎聘 token（账号 ${account}）`,
      hint: "没有它搜不了也投不了。去 liepin.com/mcp/auth 生成，过期了回来换一行",
      kind: "secret",
      nullable: true,
      wide: "full",
    },
    {
      key: "rate_limit_per_min",
      label: "接口限速（次/分钟）",
      hint: "实测约 10 次 / 60 秒滑动窗口，触发后冷却 20 分钟以上。调大有风险",
      kind: "number",
    },
    { key: "timeout", label: "超时（秒）", kind: "number" },
    { key: "base_url", label: "接口地址", wide: "full" },
  ];

  return (
    <>
      <SectionForm
        section={search}
        fields={SEARCH_FIELDS}
        title="搜索条件与关键词"
        hint={
          <>
            关键词一行一个，<b>顺序就是优先级</b>：职位按 jobId 去重，每条记到的
            searchKeyword 是最先命中它的那个词，所以最想要的方向放最前面。不想再搜的词
            删掉即可（TOML 数组里注释掉的候选词不受影响，会原样留着）。
          </>
        }
        savedNotice="搜索条件已保存。去「采集任务」跑一次搜索才会按新条件采集。"
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
        <span className="muted">{keywordCount} 个</span>
      </SectionForm>

      <SectionForm
        section={sections.liepin}
        fields={liepinFields}
        title="猎聘账号与限速"
        hint={
          <>
            这一段住全局 <code>config/config.toml</code>，所有 profile 共用。
            token 明文显示：本机单人用，能打开这个页面就能 <code>cat</code> 到那个文件，
            打码只会让人没法在这里填。多账号并存请直接编辑文件的
            <code>[liepin.accounts.*]</code>，再用「高级」页确认。
          </>
        }
        savedNotice="账号与限速已保存。限速改大之后如果开始报 429，改回 8 并等 20 分钟。"
        onSaved={onSaved}
        onFailed={onFailed}
      />

      <SectionForm
        section={sections.detail}
        fields={DETAIL_FIELDS}
        title="详情页抓取节奏"
        hint="抓 JD 走的是普通网页，被挡了就得退避重来。间隔调小会更快，也更容易吃 403。"
        savedNotice="抓取节奏已保存。"
        onSaved={onSaved}
        onFailed={onFailed}
      />
    </>
  );
}
