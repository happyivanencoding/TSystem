import React from 'react'

import { cellText } from '../../domain/formatters.js'

function regimeProfile(item) {
  const text = `${item.regime || ''} ${item.state || ''}`.toLowerCase()
  const budget = Number.parseFloat(item.risk_budget)
  if (text.includes('risk-off') || text.includes('衰退') || text.includes('压力') || text.includes('收缩') || text.includes('危机')) {
    return { angle: -58, label: 'Risk-Off', tone: 'is-risk-off', color: '#b33f55', soft: '#f8e7eb' }
  }
  if (text.includes('risk-on') || text.includes('扩张') || budget > 1.02) {
    return { angle: 58, label: 'Risk-On', tone: 'is-risk-on', color: '#167768', soft: '#e7f3ef' }
  }
  if (text.includes('震荡') || budget < 0.98) {
    return { angle: -12, label: 'Neutral / Choppy', tone: 'is-neutral', color: '#9a6b18', soft: '#fbf1dc' }
  }
  return { angle: 0, label: 'Neutral', tone: 'is-neutral', color: '#315d9f', soft: '#e9eef8' }
}

export function RegimeGauge({ item }) {
  const profile = regimeProfile(item)
  return (
    <div
      className={`tp-regime-meter ${profile.tone}`}
      style={{
        '--needle-angle': `${profile.angle}deg`,
        '--regime-color': profile.color,
        '--regime-soft': profile.soft,
      }}
    >
      <div className="tp-regime-meter-head">
        <span>{cellText(item.region)}</span>
        <strong>{profile.label}</strong>
      </div>
      <div className="tp-regime-gauge" aria-label={`${cellText(item.region)} ${profile.label}`}>
        <div className="tp-regime-arc">
          <span className="tp-regime-needle" />
          <span className="tp-regime-pin" />
        </div>
        <div className="tp-regime-scale">
          <span>Risk-Off</span>
          <span>Neutral</span>
          <span>Risk-On</span>
        </div>
      </div>
      <div className="tp-regime-readout">
        <strong>{cellText(item.regime)}</strong>
        <span>{cellText(item.risk_budget)} risk budget / {cellText(item.最新月份)}</span>
      </div>
    </div>
  )
}

function scoreWidth(value) {
  const number = Number.parseFloat(value)
  if (!Number.isFinite(number)) return '0%'
  return `${Math.max(0, Math.min(100, number * 100))}%`
}

export function StateModelMatrix({ rows }) {
  if (!rows.length) return <div className="tp-empty">暂无状态模型结果</div>
  return (
    <div className="tp-model-matrix">
      {rows.map((row) => {
        const profile = regimeProfile({ regime: row.regime, risk_budget: row.state === '0' ? '1.10' : '' })
        return (
          <div
            className="tp-model-strip"
            key={`${row.region}-${row.model}`}
            style={{ '--model-color': profile.color, '--model-soft': profile.soft }}
          >
            <div className="tp-model-strip-head">
              <span>{cellText(row.region)}</span>
              <strong>{cellText(row.model)}</strong>
            </div>
            <div className="tp-model-strip-main">
              <span className="tp-model-dot" />
              <div>
                <strong>{cellText(row.regime)}</strong>
                <small>{cellText(row.as_of)} / state {cellText(row.state)} / {cellText(row.agreement || 'N/A')}</small>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function RiskModelMeters({ rows }) {
  if (!rows.length) return <div className="tp-empty">暂无 Ridge 风险预测</div>
  return (
    <div className="tp-risk-meter-grid">
      {rows.map((row) => (
        <div className="tp-risk-meter" key={`${row.region}-${row.model}`}>
          <div className="tp-risk-meter-top">
            <span>{cellText(row.region)}</span>
            <strong>{cellText(row.equity_weight_pct)}</strong>
          </div>
          <div className="tp-risk-meter-bar" aria-label={`${row.region} equity weight`}>
            <span style={{ width: scoreWidth(row.equity_weight) }} />
          </div>
          <div className="tp-risk-meter-meta">
            <span>Ridge vol {cellText(row.pred_vol_pct)}</span>
            <span>target {cellText(row.target_vol_pct)}</span>
          </div>
          <small>{cellText(row.top_driver)} {cellText(row.top_driver_contrib)}</small>
        </div>
      ))}
    </div>
  )
}

export function ModelRankList({ icon: Icon, title, rows }) {
  const visibleRows = rows.slice(0, 6)
  return (
    <div className="tp-rank-list">
      <div className="tp-rank-title">
        <Icon size={16} />
        <strong>{title}</strong>
      </div>
      {visibleRows.map((row) => (
        <div className="tp-rank-row" key={`${title}-${row.region}-${row.rank}-${row.model}`}>
          <div className="tp-rank-row-head">
            <span>{cellText(row.region)} #{cellText(row.rank)} {cellText(row.model)}</span>
            <strong>{cellText(row.score_text)}</strong>
          </div>
          <div className="tp-rank-bar">
            <span style={{ width: scoreWidth(row.score) }} />
          </div>
          <small>
            {cellText(row.metric)} / secondary {cellText(row.secondary || 'N/A')}
            {row.annual_return ? ` / ann ${cellText(row.annual_return)}%` : ''}
            {row.sharpe ? ` / Sharpe ${cellText(row.sharpe)}` : ''}
          </small>
        </div>
      ))}
      {!visibleRows.length && <div className="tp-empty">暂无模型排名</div>}
    </div>
  )
}

