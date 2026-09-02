/**
 * 展示层的格式化。
 *
 * 后端模型里时间就是 datetime，接口吐的是 ISO 8601——
 * 怎么显示是前端的事，后端不预先转成字符串（见 CLAUDE.md 硬规则）。
 */

export function formatTime(value) {
  if (!value) return "";
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? value : at.toLocaleString();
}
