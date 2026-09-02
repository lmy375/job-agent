/**
 * 展示层的格式化。
 *
 * 后端模型里时间就是 datetime，接口吐的是 ISO 8601——
 * 怎么显示是前端的事，后端不预先转成字符串（见 CLAUDE.md 硬规则）。
 */

export function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? value : at.toLocaleString();
}

/**
 * 职位类型（`jobType`）的展示名：**谁在招**。
 *
 * 取值只有两个（`core/liepin/enums.py` 的 `JobKind`），但库里的列是裸字符串，
 * 老数据可能是空串——所以这里必须兜底，不能直接查表。
 */
export function jobKindLabel(jobType: string): string {
  if (jobType === "2") return "HR 岗位";
  if (jobType === "1") return "猎头岗位";
  return "未标记";
}
