/**
 * 统一时间格式化 —— 全站时间一律按 Asia/Shanghai 展示为 YYYY-MM-DD HH:mm:ss。
 *
 * 后端已将 ISO 字符串统一带 +08:00 后缀；此处再用 Intl API 强制用上海时区
 * 渲染，可抵御用户浏览器所在时区变化（比如出差换时区时不会错乱）。
 *
 * 注：用 formatToParts 手动拼接而不是拼 toLocaleString 结果，
 *     因为不同 JS 引擎下 locale 字符串的字段顺序不一定稳定。
 */
const CN_FMT = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function pick(parts: Intl.DateTimeFormatPart[], type: string): string {
  return parts.find((p) => p.type === type)?.value ?? '00'
}

function toParts(d: Date) {
  const parts = CN_FMT.formatToParts(d)
  return {
    y: pick(parts, 'year'),
    m: pick(parts, 'month'),
    d: pick(parts, 'day'),
    h: pick(parts, 'hour'),
    mi: pick(parts, 'minute'),
    s: pick(parts, 'second'),
  }
}

/** 把后端 ISO 字符串或 null 格式化为 "YYYY-MM-DD HH:mm:ss"；空值返回 '--'。 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'
  const p = toParts(d)
  // Intl 在午夜可能把 hour 渲染为 '24'，归一化为 '00'
  const h = p.h === '24' ? '00' : p.h
  return `${p.y}-${p.m}-${p.d} ${h}:${p.mi}:${p.s}`
}

/** 只要时间部分 "HH:mm:ss" —— 日志终端用。 */
export function formatTimeOnly(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'
  const p = toParts(d)
  const h = p.h === '24' ? '00' : p.h
  return `${h}:${p.mi}:${p.s}`
}
