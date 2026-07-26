import { PHASES } from './dashboardContracts.js'

export function phaseIndex(phase) {
  return Math.max(0, PHASES.findIndex(([value]) => value === phase))
}

export function statusText(status) {
  if (status === 'queued') return '已排队'
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'evidence_waiting') return '等待证据'
  return '空闲'
}

export function cellText(value) {
  if (value === null || value === undefined || value === '') return 'N/A'
  return String(value)
}

export function statusTone(value) {
  const text = cellText(value).toLowerCase()
  if (['ok', 'success', 'passed', 'completed', '已完成'].some((item) => text.includes(item))) return 'is-ok'
  if (['fail', 'failed', 'error', '缺失'].some((item) => text.includes(item))) return 'is-bad'
  if (['check', 'warning', '等待', '未检查', 'n/a'].some((item) => text.includes(item))) return 'is-warn'
  return 'is-muted'
}

export function technicalTone(value) {
  const text = cellText(value)
  if (text.includes('正向') || text.includes('保留') || text.includes('高分')) return 'is-positive'
  if (text.includes('反向') || text.includes('低分')) return 'is-reverse'
  if (text.includes('过滤')) return 'is-filter'
  if (text.includes('弱')) return 'is-weak'
  return 'is-muted'
}
