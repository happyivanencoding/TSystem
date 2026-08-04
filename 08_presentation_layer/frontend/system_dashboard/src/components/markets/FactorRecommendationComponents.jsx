import React, { useEffect, useMemo, useState } from 'react'
import { BarChart3, ShieldCheck, TrendingUp } from 'lucide-react'

import {
  EMPTY_FACTOR_RECOMMENDATION,
  FACTOR_RECOMMENDATION_REGIONS,
} from '../../domain/dashboardContracts.js'
import { cellText, statusTone } from '../../domain/formatters.js'

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function displayValue(value) {
  if (value === undefined || value === null || value === '') return '—'
  if (Array.isArray(value)) return value.map((item) => displayValue(item)).join(' / ')
  if (isRecord(value)) {
    const shortValue = value.label ?? value.name ?? value.title ?? value.text ?? value.value ?? value.status
    if (shortValue !== undefined) return cellText(shortValue)
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${displayValue(item)}`)
      .join(' / ')
  }
  return cellText(value)
}

function listItems(value) {
  if (Array.isArray(value)) return value
  if (value === undefined || value === null || value === '') return []
  if (isRecord(value)) {
    return Object.entries(value).map(([key, item]) => (
      isRecord(item) ? { ...item, label: item.label || key } : `${key}: ${displayValue(item)}`
    ))
  }
  return [value]
}

function regionCode(value) {
  const text = cellText(value).toUpperCase()
  if (['USA', 'AMERICA', 'NORTH AMERICA'].includes(text)) return 'US'
  if (['EUROPE', 'EMU', 'EURO AREA'].includes(text)) return 'EU'
  if (text.includes('ASIA')) return 'ASIA'
  return text
}

function uniqueValues(values) {
  return [...new Set(values.filter(Boolean))]
}

function safeRow(value) {
  return isRecord(value) ? value : { value }
}

function FactorTable({ columns, rows, empty = '暂无数据' }) {
  const safeRows = Array.isArray(rows) ? rows : []
  if (!safeRows.length) return <div className="tp-empty">{empty}</div>
  return (
    <div className="tp-table-wrap">
      <table className="tp-data-table">
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {safeRows.map((row, rowIndex) => {
            const safeRowValue = safeRow(row)
            return (
              <tr key={`${safeRowValue.region || 'row'}-${safeRowValue.factor || safeRowValue.latest_date || safeRowValue.月份 || rowIndex}-${rowIndex}`}>
                {columns.map((column) => (
                  <td key={column} title={displayValue(safeRowValue[column])}>{displayValue(safeRowValue[column])}</td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Metric({ label, value }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{displayValue(value)}</strong>
    </div>
  )
}

function WarningList({ warnings }) {
  const items = uniqueValues(listItems(warnings).map((item) => displayValue(item)))
  if (!items.length) return <div className="tp-empty">暂无 warnings</div>
  return (
    <div className="tp-market-brief-meta">
      {items.map((item) => <span className={`tp-status-pill ${statusTone(item)}`} key={item}>{item}</span>)}
    </div>
  )
}

function EvidenceList({ title, items, empty }) {
  const safeItems = listItems(items)
  return (
    <section className="tp-model-section">
      <div className="tp-model-section-head">
        <div>
          <p className="tp-kicker">Evidence</p>
          <h3>{title}</h3>
        </div>
        <span>{safeItems.length} items</span>
      </div>
      {safeItems.length ? (
        <ul className="tp-sector-evidence-list">
          {safeItems.map((item, index) => (
            <li key={`${title}-${index}`}>{displayValue(item)}</li>
          ))}
        </ul>
      ) : (
        <div className="tp-empty">{empty}</div>
      )}
    </section>
  )
}

function validationRows(value, type) {
  return listItems(value).map((item, index) => {
    if (!isRecord(item)) return { type, name: `${type} ${index + 1}`, status: displayValue(item), detail: '' }
    return {
      type,
      name: item.name || item.label || item.gate || item.metric || `${type} ${index + 1}`,
      status: item.status || item.result || item.outcome || item.value,
      detail: item.detail || item.evidence || item.message || item.description || '',
    }
  })
}

function benchmarkRows(value) {
  if (!isRecord(value)) return value ? [{ field: 'definition', value }] : []
  return Object.entries(value).map(([field, item]) => ({ field, value: displayValue(item) }))
}

export function FactorRecommendationPanel({
  factorRecommendationHistoryRows = [],
  factorRecommendationRows = [],
  factorRecommendationSignal = EMPTY_FACTOR_RECOMMENDATION,
  moduleDragProps,
  panelClass,
}) {
  const sourceSignal = isRecord(factorRecommendationSignal) ? factorRecommendationSignal : {}
  const rows = Array.isArray(factorRecommendationRows) ? factorRecommendationRows : []
  const historyRows = Array.isArray(factorRecommendationHistoryRows) ? factorRecommendationHistoryRows : []
  const status = sourceSignal.status || EMPTY_FACTOR_RECOMMENDATION.status
  const snapshotMode = sourceSignal.mode === 'exposure_snapshot'
  const researchOnly = sourceSignal.research_only ?? status === 'research_only'
  const missing = sourceSignal.missing ?? rows.length === 0
  const stale = sourceSignal.stale ?? status === 'stale'
  const signal = {
    ...EMPTY_FACTOR_RECOMMENDATION,
    ...sourceSignal,
    status,
    research_only: researchOnly,
    missing,
    stale,
    warnings: sourceSignal.warnings !== undefined
      ? sourceSignal.warnings
      : (researchOnly || missing || stale ? EMPTY_FACTOR_RECOMMENDATION.warnings : []),
  }
  const configuredRegions = listItems(signal.regions)
    .map((item) => (isRecord(item) ? item.region || item.market || item.code || item.name || item.label : item))
    .filter(Boolean)
  const regions = uniqueValues([
    ...FACTOR_RECOMMENDATION_REGIONS,
    ...configuredRegions,
    ...rows.map((item) => safeRow(item).region),
  ])
  const [activeRegion, setActiveRegion] = useState(regions[0] || FACTOR_RECOMMENDATION_REGIONS[0])

  useEffect(() => {
    if (!regions.some((region) => regionCode(region) === regionCode(activeRegion))) {
      setActiveRegion(regions[0] || FACTOR_RECOMMENDATION_REGIONS[0])
    }
  }, [activeRegion, regions])

  const activeRows = useMemo(
    () => rows.filter((item) => regionCode(safeRow(item).region) === regionCode(activeRegion)),
    [activeRegion, rows],
  )
  const activeRow = safeRow(activeRows[0])
  const factorTableRows = activeRows.map((item) => {
    const row = safeRow(item)
    return {
      ...row,
      factor: row.factor || row.factor_label,
      predicted_active_return: snapshotMode ? 'N/A (not a forecast)' : row.predicted_active_return,
      score_0_100: row.score_0_100 ?? row.score,
      neutral_weight: row.neutral_weight ?? row.neutral,
      recommended_weight: row.recommended_weight ?? row.recommended,
      warning: Array.isArray(row.warnings) ? row.warnings.join(' / ') : row.warnings,
    }
  })
  const activeHistoryRows = historyRows.filter(
    (item) => !safeRow(item).region || regionCode(safeRow(item).region) === regionCode(activeRegion),
  )
  const warnings = uniqueValues([
    ...listItems(signal.warnings).map((item) => displayValue(item)),
    ...listItems(activeRow.warnings).map((item) => displayValue(item)),
  ])
  const benchmarkDefinition = isRecord(signal.benchmark_definition) && Object.keys(signal.benchmark_definition).length
    ? signal.benchmark_definition
    : signal.benchmark_definition || signal.benchmark
  const benchmark = benchmarkRows(benchmarkDefinition)
  const backtestRows = validationRows(signal.backtest, 'backtest')
  const baselineRows = validationRows(signal.baselines, 'baseline')
  const gateRows = validationRows(signal.gates, 'gate')
  const panelProps = typeof panelClass === 'function'
    ? panelClass('results', 'factor-recommendation', 'tp-wide-panel')
    : 'tp-panel tp-wide-panel is-active-module'
  const dragProps = typeof moduleDragProps === 'function'
    ? moduleDragProps('results', 'factor-recommendation')
    : {}
  const statusClass = researchOnly ? 'is-warn' : statusTone(signal.status)

  return (
    <div className={panelProps} {...dragProps}>
      <div className="tp-panel-heading">
        <div>
          <p className="tp-kicker">Signals / Factor Recommendation</p>
          <h2 className="tp-heading-icon"><BarChart3 size={18} />月度因子推荐</h2>
        </div>
        <span className={`tp-status-pill ${statusClass}`}>{displayValue(signal.status)}</span>
      </div>

      <div className="tp-country-status-row">
        <Metric label="Latest month" value={signal.latest_date || activeRow.latest_date} />
        <Metric label="Status" value={signal.status} />
        <Metric label="Research only" value={researchOnly ? 'research_only' : 'no'} />
        <Metric label="Rows" value={rows.length} />
        <Metric label="Updated" value={signal.updated_at} />
      </div>

      {researchOnly && (
        <div className="tp-panel-note">
          <ShieldCheck size={14} /> 当前结果仅供 research_only 研究审阅，未进入生产推荐。
        </div>
      )}
      {snapshotMode && (
        <div className="tp-panel-note">
          Exposure snapshot / Not a forecast / Research v1 invalidated
        </div>
      )}
      <div className="tp-panel-note">{signal.message ? displayValue(signal.message) : 'Factor Recommendation / 月度因子推荐'}</div>

      <div aria-label="Factor recommendation regions" className="tp-segmented-control">
        {regions.map((region) => (
          <button
            aria-pressed={regionCode(region) === regionCode(activeRegion) ? 'true' : 'false'}
            className={regionCode(region) === regionCode(activeRegion) ? 'is-active' : ''}
            key={region}
            onClick={() => setActiveRegion(region)}
            type="button"
          >
            {region}
          </button>
        ))}
      </div>

      <section className="tp-model-section">
        <div className="tp-model-section-head">
          <div>
            <p className="tp-kicker">Latest recommendation / {activeRegion}</p>
            <h3><TrendingUp size={16} />最新排名与推荐</h3>
          </div>
          <span>{activeRow.latest_date || signal.latest_date || 'N/A'}</span>
        </div>
        <div className="tp-country-status-row">
          <Metric label="Latest rank" value={activeRow.rank} />
          <Metric label="Score" value={activeRow.score} />
          <Metric
            label="Recommended vs neutral"
            value={`${displayValue(activeRow.recommended_return)} / ${displayValue(activeRow.neutral_return)}`}
          />
          {snapshotMode ? <Metric label="Mode" value="Exposure snapshot" /> : <Metric label="Predicted return" value={activeRow.predicted_return} />}
          <Metric label="Confidence" value={activeRow.confidence} />
        </div>
        {!activeRows.length && (
          <div className="tp-empty">
            {signal.status === 'research_only' ? '暂无可展示的研究结果，等待该区域的月度因子证据。' : '暂无该区域的月度因子推荐。'}
          </div>
        )}
        <FactorTable
          columns={['factor', 'rank', 'predicted_active_return', 'score_0_100', 'stance', 'neutral_weight', 'recommended_weight', 'confidence', 'coverage', 'warning']}
          empty="暂无该区域的因子排名"
          rows={factorTableRows}
        />
        <div className="tp-country-dashboard">
          <div className="tp-country-column">
            <div className="tp-model-section-head">
              <div>
                <p className="tp-kicker">Drivers</p>
                <h3>推荐驱动</h3>
              </div>
            </div>
            <EvidenceList title="Drivers" items={activeRow.drivers} empty="暂无 drivers" />
          </div>
          <div className="tp-country-column">
            <div className="tp-model-section-head">
              <div>
                <p className="tp-kicker">Warnings</p>
                <h3>风险提示</h3>
              </div>
            </div>
            <WarningList warnings={warnings} />
          </div>
        </div>
      </section>

      <section className="tp-model-section">
        <div className="tp-model-section-head">
          <div>
            <p className="tp-kicker">History</p>
            <h3>月度历史</h3>
          </div>
          <span>{activeHistoryRows.length} rows</span>
        </div>
        <FactorTable
          columns={['region', 'factor', 'latest_date', 'rank', 'score_0_100', 'stance', 'predicted_active_return', 'confidence', 'coverage']}
          empty="暂无 history"
          rows={activeHistoryRows}
        />
      </section>

      <EvidenceList title="Evidence" items={signal.evidence} empty="暂无 evidence" />

      <section className="tp-model-section">
        <div className="tp-model-section-head">
          <div>
            <p className="tp-kicker">Validation</p>
            <h3>Backtest / baselines / gates</h3>
          </div>
          <span>{backtestRows.length + baselineRows.length + gateRows.length} checks</span>
        </div>
        <FactorTable
          columns={['type', 'name', 'status', 'detail']}
          empty="暂无 backtest / baselines / gates"
          rows={[...backtestRows, ...baselineRows, ...gateRows]}
        />
      </section>

      <section className="tp-model-section">
        <div className="tp-model-section-head">
          <div>
            <p className="tp-kicker">Benchmark definition</p>
            <h3>基准定义</h3>
          </div>
          <span>{Object.keys(isRecord(benchmarkDefinition) ? benchmarkDefinition : {}).length || 'N/A'} fields</span>
        </div>
        <FactorTable columns={['field', 'value']} empty="暂无 benchmark definition" rows={benchmark} />
      </section>
    </div>
  )
}
