/**
 * 角色显示名。
 *
 * 提示词 JSON 里的 `名字` 字段实际是 UUID（如 d3fec12f9d1d4c5b...），
 * 直接展示给用户毫无意义。这里用「地位 + 颜色 + 特征」拼一个人能读懂的标签，
 * 属性全空时退回 UUID 前 8 位。
 *
 * @param {object} c 角色对象，字段：名字 / 地位 / 服装颜色 / 特殊 / 性别 / 年龄
 * @param {number} [index] 可选序号（属性相同的角色靠它区分）
 * @returns {string}
 */
export function characterDisplayName(c, index) {
  if (!c) return ''
  const parts = [c.地位 || c.rank, c.服装颜色 || c.color, c.特殊 || c.special]
    .filter(Boolean)
  if (parts.length) {
    const base = parts.join(' · ')
    return index !== undefined ? `${index + 1}. ${base}` : base
  }
  // 属性全空：用 UUID 前 8 位兜底
  const raw = String(c.名字 || c.name || '')
  return raw ? raw.slice(0, 8) : `角色 ${(index ?? 0) + 1}`
}

/**
 * 角色属性摘要（性别 · 年龄 · 体型）
 */
export function characterMeta(c) {
  if (!c) return ''
  return [
    c.性别 || c.gender,
    c.年龄 || c.age,
    c.体型 || c.body_type,
  ].filter(Boolean).join(' · ')
}
