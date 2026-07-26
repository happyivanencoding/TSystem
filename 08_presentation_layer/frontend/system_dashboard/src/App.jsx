import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  BarChart3,
  Building2,
  CheckCircle2,
  Cpu,
  Database,
  Factory,
  Gauge,
  HeartPulse,
  Home,
  Landmark,
  Loader2,
  Play,
  RefreshCw,
  Server,
  ShieldCheck,
  ShoppingBag,
  TrendingUp,
  Truck,
  X,
  Zap,
} from 'lucide-react'

const API_BASE = import.meta.env.VITE_TP_DASHBOARD_API || ''
const MODULE_ORDER_STORAGE_KEY = 'tp-dashboard-module-order-v1'
const DEFAULT_MODULE_ORDER = {
  market: ['brief'],
  production: ['overview', 'alerts', 'run-control', 'live-job', 'queue', 'core-database', 'project-assets', 'pipeline-status', 'data-assets'],
  results: ['regime', 'country', 'sector', 'score-ml', 'factor-explorer'],
  technical: ['latest'],
}
const NAV_SECTIONS = [
  {
    page: 'market',
    label: '市场概况',
    description: '最新市场讯息',
    modules: [
      ['brief', '市场概况', '欧美金融市场日内复盘'],
    ],
  },
  {
    page: 'results',
    label: '结果展示',
    description: '模型、信号和组合结果',
    modules: [
      ['regime', 'Regime', '市场状态识别'],
      ['country', 'Country', '国家与区域评分'],
      ['sector', 'Sector', '行业推荐'],
      ['score-ml', 'Score ML', '组合成分对比'],
      ['factor-explorer', '因子研究', '四市场收益、ratio、经济含义与稳健性证据'],
    ],
  },
  {
    page: 'technical',
    label: '技术面',
    description: '最新 Technical metrics',
    modules: [
      ['latest', 'Technical', '按市场查看最新技术面'],
    ],
  },
  {
    page: 'production',
    label: '生产流程',
    description: '系统运行、队列、资产和 pipeline',
    modules: [
      ['overview', '总览', '状态快照与核心指标'],
      ['alerts', '告警', '生产健康信号'],
      ['run-control', '启动任务', '运行 pipeline 与检查'],
      ['live-job', '实时任务', '当前 job 与日志'],
      ['queue', '任务队列', '后台队列任务'],
      ['core-database', '核心数据库', '数据资产质量'],
      ['project-assets', '项目资产', '项目产物覆盖'],
      ['pipeline-status', 'Pipeline 状态', '步骤完成情况'],
      ['data-assets', '数据资产', '注册与发现资产'],
    ],
  },
]
const DEFAULT_MODULE_BY_PAGE = Object.fromEntries(NAV_SECTIONS.map((section) => [section.page, section.modules[0][0]]))
const MODULE_PAGE = Object.fromEntries(NAV_SECTIONS.flatMap((section) => section.modules.map(([id]) => [id, section.page])))
const DEFAULT_PAGE = NAV_SECTIONS[0].page
const COUNTRY_FLAGS = {
  EM: '🌐',
  EMU: '🇪🇺',
  EU: '🇪🇺',
  Europe: '🇪🇺',
  France: '🇫🇷',
  Germany: '🇩🇪',
  Italy: '🇮🇹',
  Japan: '🇯🇵',
  Spain: '🇪🇸',
  UK: '🇬🇧',
  US: '🇺🇸',
  USA: '🇺🇸',
}
const SECTOR_ICON_KEYS = [
  ['bank', Landmark],
  ['financial', Landmark],
  ['technology', Cpu],
  ['tech', Cpu],
  ['industrial', Factory],
  ['health', HeartPulse],
  ['consumer', ShoppingBag],
  ['retail', ShoppingBag],
  ['energy', Zap],
  ['utility', Zap],
  ['real estate', Home],
  ['property', Home],
  ['transport', Truck],
]

const PHASES = [
  ['submitted', '已提交'],
  ['running', '运行中'],
  ['evidence', '等证据'],
  ['done', '完成'],
]

const DEFAULT_PIPELINE_PAYLOAD = {
  step: 'run_all',
  input_month: '',
  as_of: '',
  update_mode: 'both',
  flags: ['skip_refresh', 'skip_backtest', 'dry_run_data', 'inspect_backtest'],
  top_pct: 0.1,
  ml_weight: 0.7,
  technical_weight: 0.3,
  max_weight: 0.05,
  optimizer_method: 'constrained',
  portfolio_region: '',
  backtest_profile: 'default',
  bench: '',
  start_date: '',
  percentile: null,
}

const EMPTY_JOB = {
  job_id: '',
  step: '暂无启动任务',
  status: 'idle',
  status_label: 'IDLE',
  phase: 'submitted',
  pid: '',
  started_at: '',
  manifest_status: 'N/A',
  manifest: '',
  log_path: '',
  log_tail: '',
  backend: '',
  queue_name: '',
  queued_at: '',
  status_updated_at: '',
  finished_at: '',
  returncode: '',
  error: '',
}

const EMPTY_DASHBOARD_STATE = {
  generated_at: '',
  overview: [],
  latest_market_brief: {
    status: 'missing',
    title: '',
    created: '',
    source_scope: '',
    okf_refresh: '',
    path: '',
    okf_path: '',
    updated_at: '',
    sections: [],
    section_count: '0',
  },
  alerts: [],
  projects: [],
  assets: [],
  core_database: [],
  pipeline: [],
  signals: {
    regime: {
      status: 'missing',
      latest_date: '',
      updated_at: '',
      signal_path: '',
      rows: [],
      history: [],
      models: {
        status: 'missing',
        updated_at: '',
        state_models: [],
        risk_models: [],
        direction_models: [],
        volatility_models: [],
        drawdown_models: [],
      },
      message: '',
    },
    country: {
      status: 'missing',
      latest_date: '',
      updated_at: '',
      signal_path: '',
      database_path: '',
      single_country_path: '',
      rows: [],
      history: [],
      single_country_rows: [],
      single_country_history: [],
      message: '',
    },
    sector: {
      status: 'missing',
      latest_date: '',
      updated_at: '',
      paths: {},
      monthly_report: { status: 'missing', month: '', path: '', sectors: '0', updated_at: '' },
      rotation: {
        status: 'missing',
        latest_date: '',
        methodology: '',
        benchmark: '',
        markets: [],
      },
      markets: [],
      rows: [],
      message: '',
    },
    technical: {
      status: 'missing',
      latest_date: '',
      screen_date: '',
      pattern_date: '',
      period_end: '',
      available_date: '',
      updated_at: '',
      signal_path: '',
      screen_path: '',
      availability_note: '',
      metric_definitions: [],
      markets: [],
      metric_rows: [],
      security_rows: [],
      message: '',
    },
    score_ml_components: {
      status: 'missing',
      selected_date: '',
      selected_side: 'top',
      default_date: '',
      default_side: 'top',
      date_options: [],
      rows: [],
      run_dir: '',
      screen_date: '',
      message: '',
    },
  },
  queue: {
    queue_name: '',
    thread_worker_alive: false,
    in_memory_pending: 0,
    total_records: 0,
    counts: { queued: 0, running: 0, completed: 0, failed: 0, other: 0 },
    latest_job_id: '',
    recent: [],
  },
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    ...options,
  })
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`)
  }
  return payload
}

function phaseIndex(phase) {
  return Math.max(0, PHASES.findIndex(([value]) => value === phase))
}

function statusText(status) {
  if (status === 'queued') return '已排队'
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'evidence_waiting') return '等待证据'
  return '空闲'
}

function cellText(value) {
  if (value === null || value === undefined || value === '') return 'N/A'
  return String(value)
}

function parseDashboardRoute(hash = '') {
  const [rawPage, rawModule] = hash.replace(/^#/, '').split('/')
  const page = NAV_SECTIONS.some((section) => section.page === rawPage) ? rawPage : MODULE_PAGE[rawModule] || DEFAULT_PAGE
  const moduleId = MODULE_PAGE[rawModule] === page ? rawModule : DEFAULT_MODULE_BY_PAGE[page]
  return { page, moduleId }
}

function loadModuleOrder() {
  if (typeof window === 'undefined') return DEFAULT_MODULE_ORDER
  try {
    const parsed = JSON.parse(window.localStorage.getItem(MODULE_ORDER_STORAGE_KEY) || '{}')
    return Object.fromEntries(
      NAV_SECTIONS.map((section) => [
        section.page,
        mergeModuleOrder(parsed[section.page], DEFAULT_MODULE_ORDER[section.page]),
      ]),
    )
  } catch {
    return DEFAULT_MODULE_ORDER
  }
}

function mergeModuleOrder(savedOrder, defaultOrder) {
  if (!Array.isArray(savedOrder)) return defaultOrder
  const known = savedOrder.filter((item) => defaultOrder.includes(item))
  return [...known, ...defaultOrder.filter((item) => !known.includes(item))]
}

function saveModuleOrder(order) {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(MODULE_ORDER_STORAGE_KEY, JSON.stringify(order))
  }
}

function moveItem(items, fromId, toId) {
  if (!fromId || !toId || fromId === toId) return items
  const next = [...items]
  const fromIndex = next.indexOf(fromId)
  const toIndex = next.indexOf(toId)
  if (fromIndex < 0 || toIndex < 0) return items
  next.splice(fromIndex, 1)
  next.splice(toIndex, 0, fromId)
  return next
}

function countryFlag(value) {
  const text = cellText(value)
  return COUNTRY_FLAGS[text] || COUNTRY_FLAGS[text.toUpperCase()] || '🌐'
}

function sectorIconFor(value) {
  const text = cellText(value).toLowerCase()
  const match = SECTOR_ICON_KEYS.find(([keyword]) => text.includes(keyword))
  return match ? match[1] : Building2
}

function statusTone(value) {
  const text = cellText(value).toLowerCase()
  if (['ok', 'success', 'passed', 'completed', '已完成'].some((item) => text.includes(item))) return 'is-ok'
  if (['fail', 'failed', 'error', '缺失'].some((item) => text.includes(item))) return 'is-bad'
  if (['check', 'warning', '等待', '未检查', 'n/a'].some((item) => text.includes(item))) return 'is-warn'
  return 'is-muted'
}

function technicalTone(value) {
  const text = cellText(value)
  if (text.includes('正向') || text.includes('保留') || text.includes('高分')) return 'is-positive'
  if (text.includes('反向') || text.includes('低分')) return 'is-reverse'
  if (text.includes('过滤')) return 'is-filter'
  if (text.includes('弱')) return 'is-weak'
  return 'is-muted'
}

function ActionButton({ icon: Icon, label, description, disabled, active = false, busy = false, onClick }) {
  const ButtonIcon = busy ? Loader2 : Icon
  return (
    <button
      aria-busy={busy ? 'true' : 'false'}
      className={active ? 'tp-action-button is-active' : 'tp-action-button'}
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      <ButtonIcon className={busy ? 'tp-spin' : ''} size={18} />
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
    </button>
  )
}

function StatusPill({ value }) {
  return <span className={`tp-status-pill ${statusTone(value)}`}>{cellText(value)}</span>
}

function PageTabs({ activePage, activeModule, onChange, onModuleChange }) {
  return (
    <nav className="tp-page-tabs" aria-label="Dashboard navigation">
      {NAV_SECTIONS.map((section) => (
        <section className="tp-nav-section" key={section.page}>
          <button
            className={activePage === section.page ? 'tp-nav-group is-active' : 'tp-nav-group'}
            onClick={() => onChange(section.page)}
            type="button"
          >
            <strong>{section.label}</strong>
            <span>{section.description}</span>
          </button>
          {section.modules.length > 1 && (
            <div className="tp-nav-modules">
              {section.modules.map(([id, label, description]) => (
                <button
                  className={activeModule === id ? 'tp-nav-module is-active' : 'tp-nav-module'}
                  key={id}
                  onClick={() => onModuleChange(section.page, id)}
                  type="button"
                >
                  <strong>{label}</strong>
                  <span>{description}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      ))}
    </nav>
  )
}

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

function RegimeGauge({ item }) {
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

function StateModelMatrix({ rows }) {
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

function RiskModelMeters({ rows }) {
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

function ModelRankList({ icon: Icon, title, rows }) {
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

const COUNTRY_FACTORS = [
  ['margin', 'Margin'],
  ['profitability', 'Profit'],
  ['growth', 'Growth'],
  ['value', 'Value'],
  ['momentum', 'Momentum'],
]

function countryScoreWidth(value) {
  const number = Number.parseFloat(value)
  if (!Number.isFinite(number)) return '0%'
  return `${Math.max(0, Math.min(100, number * 10))}%`
}

function countryProfile(item) {
  const score = Number.parseFloat(item.score)
  const recommendation = cellText(item.recommendation).toLowerCase()
  if (recommendation.includes('positive') || score >= 6.6) {
    return { label: 'Positive', color: '#167768', soft: '#e7f3ef' }
  }
  if (recommendation.includes('negative') || score <= 4.2) {
    return { label: 'Negative', color: '#b33f55', soft: '#f8e7eb' }
  }
  return { label: 'Neutral', color: '#315d9f', soft: '#e9eef8' }
}

function CountryFactorBars({ item }) {
  return (
    <div className="tp-country-factors">
      {COUNTRY_FACTORS.map(([key, label]) => (
        <div className="tp-country-factor" key={key}>
          <span>{label}</span>
          <div className="tp-country-factor-track">
            <i style={{ width: countryScoreWidth(item[key]) }} />
          </div>
          <strong>{cellText(item[key])}</strong>
        </div>
      ))}
    </div>
  )
}

function CountryRegionCard({ item }) {
  const profile = countryProfile(item)
  const flag = countryFlag(item.region)
  return (
    <div
      className="tp-country-card"
      style={{ '--country-color': profile.color, '--country-soft': profile.soft }}
    >
      <div className="tp-country-card-head">
        <div className="tp-country-title">
          <b>{flag}</b>
          <div>
            <span>{cellText(item.country_label)}</span>
            <strong>{cellText(item.region)}</strong>
          </div>
        </div>
        <em>{cellText(item.recommendation || profile.label)}</em>
      </div>
      <div className="tp-country-score-line">
        <strong>{cellText(item.score)}</strong>
        <span>rank #{cellText(item.rank)} / {cellText(item.最新月份)}</span>
      </div>
      <div className="tp-country-score-track" aria-label={`${item.region} country score`}>
        <i style={{ width: countryScoreWidth(item.score) }} />
      </div>
      <div className="tp-country-card-meta">
        <span>rank change {cellText(item.rank_delta)}</span>
        <span>{cellText(item.model)}</span>
      </div>
      <CountryFactorBars item={item} />
    </div>
  )
}

function SingleCountryTile({ item }) {
  const profile = countryProfile(item)
  const flag = countryFlag(item.country)
  return (
    <div
      className="tp-single-country-tile"
      style={{ '--country-color': profile.color, '--country-soft': profile.soft }}
    >
      <div className="tp-single-country-head">
        <span><b>{flag}</b>{cellText(item.country)}</span>
        <strong>#{cellText(item.rank)}</strong>
      </div>
      <small>{cellText(item.country_label)}</small>
      <div className="tp-single-country-score">
        <strong>{cellText(item.score)}</strong>
        <div className="tp-country-score-track">
          <i style={{ width: countryScoreWidth(item.score) }} />
        </div>
      </div>
    </div>
  )
}

function SingleCountryBoard({ rows }) {
  if (!rows.length) return <div className="tp-empty">暂无单个国家分数</div>
  const [leader, ...rest] = rows
  const leaderProfile = countryProfile(leader)
  const leaderFlag = countryFlag(leader.country)
  return (
    <div className="tp-single-country-board">
      <div
        className="tp-country-leader"
        style={{ '--country-color': leaderProfile.color, '--country-soft': leaderProfile.soft }}
      >
        <div className="tp-country-card-head">
          <div className="tp-country-title">
            <b>{leaderFlag}</b>
            <div>
              <span>Top single country</span>
              <strong>{cellText(leader.country)}</strong>
            </div>
          </div>
          <em>#{cellText(leader.rank)}</em>
        </div>
        <div className="tp-country-score-line">
          <strong>{cellText(leader.score)}</strong>
          <span>{cellText(leader.country_label)} / {cellText(leader.最新月份)}</span>
        </div>
        <div className="tp-country-score-track" aria-label={`${leader.country} country score`}>
          <i style={{ width: countryScoreWidth(leader.score) }} />
        </div>
        <CountryFactorBars item={leader} />
      </div>
      <div className="tp-single-country-grid">
        {rest.map((item) => (
          <SingleCountryTile item={item} key={`${item.country}-${item.最新月份}`} />
        ))}
      </div>
    </div>
  )
}

const SECTOR_FACTORS = [
  ['leverage', 'Low leverage'],
  ['margin', 'Margin'],
  ['valuation', 'Value'],
  ['momentum', 'Momentum'],
  ['growth', 'Growth'],
  ['lowvol', 'Low vol'],
  ['factor_score', 'Factor'],
]

const ROTATION_PALETTE = [
  '#167768',
  '#315d9f',
  '#b33f55',
  '#9a6b18',
  '#6c4ca5',
  '#0f7992',
  '#b45f2f',
  '#3c7f42',
  '#a34884',
  '#526a8d',
  '#8d663f',
  '#2e8874',
  '#7954a5',
  '#a54d4d',
  '#57723b',
  '#23718b',
  '#8e596f',
  '#5864a8',
  '#7b6a28',
]

const ROTATION_QUADRANTS = [
  ['Improving', '改善中'],
  ['Leading', '领先'],
  ['Lagging', '落后'],
  ['Weakening', '转弱'],
]

const ROTATION_SECTOR_LABELS = {
  'Automobiles and Parts': 'Autos',
  Banks: 'Banks',
  'Basic Resources': 'Basic',
  Chemicals: 'Chem',
  'Construction and Materials': 'Constr',
  'Financial Services': 'FinSvc',
  'Food, Beverage and Tobacco': 'Food',
  'Health Care': 'Health',
  'Industrial Goods and Services': 'Indust',
  Insurance: 'Insur',
  Media: 'Media',
  Energy: 'Energy',
  'Personal & Household Goods': 'PersGds',
  'Real Estate': 'RE',
  Retail: 'Retail',
  Technology: 'Tech',
  Telecommunications: 'Telco',
  'Travel and Leisure': 'Travel',
  Utilities: 'Util',
}

function rotationSectorLabel(value) {
  return ROTATION_SECTOR_LABELS[value] || value
}

function spreadRotationLabels(nodes, top, bottom, centerX) {
  const placed = new Map()
  const groups = [
    nodes.filter((node) => node.currentX <= centerX).map((node) => ({ ...node, side: 'right' })),
    nodes.filter((node) => node.currentX > centerX).map((node) => ({ ...node, side: 'left' })),
  ]
  groups.forEach((group) => {
    const ordered = group.sort((a, b) => a.currentY - b.currentY)
    const gap = 14
    ordered.forEach((node, index) => {
      node.labelY = Math.max(top + 8, node.currentY, index ? ordered[index - 1].labelY + gap : top + 8)
    })
    if (ordered.length && ordered[ordered.length - 1].labelY > bottom - 8) {
      const overflow = ordered[ordered.length - 1].labelY - (bottom - 8)
      ordered.forEach((node) => {
        node.labelY -= overflow
      })
      for (let index = ordered.length - 2; index >= 0; index -= 1) {
        ordered[index].labelY = Math.min(ordered[index].labelY, ordered[index + 1].labelY - gap)
      }
    }
    ordered.forEach((node) => placed.set(String(node.sector.sector_code), node))
  })
  return placed
}

function SectorRotationMap({ rotation, rows, onSelect }) {
  const markets = rotation?.markets || []
  const [selectedMarket, setSelectedMarket] = useState(markets[0]?.market || '')
  const [trailMonths, setTrailMonths] = useState(6)
  const [hoveredSector, setHoveredSector] = useState('')

  useEffect(() => {
    if (!markets.some((item) => item.market === selectedMarket)) {
      setSelectedMarket(markets[0]?.market || '')
    }
  }, [markets, selectedMarket])

  const market = markets.find((item) => item.market === selectedMarket) || markets[0]
  const chart = useMemo(() => {
    if (!market) return null
    const width = 900
    const height = 520
    const plot = { left: 70, right: 28, top: 28, bottom: 62 }
    const plotWidth = width - plot.left - plot.right
    const plotHeight = height - plot.top - plot.bottom
    const sectors = (market.sectors || [])
      .map((sector, index) => ({
        sector,
        color: ROTATION_PALETTE[index % ROTATION_PALETTE.length],
        points: (sector.points || []).slice(-trailMonths).filter(
          (point) => Number.isFinite(point.relative_strength) && Number.isFinite(point.relative_momentum),
        ),
      }))
      .filter((sector) => sector.points.length)
    const allPoints = sectors.flatMap((sector) => sector.points)
    const maxDeviation = allPoints.reduce(
      (value, point) => Math.max(
        value,
        Math.abs(point.relative_strength - 100),
        Math.abs(point.relative_momentum - 100),
      ),
      0,
    )
    const span = Math.max(2, Math.ceil(maxDeviation * 1.12 * 2) / 2)
    const minimum = 100 - span
    const maximum = 100 + span
    const scaleX = (value) => plot.left + ((value - minimum) / (maximum - minimum)) * plotWidth
    const scaleY = (value) => plot.top + ((maximum - value) / (maximum - minimum)) * plotHeight
    const nodes = sectors.map((item) => {
      const points = item.points.map((point) => ({
        ...point,
        x: scaleX(point.relative_strength),
        y: scaleY(point.relative_momentum),
      }))
      const current = points[points.length - 1]
      return {
        ...item,
        points,
        current,
        currentX: current.x,
        currentY: current.y,
      }
    })
    const labels = spreadRotationLabels(
      nodes,
      plot.top,
      plot.top + plotHeight,
      scaleX(100),
    )
    const ticks = Array.from({ length: 5 }, (_, index) => minimum + ((maximum - minimum) * index) / 4)
    return {
      width,
      height,
      plot,
      plotWidth,
      plotHeight,
      scaleX,
      scaleY,
      nodes,
      labels,
      ticks,
    }
  }, [market, trailMonths])

  if (!market || !chart) {
    return <div className="tp-empty">{rotation?.warning || '暂无可用的行业轮动历史'}</div>
  }

  const hovered = chart.nodes.find((node) => node.sector.sector_name === hoveredSector)
  const openSector = (sector) => {
    const recommendation = rows.find(
      (item) => item.market === market.market && item.sector_name === sector.sector_name,
    )
    if (recommendation) onSelect(recommendation)
  }
  const centerX = chart.scaleX(100)
  const centerY = chart.scaleY(100)

  return (
    <section className="tp-sector-rotation">
      <div className="tp-sector-rotation-head">
        <div>
          <p className="tp-kicker">Relative strength / momentum</p>
          <h3>Sector Rotation Map</h3>
          <span>{rotation.methodology}</span>
        </div>
        <div className="tp-sector-rotation-controls">
          <div aria-label="Rotation market" className="tp-segmented-control">
            {markets.map((item) => (
              <button
                aria-pressed={item.market === market.market ? 'true' : 'false'}
                className={item.market === market.market ? 'is-active' : ''}
                key={item.market}
                onClick={() => setSelectedMarket(item.market)}
                type="button"
              >
                {countryFlag(item.market)} {item.market}
              </button>
            ))}
          </div>
          <div aria-label="Rotation trail length" className="tp-segmented-control">
            {[6, 12].map((months) => (
              <button
                aria-pressed={trailMonths === months ? 'true' : 'false'}
                className={trailMonths === months ? 'is-active' : ''}
                key={months}
                onClick={() => setTrailMonths(months)}
                type="button"
              >
                {months}M
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="tp-sector-rotation-meta">
        <span>{market.market} / 截至 {market.latest_date}</span>
        <span>{rotation.benchmark}</span>
        {hovered && (
          <strong style={{ '--rotation-color': hovered.color }}>
            {hovered.sector.sector_name} / {hovered.current.quadrant} / RS {hovered.current.relative_strength.toFixed(2)} / Mom {hovered.current.relative_momentum.toFixed(2)}
          </strong>
        )}
      </div>
      <div className="tp-sector-rotation-scroll">
        <svg
          aria-label={`${market.market} sector relative strength and momentum rotation map`}
          className="tp-sector-rotation-chart"
          role="img"
          viewBox={`0 0 ${chart.width} ${chart.height}`}
        >
          <rect
            className="is-improving"
            height={centerY - chart.plot.top}
            width={centerX - chart.plot.left}
            x={chart.plot.left}
            y={chart.plot.top}
          />
          <rect
            className="is-leading"
            height={centerY - chart.plot.top}
            width={chart.plot.left + chart.plotWidth - centerX}
            x={centerX}
            y={chart.plot.top}
          />
          <rect
            className="is-lagging"
            height={chart.plot.top + chart.plotHeight - centerY}
            width={centerX - chart.plot.left}
            x={chart.plot.left}
            y={centerY}
          />
          <rect
            className="is-weakening"
            height={chart.plot.top + chart.plotHeight - centerY}
            width={chart.plot.left + chart.plotWidth - centerX}
            x={centerX}
            y={centerY}
          />
          {chart.ticks.map((tick) => (
            <g className="tp-rotation-grid" key={`rotation-grid-${tick}`}>
              <line
                x1={chart.scaleX(tick)}
                x2={chart.scaleX(tick)}
                y1={chart.plot.top}
                y2={chart.plot.top + chart.plotHeight}
              />
              <line
                x1={chart.plot.left}
                x2={chart.plot.left + chart.plotWidth}
                y1={chart.scaleY(tick)}
                y2={chart.scaleY(tick)}
              />
              <text x={chart.scaleX(tick)} y={chart.plot.top + chart.plotHeight + 22}>{tick.toFixed(1)}</text>
              <text x={chart.plot.left - 12} y={chart.scaleY(tick) + 4}>{tick.toFixed(1)}</text>
            </g>
          ))}
          <line className="tp-rotation-axis" x1={centerX} x2={centerX} y1={chart.plot.top} y2={chart.plot.top + chart.plotHeight} />
          <line className="tp-rotation-axis" x1={chart.plot.left} x2={chart.plot.left + chart.plotWidth} y1={centerY} y2={centerY} />
          <text className="tp-rotation-quadrant is-left" x={chart.plot.left + 12} y={chart.plot.top + 22}>IMPROVING · 改善中</text>
          <text className="tp-rotation-quadrant" textAnchor="end" x={chart.plot.left + chart.plotWidth - 12} y={chart.plot.top + 22}>LEADING · 领先</text>
          <text className="tp-rotation-quadrant is-left" x={chart.plot.left + 12} y={chart.plot.top + chart.plotHeight - 12}>LAGGING · 落后</text>
          <text className="tp-rotation-quadrant" textAnchor="end" x={chart.plot.left + chart.plotWidth - 12} y={chart.plot.top + chart.plotHeight - 12}>WEAKENING · 转弱</text>
          {chart.nodes.map((node) => {
            const active = !hoveredSector || hoveredSector === node.sector.sector_name
            const label = chart.labels.get(String(node.sector.sector_code))
            const labelX = node.currentX + (label.side === 'right' ? 9 : -9)
            return (
              <g
                aria-label={`${node.sector.sector_name}, ${node.current.quadrant}`}
                className="tp-rotation-trail"
                key={`${market.market}-${node.sector.sector_code}`}
                onClick={() => openSector(node.sector)}
                onFocus={() => setHoveredSector(node.sector.sector_name)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') openSector(node.sector)
                }}
                onMouseEnter={() => setHoveredSector(node.sector.sector_name)}
                onMouseLeave={() => setHoveredSector('')}
                role="button"
                style={{ '--rotation-color': node.color, opacity: active ? 1 : 0.12 }}
                tabIndex="0"
              >
                <polyline points={node.points.map((point) => `${point.x},${point.y}`).join(' ')} />
                {node.points.map((point, index) => (
                  <circle
                    cx={point.x}
                    cy={point.y}
                    key={`${node.sector.sector_code}-${point.date}`}
                    r={index === node.points.length - 1 ? 5 : 2.2}
                    style={{ opacity: 0.2 + ((index + 1) / node.points.length) * 0.72 }}
                  >
                    <title>{node.sector.sector_name} / {point.date} / RS {point.relative_strength.toFixed(2)} / Mom {point.relative_momentum.toFixed(2)}</title>
                  </circle>
                ))}
                <line className="tp-rotation-label-line" x1={node.currentX} x2={labelX} y1={node.currentY} y2={label.labelY} />
                <text
                  className="tp-rotation-sector-label"
                  textAnchor={label.side === 'right' ? 'start' : 'end'}
                  x={labelX + (label.side === 'right' ? 3 : -3)}
                  y={label.labelY + 4}
                >
                  {rotationSectorLabel(node.sector.sector_name)}
                </text>
              </g>
            )
          })}
          <text className="tp-rotation-axis-label" textAnchor="middle" x={chart.plot.left + chart.plotWidth / 2} y={chart.height - 12}>相对强度指数</text>
          <text className="tp-rotation-axis-label" textAnchor="middle" transform={`rotate(-90 17 ${chart.plot.top + chart.plotHeight / 2})`} x="17" y={chart.plot.top + chart.plotHeight / 2}>相对动量指数</text>
        </svg>
      </div>
      <div className="tp-sector-rotation-legend">
        {ROTATION_QUADRANTS.map(([key, label]) => (
          <span className={`is-${key.toLowerCase()}`} key={key}>{key} · {label}</span>
        ))}
        <em>轨迹由淡到深；点击行业可打开月度分析</em>
      </div>
    </section>
  )
}

function sectorProfile(item) {
  const score = Number.parseFloat(item.score)
  const recommendation = cellText(item.recommendation).toLowerCase()
  if (recommendation.includes('positive') || score >= 6.5) {
    return { color: '#167768', soft: '#e7f3ef' }
  }
  if (recommendation.includes('negative') || score <= 4.5) {
    return { color: '#b33f55', soft: '#f8e7eb' }
  }
  return { color: '#315d9f', soft: '#e9eef8' }
}

function SectorFactorBars({ item }) {
  return (
    <div className="tp-country-factors">
      {SECTOR_FACTORS.map(([key, label]) => (
        <div className="tp-country-factor" key={key}>
          <span>{label}</span>
          <div className="tp-country-factor-track">
            <i style={{ width: countryScoreWidth(item[key]) }} />
          </div>
          <strong>{cellText(item[key])}</strong>
        </div>
      ))}
    </div>
  )
}

function SectorCard({ item, onSelect, selected }) {
  const profile = sectorProfile(item)
  const Icon = sectorIconFor(item.sector_name)
  const analysis = item.monthly_analysis || {}
  return (
    <button
      aria-pressed={selected ? 'true' : 'false'}
      className={selected ? 'tp-country-card tp-sector-card is-selected' : 'tp-country-card tp-sector-card'}
      onClick={() => onSelect(item)}
      style={{ '--country-color': profile.color, '--country-soft': profile.soft }}
      type="button"
    >
      <div className="tp-country-card-head">
        <div className="tp-country-title">
          <span className="tp-sector-icon"><Icon size={18} /></span>
          <div>
            <span>{countryFlag(item.market)} {cellText(item.market)} sector</span>
            <strong>{cellText(item.sector_name)}</strong>
          </div>
        </div>
        <em>{cellText(item.recommendation)}</em>
      </div>
      <div className="tp-country-score-line">
        <strong>{cellText(item.score)}</strong>
        <span>rank #{cellText(item.rank)} / {cellText(item.最新月份)}</span>
      </div>
      <div className="tp-country-score-track" aria-label={`${item.market} ${item.sector_name} sector score`}>
        <i style={{ width: countryScoreWidth(item.score) }} />
      </div>
      <div className="tp-sector-card-meta">
        <span>{cellText(item.sector_weight)} weight</span>
        <span>{cellText(item.constituents)} names</span>
        <span>{cellText(item.forward_return)} fwd</span>
      </div>
      <p className="tp-sector-card-summary">
        {analysis.summary || '月度 Obsidian 分析暂未匹配'}
      </p>
      <SectorFactorBars item={item} />
    </button>
  )
}

function SectorMarketBoard({ market, rows, onSelect, selectedSector }) {
  const marketRows = rows.filter((item) => item.market === market.market)
  return (
    <section className="tp-sector-market">
      <div className="tp-model-section-head">
        <div>
          <p className="tp-kicker">{cellText(market.market)} sector scorecard</p>
          <h3>行业推荐排名</h3>
        </div>
        <span>
          +{cellText(market.positive)} / ={cellText(market.neutral)} / -{cellText(market.negative)}
        </span>
      </div>
      <div className="tp-panel-note">
        {cellText(market.latest_date)} / {cellText(market.sectors)} sectors / {cellText(market.path)}
      </div>
      <div className="tp-sector-card-grid">
        {marketRows.map((item) => (
          <SectorCard
            item={item}
            key={`${item.market}-${item.sector_code}-${item.最新月份}`}
            onSelect={onSelect}
            selected={selectedSector?.market === item.market && selectedSector?.sector_name === item.sector_name}
          />
        ))}
        {!marketRows.length && <div className="tp-empty">暂无 Sector recommendation</div>}
      </div>
    </section>
  )
}

function SectorAnalysisDrawer({ item, monthlyReport, onClose }) {
  useEffect(() => {
    if (!item) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [item, onClose])

  if (!item) return null
  const analysis = item.monthly_analysis || {}
  const evidence = analysis.evidence_block || []
  const profile = sectorProfile(item)
  return (
    <div className="tp-sector-drawer-backdrop" onClick={onClose}>
      <aside
        aria-label={`${item.market} ${item.sector_name} 月度分析`}
        aria-modal="true"
        className="tp-sector-drawer"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        style={{ '--country-color': profile.color, '--country-soft': profile.soft }}
      >
        <div className="tp-sector-drawer-head">
          <div>
            <p className="tp-kicker">Obsidian monthly view</p>
            <h3>{countryFlag(item.market)} {cellText(item.market)} {cellText(item.sector_name)}</h3>
            <span>{cellText(monthlyReport?.month)} / {cellText(analysis.view || item.recommendation)} / rank #{cellText(item.rank)}</span>
          </div>
          <button aria-label="关闭行业分析抽屉" className="tp-icon-only-button" onClick={onClose} type="button">
            <X size={18} />
          </button>
        </div>

        <div className="tp-sector-drawer-score">
          <div>
            <span>综合分</span>
            <strong>{cellText(item.score)}</strong>
          </div>
          <div>
            <span>核心因子</span>
            <strong>Trend {cellText(item.momentum)} / Growth {cellText(item.growth)}</strong>
          </div>
        </div>

        <section className="tp-sector-drawer-section">
          <h4>总结文字</h4>
          <p>{analysis.summary || '该 sector 尚未匹配到本月 Obsidian 分析。'}</p>
        </section>

        <section className="tp-sector-drawer-section">
          <h4>Evidence block</h4>
          {evidence.length ? (
            <ul className="tp-sector-evidence-list">
              {evidence.map((line, index) => (
                <li key={`${item.market}-${item.sector_name}-evidence-${index}`}>{line}</li>
              ))}
            </ul>
          ) : (
            <div className="tp-empty">暂无 evidence block</div>
          )}
        </section>

        <div className="tp-panel-note">
          {analysis.report_path || monthlyReport?.path || 'N/A'}
        </div>
      </aside>
    </div>
  )
}

function CompanyDetailDrawer({ company, loading, error, onClose }) {
  useEffect(() => {
    if (!company && !loading && !error) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [company, loading, error, onClose])

  if (!company && !loading && !error) return null
  const identity = company?.identity || {}
  const description = company?.description || {}
  const news = company?.news || []
  const title = identity.name || company?.isin || 'Company detail'
  return (
    <div className="tp-sector-drawer-backdrop tp-company-drawer-backdrop" onClick={onClose}>
      <aside
        aria-label={`${title} 公司详情`}
        aria-modal="true"
        className="tp-sector-drawer tp-company-drawer"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        style={{ '--country-color': 'var(--green)', '--country-soft': 'var(--green-soft)' }}
      >
        <div className="tp-sector-drawer-head">
          <div>
            <p className="tp-kicker">Company detail</p>
            <h3>{title}</h3>
            <span>{company?.isin || 'N/A'} / {identity.country || 'N/A'} / {identity.sector || 'N/A'}</span>
          </div>
          <button aria-label="关闭公司详情抽屉" className="tp-icon-only-button" onClick={onClose} type="button">
            <X size={18} />
          </button>
        </div>

        {loading && <div className="tp-empty">正在读取公司简介和最近新闻...</div>}
        {error && <div className="tp-empty">{error}</div>}

        {!loading && !error && (
          <>
            <section className="tp-sector-drawer-section tp-company-detail-section">
              <h4>公司简介</h4>
              <div className="tp-company-meta-row">
                <span>{description.date || 'N/A'}</span>
                <strong>{description.title || 'Description'}</strong>
              </div>
              <div className="tp-company-markdown">
                {description.body || '暂无公司简介。'}
              </div>
            </section>

            <section className="tp-sector-drawer-section tp-company-detail-section">
              <h4>最近新闻</h4>
              {news.length ? (
                <div className="tp-company-news-list">
                  {news.map((item, index) => (
                    <article className="tp-company-news-item" key={`${company?.isin || 'company'}-${index}`}>
                      <span>{item.date || 'N/A'}</span>
                      <strong>{item.title || 'Actualité'}</strong>
                      <p>{item.body || '暂无新闻正文。'}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="tp-empty">最近 3 个月暂无新闻。</div>
              )}
            </section>
          </>
        )}
      </aside>
    </div>
  )
}

function DataTable({ columns, rows, limit = 8, renderCell }) {
  const shouldPaginate = rows.length > 20
  const pageSize = shouldPaginate ? 20 : limit
  const [page, setPage] = useState(0)
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const start = safePage * pageSize
  const visibleRows = rows.slice(start, start + pageSize)
  useEffect(() => {
    setPage(0)
  }, [rows.length, pageSize])
  if (!visibleRows.length) {
    return <div className="tp-empty">暂无数据</div>
  }
  return (
    <>
      <div className="tp-table-wrap">
        <table className="tp-data-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, rowIndex) => (
              <tr key={`${start + rowIndex}-${columns.map((column) => row[column]).join('-')}`}>
                {columns.map((column) => (
                  <td key={column} title={cellText(row[column])}>
                    {renderCell
                      ? renderCell(column, row, start + rowIndex)
                      : column.includes('状态')
                        ? <StatusPill value={row[column]} />
                        : cellText(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shouldPaginate && (
        <div className="tp-table-pager">
          <span>{start + 1}-{Math.min(start + pageSize, rows.length)} / {rows.length}</span>
          <div>
            <button disabled={safePage === 0} onClick={() => setPage((value) => Math.max(0, value - 1))} type="button">
              上一页
            </button>
            <strong>{safePage + 1} / {pageCount}</strong>
            <button disabled={safePage >= pageCount - 1} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))} type="button">
              下一页
            </button>
          </div>
        </div>
      )}
    </>
  )
}

function MarketBriefPanel({ latestMarketBrief, moduleDragProps, panelClass, refreshingState }) {
  return (
          <div className={panelClass('market', 'brief', 'tp-market-panel')} {...moduleDragProps('market', 'brief')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Latest market brief</p>
                <h2>市场概况</h2>
              </div>
              {refreshingState && <Loader2 className="tp-spin" size={20} />}
            </div>
            <section className="tp-market-brief">
              <div className="tp-market-brief-head">
                <div>
                  <p className="tp-kicker">News Room / OKF</p>
                  <h3>{latestMarketBrief.title || '最新市场讯息'}</h3>
                </div>
                <span>{latestMarketBrief.created || latestMarketBrief.updated_at || 'N/A'}</span>
              </div>
              {latestMarketBrief.status === 'ok' ? (
                <>
                  <div className="tp-market-brief-meta">
                    <span>{latestMarketBrief.source_scope || 'source: N/A'}</span>
                    <span>OKF {latestMarketBrief.okf_refresh || 'N/A'}</span>
                    <span>{latestMarketBrief.section_count || '0'} sections</span>
                  </div>
                  <div className="tp-market-brief-sections">
                    {(latestMarketBrief.sections || []).map((section) => (
                      <article className="tp-market-brief-section" key={section.heading}>
                        <h4>{section.heading}</h4>
                        <p>{section.body}</p>
                      </article>
                    ))}
                  </div>
                  <div className="tp-market-brief-path">
                    {latestMarketBrief.path || 'N/A'}
                    {latestMarketBrief.okf_path ? ` / OKF: ${latestMarketBrief.okf_path}` : ''}
                  </div>
                </>
              ) : (
                <div className="tp-empty">暂无市场复盘 clipping</div>
              )}
            </section>
          </div>
  )
}

function RunControlPanel({ isBusy, job, launchJob, moduleDragProps, panelClass, pipelinePayload, projectPayload, setPipelinePayload, setProjectPayload, submitting }) {
  return (
            <div className={panelClass('production', 'run-control', 'tp-run-panel')} {...moduleDragProps('production', 'run-control')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Run control</p>
                <h2>启动任务</h2>
              </div>
              {isBusy && <Loader2 className="tp-spin" size={20} />}
            </div>

            <div className="tp-action-grid">
              <ActionButton
                active={submitting === 'checks' || (job.step === 'system_checks' && ['queued', 'running'].includes(job.status))}
                busy={submitting === 'checks'}
                description="安全 smoke / inspect"
                disabled={isBusy}
                icon={ShieldCheck}
                label="全部项目检查"
                onClick={() => launchJob('checks')}
              />
              <ActionButton
                active={submitting === 'project' || (job.step?.startsWith('project:') && ['queued', 'running'].includes(job.status))}
                busy={submitting === 'project'}
                description={`${projectPayload.project_id} / ${projectPayload.mode}`}
                disabled={isBusy}
                icon={Database}
                label="启动子项目"
                onClick={() => launchJob('project')}
              />
              <ActionButton
                active={submitting === 'pipeline' || (!job.step?.startsWith('project:') && !job.step?.startsWith('signal:') && job.step !== 'system_checks' && ['queued', 'running'].includes(job.status))}
                busy={submitting === 'pipeline'}
                description={`${pipelinePayload.step} / ${pipelinePayload.update_mode}`}
                disabled={isBusy}
                icon={Play}
                label="启动 Pipeline"
                onClick={() => launchJob('pipeline')}
              />
            </div>

            <div className="tp-form-grid">
              <label>
                <span>Pipeline step</span>
                <select
                  value={pipelinePayload.step}
                  onChange={(event) => setPipelinePayload({ ...pipelinePayload, step: event.target.value })}
                >
                  <option value="run_all">run_all</option>
                  <option value="refresh_data">refresh_data</option>
                  <option value="refresh_ml">refresh_ml</option>
                  <option value="export_signals">export_signals</option>
                  <option value="build_candidates">build_candidates</option>
                  <option value="optimize_portfolio">optimize_portfolio</option>
                  <option value="run_backtest">run_backtest</option>
                  <option value="generate_report">generate_report</option>
                </select>
              </label>
              <label>
                <span>Update mode</span>
                <select
                  value={pipelinePayload.update_mode}
                  onChange={(event) =>
                    setPipelinePayload({ ...pipelinePayload, update_mode: event.target.value })
                  }
                >
                  <option value="both">both</option>
                  <option value="screen_only">screen_only</option>
                  <option value="returns_only">returns_only</option>
                </select>
              </label>
              <label>
                <span>Project</span>
                <input
                  value={projectPayload.project_id}
                  onChange={(event) => setProjectPayload({ ...projectPayload, project_id: event.target.value })}
                />
              </label>
              <label>
                <span>Project mode</span>
                <select
                  value={projectPayload.mode}
                  onChange={(event) => setProjectPayload({ ...projectPayload, mode: event.target.value })}
                >
                  <option value="safe_check">safe_check</option>
                  <option value="registered_command">registered_command</option>
                </select>
              </label>
            </div>
          </div>
  )
}

function LiveJobPanel({ activePhase, job, moduleDragProps, panelClass, progressPercent }) {
  return (
          <div className={panelClass('production', 'live-job')} {...moduleDragProps('production', 'live-job')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Live job</p>
                <h2>{job.status_label || 'IDLE'}</h2>
              </div>
              {job.status === 'completed' ? <CheckCircle2 size={22} /> : <Activity size={22} />}
            </div>

            <div className={`tp-job-badge tp-job-${job.status}`}>{job.step || 'N/A'}</div>
            <div className="tp-job-progress" aria-label="任务进度">
              <span style={{ width: `${progressPercent}%` }} />
            </div>
            <div className="tp-phase-row">
              {PHASES.map(([, label], index) => (
                <span className={index <= activePhase ? 'tp-phase tp-phase-active' : 'tp-phase'} key={label}>
                  {label}
                </span>
              ))}
            </div>

            <dl className="tp-details">
              <div>
                <dt>job_id</dt>
                <dd>{job.job_id || 'N/A'}</dd>
              </div>
              <div>
                <dt>PID</dt>
                <dd>{job.pid || 'N/A'}</dd>
              </div>
              <div>
                <dt>backend</dt>
                <dd>{job.backend || 'N/A'}{job.queue_name ? ` / ${job.queue_name}` : ''}</dd>
              </div>
              <div>
                <dt>updated</dt>
                <dd>{job.status_updated_at || job.queued_at || 'N/A'}</dd>
              </div>
              <div>
                <dt>manifest</dt>
                <dd>{job.manifest_status || 'N/A'} / {job.manifest || 'N/A'}</dd>
              </div>
              <div>
                <dt>result</dt>
                <dd>{job.error || (job.returncode ? `returncode ${job.returncode}` : job.finished_at || 'N/A')}</dd>
              </div>
            </dl>

            <pre className="tp-log">{job.log_tail || '暂无日志摘要'}</pre>
          </div>
  )
}

function OverviewPanel({ dashboardState, metrics, moduleDragProps, panelClass, refreshingState }) {
  return (
          <div className={panelClass('production', 'overview')} {...moduleDragProps('production', 'overview')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">State API</p>
                <h2>系统概览</h2>
              </div>
              {refreshingState && <Loader2 className="tp-spin" size={20} />}
            </div>
            <section className="tp-status-strip">
              {metrics.map(([label, value, note]) => (
                <div className="tp-metric" key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                  <small>{note}</small>
                </div>
              ))}
            </section>
            <div className="tp-signal-list">
              {dashboardState.overview.map((item) => (
                <div className="tp-signal-row" key={item.label}>
                  <span>{item.label}</span>
                  <strong>{cellText(item.value)}</strong>
                  <small>{cellText(item.note)}</small>
                </div>
              ))}
            </div>
          </div>
  )
}

function AlertsPanel({ dashboardState, moduleDragProps, panelClass }) {
  return (
          <div className={panelClass('production', 'alerts')} {...moduleDragProps('production', 'alerts')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Alerts</p>
                <h2>告警</h2>
              </div>
            </div>
            <div className="tp-alert-list">
              {dashboardState.alerts.slice(0, 6).map((alert, index) => (
                <div className="tp-alert-row" key={`${alert.模块}-${alert.对象}-${index}`}>
                  <StatusPill value={alert.级别 || alert.状态} />
                  <div>
                    <strong>{cellText(alert.模块)} / {cellText(alert.对象)}</strong>
                    <small>{cellText(alert.证据)}</small>
                  </div>
                </div>
              ))}
              {!dashboardState.alerts.length && <div className="tp-empty">暂无告警</div>}
            </div>
          </div>
  )
}

function RegimePanel({ directionModelRows, drawdownModelRows, isBusy, job, launchJob, moduleDragProps, panelClass, regimeHistoryRows, regimeModels, regimeRows, regimeSignal, riskModelRows, stateModelRows, submitting, volatilityModelRows }) {
  return (
          <div className={panelClass('results', 'regime', 'tp-wide-panel')} {...moduleDragProps('results', 'regime')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Signals / Regime</p>
                <h2 className="tp-heading-icon"><Gauge size={18} />Regime detector</h2>
              </div>
              <button
                aria-busy={submitting === 'regime' ? 'true' : 'false'}
                className="tp-icon-button"
                disabled={isBusy}
                onClick={() => launchJob('regime')}
                type="button"
              >
                <RefreshCw className={submitting === 'regime' ? 'tp-spin' : ''} size={18} />
                <span>刷新 Regime</span>
              </button>
            </div>
            <div className="tp-panel-note">
              最新月份 {regimeSignal.latest_date || 'N/A'} / {regimeSignal.status || 'N/A'} / {regimeSignal.signal_path || 'N/A'}
            </div>
            <div className="tp-regime-cards">
              {(regimeSignal.rows || []).map((item) => (
                <RegimeGauge item={item} key={`${item.region}-${item.最新月份}`} />
              ))}
              {!(regimeSignal.rows || []).length && <div className="tp-empty">暂无 Regime 信号</div>}
            </div>
            <div className="tp-model-section">
              <div className="tp-model-section-head">
                <div>
                  <p className="tp-kicker">Model family</p>
                  <h3>状态模型与风险配置</h3>
                </div>
                <span>{regimeModels.updated_at || 'N/A'}</span>
              </div>
              <StateModelMatrix rows={stateModelRows} />
              <RiskModelMeters rows={riskModelRows} />
            </div>
            <div className="tp-rank-grid">
              <ModelRankList icon={TrendingUp} rows={directionModelRows} title="方向预测" />
              <ModelRankList icon={BarChart3} rows={volatilityModelRows} title="波动预测" />
              <ModelRankList icon={Activity} rows={drawdownModelRows} title="回撤预测" />
            </div>
            <DataTable columns={['region', '最新月份', 'regime', '风险预算', '状态', 'model']} rows={regimeRows} />
            <div className="tp-panel-note">最近历史</div>
            <DataTable columns={['region', '月份', 'regime', '风险预算', '状态']} limit={6} rows={regimeHistoryRows} />
          </div>
  )
}

function CountryPanel({ countryHistoryRows, countryRows, countrySignal, countryVisualRows, isBusy, launchJob, moduleDragProps, panelClass, singleCountryRows, singleCountrySignalRows, submitting }) {
  return (
          <div className={panelClass('results', 'country', 'tp-wide-panel')} {...moduleDragProps('results', 'country')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Signals / Country</p>
                <h2 className="tp-heading-icon"><BarChart3 size={18} />Country model</h2>
              </div>
              <button
                aria-busy={submitting === 'country' ? 'true' : 'false'}
                className="tp-icon-button"
                disabled={isBusy}
                onClick={() => launchJob('country')}
                type="button"
              >
                <RefreshCw className={submitting === 'country' ? 'tp-spin' : ''} size={18} />
                <span>刷新 Country</span>
              </button>
            </div>
            <div className="tp-country-status-row">
              <div>
                <span>最新月份</span>
                <strong>{countrySignal.latest_date || 'N/A'}</strong>
              </div>
              <div>
                <span>状态</span>
                <strong>{countrySignal.status || 'N/A'}</strong>
              </div>
              <div>
                <span>Signal file</span>
                <strong>{countrySignal.signal_path || 'N/A'}</strong>
              </div>
              <div>
                <span>Single-country file</span>
                <strong>{countrySignal.single_country_path || 'N/A'}</strong>
              </div>
            </div>
            <div className="tp-country-dashboard">
              <section className="tp-country-column">
                <div className="tp-model-section-head">
                  <div>
                    <p className="tp-kicker">Regional allocation signal</p>
                    <h3>区域评分与因子构成</h3>
                  </div>
                  <span>{countryVisualRows.length} regions</span>
                </div>
                <div className="tp-country-card-grid">
                  {countryVisualRows.map((item) => (
                    <CountryRegionCard item={item} key={`${item.region}-${item.最新月份}`} />
                  ))}
                  {!countryVisualRows.length && <div className="tp-empty">暂无 Country 信号</div>}
                </div>
              </section>
              <section className="tp-country-column">
                <div className="tp-model-section-head">
                  <div>
                    <p className="tp-kicker">Single-country score</p>
                    <h3>单个国家排名</h3>
                  </div>
                  <span>{singleCountrySignalRows.length} countries</span>
                </div>
                <SingleCountryBoard rows={singleCountrySignalRows} />
              </section>
            </div>
            <div className="tp-country-table-split">
              <div>
                <div className="tp-panel-note">区域明细 / {countrySignal.signal_path || 'N/A'}</div>
                <DataTable
                  columns={['region', '最新月份', 'score', 'rank', 'recommendation', 'Δ rank', 'margin', 'profitability', 'growth', 'value', 'momentum']}
                  rows={countryRows}
                />
              </div>
              <div>
                <div className="tp-panel-note">单国明细 / {countrySignal.single_country_path || 'N/A'}</div>
                <DataTable
                  columns={['国家', '指数', '最新月份', 'score', 'rank', 'margin', 'profitability', 'growth', 'value', 'momentum']}
                  rows={singleCountryRows}
                />
              </div>
            </div>
            <div className="tp-panel-note">最近历史</div>
            <DataTable columns={['region', '月份', 'score', 'rank', 'recommendation']} limit={10} rows={countryHistoryRows} />
          </div>
  )
}

function SectorPanel({ moduleDragProps, panelClass, sectorMarkets, sectorRows, sectorSignal, sectorVisualRows, selectedSectorRow, setSelectedSector }) {
  return (
          <div className={panelClass('results', 'sector', 'tp-wide-panel')} {...moduleDragProps('results', 'sector')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Signals / Sector</p>
                <h2 className="tp-heading-icon"><BarChart3 size={18} />Sector recommendation</h2>
              </div>
            </div>
            <div className="tp-country-status-row">
              <div>
                <span>最新月份</span>
                <strong>{sectorSignal.latest_date || 'N/A'}</strong>
              </div>
              <div>
                <span>状态</span>
                <strong>{sectorSignal.status || 'N/A'}</strong>
              </div>
              <div>
                <span>Markets</span>
                <strong>{sectorMarkets.length || 'N/A'}</strong>
              </div>
              <div>
                <span>Updated</span>
                <strong>{sectorSignal.updated_at || 'N/A'}</strong>
              </div>
              <div>
                <span>Monthly note</span>
                <strong>{sectorSignal.monthly_report?.sectors || '0'} sectors</strong>
              </div>
            </div>
            <div className="tp-panel-note">
              月报 / {sectorSignal.monthly_report?.path || 'N/A'}
            </div>
            <SectorRotationMap
              onSelect={setSelectedSector}
              rotation={sectorSignal.rotation}
              rows={sectorVisualRows}
            />
            <div className="tp-sector-dashboard">
              {sectorMarkets.map((market) => (
                <SectorMarketBoard
                  market={market}
                  rows={sectorVisualRows}
                  key={market.market}
                  onSelect={setSelectedSector}
                  selectedSector={selectedSectorRow}
                />
              ))}
              {!sectorMarkets.length && <div className="tp-empty">{sectorSignal.message || '暂无 Sector recommendation'}</div>}
            </div>
            <SectorAnalysisDrawer
              item={selectedSectorRow}
              monthlyReport={sectorSignal.monthly_report}
              onClose={() => setSelectedSector(null)}
            />
            <div className="tp-panel-note">明细 / {Object.values(sectorSignal.paths || {}).join(' / ') || 'N/A'}</div>
            <DataTable
              columns={['market', 'sector', '最新月份', 'rank', 'recommendation', 'score', 'leverage', 'margin', 'valuation', 'momentum', 'growth', 'lowvol', 'weight', 'names']}
              limit={40}
              rows={sectorRows}
            />
          </div>
  )
}

function TechnicalPanel({ companyDetail, companyDetailError, companyDetailLoading, moduleDragProps, panelClass, renderTechnicalCell, setCompanyDetail, setCompanyDetailError, setCompanyDetailLoading, technicalMetricRows, technicalSecurityRows, technicalSignal }) {
  return (
          <div className={panelClass('technical', 'latest', 'tp-wide-panel')} {...moduleDragProps('technical', 'latest')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Signals / Technical</p>
                <h2 className="tp-heading-icon"><Activity size={18} />Latest Technical metrics</h2>
              </div>
            </div>
            <div className="tp-country-status-row">
              <div>
                <span>Signal date</span>
                <strong>{technicalSignal.latest_date || 'N/A'}</strong>
              </div>
              <div>
                <span>Pattern date</span>
                <strong>{technicalSignal.pattern_date || 'N/A'}</strong>
              </div>
              <div>
                <span>Available date</span>
                <strong>{technicalSignal.available_date || 'N/A'}</strong>
              </div>
              <div>
                <span>Screen date</span>
                <strong>{technicalSignal.screen_date || 'N/A'}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{technicalSignal.status || 'N/A'}</strong>
              </div>
              <div>
                <span>Rows</span>
                <strong>{technicalMetricRows.length || 'N/A'} metrics</strong>
              </div>
            </div>
            <div className="tp-panel-note">
              {technicalSignal.message || 'N/A'} / {technicalSignal.signal_path || 'N/A'} / {technicalSignal.screen_path || 'N/A'}
            </div>
            {technicalSignal.availability_note && (
              <div className="tp-panel-note tp-technical-warning">{technicalSignal.availability_note}</div>
            )}
            <div className="tp-technical-market-grid">
              {(technicalSignal.markets || []).map((item) => (
                <article className="tp-technical-market-card" key={item.market}>
                  <div className="tp-technical-market-head">
                    <div>
                      <p className="tp-kicker">Market</p>
                      <h3>{item.market}</h3>
                    </div>
                    <strong>{item.coverage || 'N/A'}</strong>
                  </div>
                  <div className="tp-technical-market-meta">
                    <span>{item.universe || '0'} names</span>
                    <span>{item.covered || '0'} covered</span>
                    <span>{item.signal_date || 'N/A'}</span>
                  </div>
                  <div className="tp-technical-pill-row">
                    <span className="tp-technical-tag is-positive">保留 {item.positive || 'N/A'}</span>
                    <span className="tp-technical-tag is-reverse">反向 {item.reverse || 'N/A'}</span>
                    <span className="tp-technical-tag is-filter">辅助 {item.auxiliary || 'N/A'}</span>
                  </div>
                </article>
              ))}
              {!(technicalSignal.markets || []).length && <div className="tp-empty">{technicalSignal.message || '暂无 Technical metrics'}</div>}
            </div>
            <div className="tp-technical-section">
              <div className="tp-model-section-head">
                <div>
                  <p className="tp-kicker">Metric evidence map</p>
                  <h3>按市场的保留、反向与弱证据</h3>
                </div>
                <span>{technicalSignal.updated_at || 'N/A'}</span>
              </div>
              <DataTable
                columns={['市场', 'metric', '处理', '证据', '推荐端', '覆盖', '覆盖率', '均值', '中位数', '最小', '最大', '并列率', '事件率', '说明']}
                limit={40}
                renderCell={renderTechnicalCell}
                rows={technicalMetricRows}
              />
            </div>
            <div className="tp-technical-section">
              <div className="tp-model-section-head">
                <div>
                  <p className="tp-kicker">Current names</p>
                  <h3>最新一期推荐端样本</h3>
                </div>
                <span>{technicalSecurityRows.length || 0} rows</span>
              </div>
              <DataTable
                columns={['市场', 'metric', '处理', '推荐端', 'Name', 'score', 'Weight', 'Country', 'Region', 'Sector', 'ISIN']}
                limit={120}
                renderCell={renderTechnicalCell}
                rows={technicalSecurityRows}
              />
            </div>
            <CompanyDetailDrawer
              company={companyDetail}
              error={companyDetailError}
              loading={companyDetailLoading}
              onClose={() => {
                setCompanyDetail(null)
                setCompanyDetailError('')
                setCompanyDetailLoading(false)
              }}
            />
          </div>
  )
}

function ScoreMlPanel({ companyDetail, companyDetailError, companyDetailLoading, moduleDragProps, panelClass, refreshScoreMlComponents, renderScoreMlCell, scoreMlComponents, scoreMlLoading, scoreMlRows, scoreMlSelection, setCompanyDetail, setCompanyDetailError, setCompanyDetailLoading }) {
  return (
          <div className={panelClass('results', 'score-ml', 'tp-wide-panel')} {...moduleDragProps('results', 'score-ml')}>
            <div className="tp-panel-heading tp-score-ml-heading">
              <div>
                <p className="tp-kicker">Score ML</p>
                <h2 className="tp-heading-icon"><BarChart3 size={18} />Portfolio components</h2>
              </div>
              {scoreMlLoading && <Loader2 className="tp-spin" size={20} />}
            </div>
            <div className="tp-score-ml-controls">
              <label>
                <span>Date</span>
                <select
                  value={scoreMlSelection.date || scoreMlComponents.selected_date || ''}
                  onChange={(event) => refreshScoreMlComponents({ ...scoreMlSelection, date: event.target.value })}
                >
                  {(scoreMlComponents.date_options || []).map((date) => (
                    <option value={date} key={date}>{date}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Portfolio</span>
                <select
                  value={scoreMlSelection.side || scoreMlComponents.selected_side || 'top'}
                  onChange={(event) => refreshScoreMlComponents({ ...scoreMlSelection, side: event.target.value })}
                >
                  <option value="top">Top</option>
                  <option value="worst">Worst</option>
                </select>
              </label>
              <div>
                <span>Screen date</span>
                <strong>{scoreMlComponents.screen_date || 'N/A'}</strong>
              </div>
              <div>
                <span>Components</span>
                <strong>{scoreMlRows.length || 'N/A'}</strong>
              </div>
            </div>
            <div className="tp-panel-note">
              {scoreMlComponents.message || 'N/A'} / {scoreMlComponents.run_dir || 'N/A'}
            </div>
            <DataTable
              columns={['Name', 'Weight', 'Score ML', 'Score ML_IF', 'Value', 'Quality', 'Momentum', 'Growth', 'LowVol', 'Div', 'Size', 'PE LTM', 'PE FY1', 'EPS Growth FY1', 'ROE', 'Dividend Yield', 'Earnings Yield', 'Country', 'Region', 'Sector', 'ISIN']}
              limit={320}
              renderCell={renderScoreMlCell}
              rows={scoreMlRows}
            />
            <CompanyDetailDrawer
              company={companyDetail}
              error={companyDetailError}
              loading={companyDetailLoading}
              onClose={() => {
                setCompanyDetail(null)
                setCompanyDetailError('')
                setCompanyDetailLoading(false)
              }}
            />
          </div>
  )
}

function ProductionTables({ dashboardState, moduleDragProps, panelClass, queueRows }) {
  return (
<>
          <div className={panelClass('production', 'queue', 'tp-wide-panel')} {...moduleDragProps('production', 'queue')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Queue stream</p>
                <h2>后台队列任务</h2>
              </div>
            </div>
            <DataTable columns={['job_id', '状态', 'step', '更新时间', 'backend']} rows={queueRows} />
          </div>

          <div className={panelClass('production', 'core-database', 'tp-wide-panel')} {...moduleDragProps('production', 'core-database')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Core database</p>
                <h2>核心数据库</h2>
              </div>
            </div>
            <DataTable columns={['数据资产', '更新状态', '最新日期', '行', 'Schema']} rows={dashboardState.core_database} />
          </div>

          <div className={panelClass('production', 'project-assets', 'tp-wide-panel')} {...moduleDragProps('production', 'project-assets')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Project assets</p>
                <h2>项目资产</h2>
              </div>
            </div>
            <DataTable
              columns={['项目', '资产状态', '注册资产', '自动发现', '必需缺失', '总大小', '最新更新时间']}
              rows={dashboardState.projects}
            />
          </div>

          <div className={panelClass('production', 'pipeline-status', 'tp-wide-panel')} {...moduleDragProps('production', 'pipeline-status')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Pipeline</p>
                <h2>Pipeline 状态</h2>
              </div>
            </div>
            <DataTable columns={['步骤', '状态', '最近完成', '未通过校验']} rows={dashboardState.pipeline} />
          </div>

          <div className={panelClass('production', 'data-assets', 'tp-wide-panel')} {...moduleDragProps('production', 'data-assets')}>
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Data assets</p>
                <h2>数据资产</h2>
              </div>
            </div>
            <DataTable
              columns={['项目', '数据/产物', '来源', '状态', '行', '大小', '更新时间']}
              limit={12}
              rows={dashboardState.assets}
            />
          </div>
</>
  )
}

function FactorExplorerPanel({ panelClass }) {
  return (
          <div className={panelClass('results', 'factor-explorer', 'tp-factor-explorer-panel')}>
            <iframe
              className="tp-factor-explorer-frame"
              src="/reports/factor-explorer.html"
              title="四市场因子收益、ratio 与经济含义研究"
            />
          </div>
  )
}

function normalizeDashboardState(nextState = {}) {
  return {
    ...EMPTY_DASHBOARD_STATE,
    ...nextState,
    queue: {
      ...EMPTY_DASHBOARD_STATE.queue,
      ...(nextState.queue || {}),
      counts: {
        ...EMPTY_DASHBOARD_STATE.queue.counts,
        ...(nextState.queue?.counts || {}),
      },
    },
    signals: {
      ...EMPTY_DASHBOARD_STATE.signals,
      ...(nextState.signals || {}),
    },
  }
}

function useDashboardData(setToast) {
  const [dashboardState, setDashboardState] = useState(EMPTY_DASHBOARD_STATE)
  const [refreshingState, setRefreshingState] = useState(false)
  const [scoreMlComponents, setScoreMlComponents] = useState(EMPTY_DASHBOARD_STATE.signals.score_ml_components)
  const [scoreMlSelection, setScoreMlSelection] = useState({ date: '', side: 'top' })
  const [scoreMlLoading, setScoreMlLoading] = useState(false)
  const [selectedSector, setSelectedSector] = useState(null)
  const [companyDetail, setCompanyDetail] = useState(null)
  const [companyDetailLoading, setCompanyDetailLoading] = useState(false)
  const [companyDetailError, setCompanyDetailError] = useState('')

  const refreshDashboardState = async ({ quiet = false } = {}) => {
    setRefreshingState(true)
    if (!quiet) {
      setToast({ tone: 'info', title: '正在刷新状态', detail: '正在读取项目、资产、核心库和 pipeline 快照。' })
    }
    try {
      const signalEndpoints = {
        regime: '/api/dashboard/signals/regime',
        country: '/api/dashboard/signals/country',
        small_cap: '/api/dashboard/signals/small-cap',
        sector: '/api/dashboard/signals/sector',
        technical: '/api/dashboard/signals/technical',
        score_ml_components: '/api/dashboard/score-ml-components',
      }
      const [coreState, backtest, ...signalResults] = await Promise.all([
        requestJson('/api/dashboard/state'),
        requestJson('/api/dashboard/backtest'),
        ...Object.values(signalEndpoints).map((endpoint) => requestJson(endpoint)),
      ])
      const signals = { ...(coreState.signals || {}) }
      Object.keys(signalEndpoints).forEach((key, index) => {
        signals[key] = signalResults[index]
      })
      const nextState = { ...coreState, backtest, signals }
      setDashboardState(normalizeDashboardState(nextState))
      const nextComponents = nextState.signals?.score_ml_components || EMPTY_DASHBOARD_STATE.signals.score_ml_components
      setScoreMlComponents(nextComponents)
      setScoreMlSelection({
        date: nextComponents.selected_date || nextComponents.default_date || '',
        side: nextComponents.selected_side || nextComponents.default_side || 'top',
      })
      if (!quiet) {
        setToast({
          tone: 'good',
          title: '状态已刷新',
          detail: `${nextState.projects?.length || 0} projects / ${nextState.assets?.length || 0} assets`,
        })
      }
    } catch (error) {
      setToast({ tone: 'bad', title: '状态刷新失败', detail: error.message })
    } finally {
      setRefreshingState(false)
    }
  }

  const refreshScoreMlComponents = async (nextSelection) => {
    const selection = {
      date: nextSelection.date || scoreMlSelection.date || '',
      side: nextSelection.side || scoreMlSelection.side || 'top',
    }
    setScoreMlSelection(selection)
    setScoreMlLoading(true)
    try {
      const payload = await requestJson(
        `/api/dashboard/score-ml-components?side=${encodeURIComponent(selection.side)}&date=${encodeURIComponent(selection.date)}`,
      )
      setScoreMlComponents(payload)
      setScoreMlSelection({
        date: payload.selected_date || selection.date,
        side: payload.selected_side || selection.side,
      })
    } catch (error) {
      setToast({ tone: 'bad', title: 'Score ML 成分读取失败', detail: error.message })
    } finally {
      setScoreMlLoading(false)
    }
  }

  const openCompanyDetail = async (row) => {
    const isin = row?.ISIN
    if (!isin) return
    setCompanyDetail({
      status: 'loading',
      isin,
      identity: { name: row.Name, country: row.Country, sector: row.Sector },
      description: {},
      news: [],
      message: '',
    })
    setCompanyDetailError('')
    setCompanyDetailLoading(true)
    try {
      const detail = await requestJson(`/api/dashboard/company-detail/${encodeURIComponent(isin)}`)
      setCompanyDetail(detail)
      if (detail.status !== 'ok') setCompanyDetailError(detail.message || '未找到公司详情')
    } catch (error) {
      setCompanyDetailError(error.message)
    } finally {
      setCompanyDetailLoading(false)
    }
  }

  useEffect(() => {
    refreshDashboardState({ quiet: true })
  }, [])

  return {
    companyDetail,
    companyDetailError,
    companyDetailLoading,
    dashboardState,
    openCompanyDetail,
    refreshingState,
    refreshDashboardState,
    refreshScoreMlComponents,
    scoreMlComponents,
    scoreMlLoading,
    scoreMlSelection,
    selectedSector,
    setCompanyDetail,
    setCompanyDetailError,
    setCompanyDetailLoading,
    setDashboardState,
    setSelectedSector,
  }
}

function useQueueStream(setDashboardState, setToast) {
  const sourceRef = useRef(null)
  const pollingRef = useRef(null)

  const stopPolling = () => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }
  const closeSource = () => {
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
    }
  }
  const mergeQueueState = (queue) => {
    setDashboardState((current) => normalizeDashboardState({
      ...current,
      queue: {
        ...current.queue,
        ...queue,
        counts: { ...current.queue?.counts, ...(queue?.counts || {}) },
      },
    }))
  }
  const startPolling = () => {
    stopPolling()
    const pollQueue = async () => {
      try {
        mergeQueueState(await requestJson('/api/dashboard/jobs/queue'))
      } catch (error) {
        setToast({ tone: 'bad', title: '队列状态读取失败', detail: error.message })
      }
    }
    pollQueue()
    pollingRef.current = window.setInterval(pollQueue, 5000)
  }
  const subscribe = () => {
    closeSource()
    stopPolling()
    if (typeof EventSource === 'undefined') {
      startPolling()
      return
    }
    const source = new EventSource(`${API_BASE}/api/dashboard/jobs/queue/events`)
    sourceRef.current = source
    source.addEventListener('queue', (event) => mergeQueueState(JSON.parse(event.data)))
    source.onerror = () => {
      closeSource()
      startPolling()
    }
  }

  useEffect(() => {
    subscribe()
    return () => {
      closeSource()
      stopPolling()
    }
  }, [])
}

function useJobStream(refreshDashboardState, setToast) {
  const [job, setJob] = useState(EMPTY_JOB)
  const [connection, setConnection] = useState('api')
  const sourceRef = useRef(null)
  const pollingRef = useRef(null)
  const pollingInFlightRef = useRef(false)

  const stopPolling = () => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    pollingInFlightRef.current = false
  }
  const closeSource = () => {
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
    }
  }
  const startPolling = (jobId) => {
    stopPolling()
    if (!jobId) {
      setConnection('api')
      return
    }
    setConnection('polling')
    const pollOnce = async () => {
      if (pollingInFlightRef.current) return
      pollingInFlightRef.current = true
      try {
        const nextJob = await requestJson(`/api/dashboard/jobs/${encodeURIComponent(jobId)}`)
        setJob(nextJob)
        if (['completed', 'failed'].includes(nextJob.status)) {
          stopPolling()
          setConnection('api')
          refreshDashboardState({ quiet: true })
        }
      } catch (error) {
        setToast({ tone: 'bad', title: '任务状态轮询失败', detail: error.message })
      } finally {
        pollingInFlightRef.current = false
      }
    }
    pollOnce()
    pollingRef.current = window.setInterval(pollOnce, 3000)
  }
  const subscribeToJob = (jobId) => {
    closeSource()
    stopPolling()
    if (!jobId || typeof EventSource === 'undefined') {
      startPolling(jobId)
      return
    }
    const source = new EventSource(`${API_BASE}/api/dashboard/jobs/${encodeURIComponent(jobId)}/events`)
    sourceRef.current = source
    setConnection('sse')
    source.addEventListener('job', (event) => {
      const nextJob = JSON.parse(event.data)
      setJob(nextJob)
      if (['completed', 'failed'].includes(nextJob.status)) {
        closeSource()
        setConnection('api')
        refreshDashboardState({ quiet: true })
      }
    })
    source.onerror = () => {
      closeSource()
      setToast({ tone: 'warn', title: '实时连接已切换', detail: 'SSE 暂不可用，正在用 API 轮询保持状态更新。' })
      startPolling(jobId)
    }
  }
  const refreshLatestJob = async () => {
    const latest = await requestJson('/api/dashboard/jobs/latest')
    setJob(latest)
    if (latest.job_id && !sourceRef.current) subscribeToJob(latest.job_id)
  }

  useEffect(() => {
    refreshLatestJob().catch((error) => {
      setToast({ tone: 'bad', title: '状态读取失败', detail: error.message })
    })
    return () => {
      closeSource()
      stopPolling()
    }
  }, [])

  return { connection, job, refreshLatestJob, setConnection, setJob, subscribeToJob }
}

function useDashboardNavigation() {
  const [activePage, setActivePage] = useState(() => (
    typeof window === 'undefined' ? DEFAULT_PAGE : parseDashboardRoute(window.location.hash).page
  ))
  const [activeModule, setActiveModule] = useState(() => (
    typeof window === 'undefined'
      ? DEFAULT_MODULE_BY_PAGE[DEFAULT_PAGE]
      : parseDashboardRoute(window.location.hash).moduleId
  ))
  const [moduleOrder, setModuleOrder] = useState(loadModuleOrder)
  const dragModuleRef = useRef('')

  useEffect(() => {
    const onHashChange = () => {
      const route = parseDashboardRoute(window.location.hash)
      setActivePage(route.page)
      setActiveModule(route.moduleId)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const changeModule = (page, moduleId) => {
    setActivePage(page)
    setActiveModule(moduleId)
    if (typeof window !== 'undefined') window.location.hash = `${page}/${moduleId}`
  }
  const changePage = (page) => changeModule(page, DEFAULT_MODULE_BY_PAGE[page])
  const reorderModules = (page, fromId, toId) => {
    setModuleOrder((current) => {
      const next = {
        ...current,
        [page]: moveItem(current[page] || DEFAULT_MODULE_ORDER[page], fromId, toId),
      }
      saveModuleOrder(next)
      return next
    })
  }
  const moduleDragProps = (page, id) => ({
    draggable: true,
    onDragStart: (event) => {
      dragModuleRef.current = id
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', id)
    },
    onDragOver: (event) => {
      event.preventDefault()
      event.dataTransfer.dropEffect = 'move'
    },
    onDrop: (event) => {
      event.preventDefault()
      reorderModules(page, event.dataTransfer.getData('text/plain') || dragModuleRef.current, id)
    },
    style: { order: Math.max(0, (moduleOrder[page] || DEFAULT_MODULE_ORDER[page]).indexOf(id)) },
    title: '拖动模块排序',
  })
  const panelClass = (page, id, extra = '') => [
    'tp-panel',
    extra,
    `tp-${page}-module`,
    activePage === page && activeModule === id ? 'is-active-module' : '',
  ].filter(Boolean).join(' ')

  return { activeModule, activePage, changeModule, changePage, moduleDragProps, panelClass }
}

function useJobLauncher({ job, setConnection, setJob, setToast, subscribeToJob }) {
  const [pipelinePayload, setPipelinePayload] = useState(DEFAULT_PIPELINE_PAYLOAD)
  const [projectPayload, setProjectPayload] = useState({ project_id: '00_screen', mode: 'safe_check' })
  const [submitting, setSubmitting] = useState('')
  const isBusy = submitting !== '' || ['queued', 'running'].includes(job.status)

  const launchJob = async (kind) => {
    const targets = {
      checks: ['/api/dashboard/jobs/system-checks', {}, '全部项目检查', 'system_checks'],
      project: ['/api/dashboard/jobs/project', projectPayload, '子项目启动', `project:${projectPayload.project_id}:${projectPayload.mode}`],
      pipeline: ['/api/dashboard/jobs/pipeline', pipelinePayload, 'Pipeline 启动', pipelinePayload.step],
      regime: ['/api/dashboard/jobs/signals/regime', {}, 'Regime 刷新', 'signal:regime_risk_budget'],
      country: ['/api/dashboard/jobs/signals/country', {}, 'Country model 刷新', 'signal:country_model'],
    }
    const [endpoint, payload, label, pendingStep] = targets[kind]
    setSubmitting(kind)
    setConnection('submitting')
    setToast({ tone: 'info', title: `${label}已提交`, detail: '前端已立即接收点击，正在创建后台 job。' })
    setJob({
      ...EMPTY_JOB,
      job_id: 'pending',
      step: pendingStep,
      status: 'running',
      status_label: 'SUBMITTING',
      log_tail: '正在向后端提交 job...',
    })
    try {
      const result = await requestJson(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setJob(result.job)
      subscribeToJob(result.job.job_id)
      setToast({
        tone: 'good',
        title: `${label}已创建`,
        detail: `job_id ${result.job.job_id || 'N/A'} / PID ${result.job.pid || 'N/A'}`,
      })
    } catch (error) {
      setToast({ tone: 'bad', title: `${label}失败`, detail: error.message })
      setJob({ ...EMPTY_JOB, log_tail: error.message })
      setConnection('api')
    } finally {
      setSubmitting('')
    }
  }

  return {
    isBusy,
    launchJob,
    pipelinePayload,
    projectPayload,
    setPipelinePayload,
    setProjectPayload,
    submitting,
  }
}

function useProductionRows(job, connection, dashboardState) {
  const metrics = useMemo(
    () => [
      ['当前状态', statusText(job.status), job.status_label || 'IDLE'],
      ['运行目标', job.step || 'N/A', job.job_id || 'N/A'],
      ['状态通道', connection.toUpperCase(), job.log_path || 'log: N/A'],
      [
        '数据快照',
        dashboardState.generated_at ? dashboardState.generated_at.replace('T', ' ') : 'N/A',
        `${dashboardState.projects.length} projects / ${dashboardState.assets.length} assets`,
      ],
      [
        '后台队列',
        `${dashboardState.queue.counts.queued} queued / ${dashboardState.queue.counts.running} running`,
        `${dashboardState.queue.thread_worker_alive ? 'worker alive' : 'worker idle'} / pending ${dashboardState.queue.in_memory_pending}`,
      ],
    ],
    [connection, dashboardState, job],
  )
  const queueRows = useMemo(
    () => (dashboardState.queue.recent || []).map((item) => ({
      job_id: item.job_id,
      状态: item.status,
      step: item.step,
      更新时间: item.updated_at,
      backend: item.backend || item.queue_name,
    })),
    [dashboardState.queue.recent],
  )
  return {
    latestMarketBrief: dashboardState.latest_market_brief || EMPTY_DASHBOARD_STATE.latest_market_brief,
    metrics,
    queueRows,
  }
}

function useRegimeRows(dashboardState) {
  const regimeSignal = dashboardState.signals?.regime || EMPTY_DASHBOARD_STATE.signals.regime
  const regimeRows = useMemo(
    () => (regimeSignal.rows || []).map((item) => ({
      region: item.region,
      最新月份: item.最新月份,
      regime: item.regime,
      风险预算: item.risk_budget,
      状态: item.state,
      model: item.model,
    })),
    [regimeSignal],
  )
  const regimeHistoryRows = useMemo(
    () => (regimeSignal.history || []).map((item) => ({
      region: item.region,
      月份: item.最新月份,
      regime: item.regime,
      风险预算: item.risk_budget,
      状态: item.state,
    })),
    [regimeSignal],
  )
  const regimeModels = regimeSignal.models || EMPTY_DASHBOARD_STATE.signals.regime.models
  return {
    directionModelRows: regimeModels.direction_models || [],
    drawdownModelRows: regimeModels.drawdown_models || [],
    regimeHistoryRows,
    regimeModels,
    regimeRows,
    regimeSignal,
    riskModelRows: regimeModels.risk_models || [],
    stateModelRows: regimeModels.state_models || [],
    volatilityModelRows: regimeModels.volatility_models || [],
  }
}

function useCountryRows(dashboardState) {
  const countrySignal = dashboardState.signals?.country || EMPTY_DASHBOARD_STATE.signals.country
  const countryRows = useMemo(
    () => (countrySignal.rows || []).map((item) => ({
      region: item.region,
      最新月份: item.最新月份,
      score: item.score,
      rank: item.rank,
      recommendation: item.recommendation,
      'Δ rank': item.rank_delta,
      margin: item.margin,
      profitability: item.profitability,
      growth: item.growth,
      value: item.value,
      momentum: item.momentum,
    })),
    [countrySignal],
  )
  const countryHistoryRows = useMemo(
    () => (countrySignal.history || []).map((item) => ({
      region: item.region,
      月份: item.最新月份,
      score: item.score,
      rank: item.rank,
      recommendation: item.recommendation,
    })),
    [countrySignal],
  )
  const singleCountryRows = useMemo(
    () => (countrySignal.single_country_rows || []).map((item) => ({
      国家: item.country,
      指数: item.country_label,
      最新月份: item.最新月份,
      score: item.score,
      rank: item.rank,
      margin: item.margin,
      profitability: item.profitability,
      growth: item.growth,
      value: item.value,
      momentum: item.momentum,
    })),
    [countrySignal],
  )
  return {
    countryHistoryRows,
    countryRows,
    countrySignal,
    countryVisualRows: countrySignal.rows || [],
    singleCountryRows,
    singleCountrySignalRows: countrySignal.single_country_rows || [],
  }
}

function useSectorRows(dashboardState, selectedSector) {
  const sectorSignal = dashboardState.signals?.sector || EMPTY_DASHBOARD_STATE.signals.sector
  const sectorVisualRows = sectorSignal.rows || []
  const selectedSectorRow = useMemo(
    () => sectorVisualRows.find(
      (item) => item.market === selectedSector?.market && item.sector_name === selectedSector?.sector_name,
    ) || selectedSector,
    [sectorVisualRows, selectedSector],
  )
  const sectorRows = useMemo(
    () => (sectorSignal.rows || []).map((item) => ({
      market: item.market,
      sector: item.sector_name,
      最新月份: item.最新月份,
      rank: item.rank,
      recommendation: item.recommendation,
      score: item.score,
      leverage: item.leverage,
      margin: item.margin,
      valuation: item.valuation,
      momentum: item.momentum,
      growth: item.growth,
      lowvol: item.lowvol,
      weight: item.sector_weight,
      names: item.constituents,
    })),
    [sectorSignal],
  )
  return {
    sectorMarkets: sectorSignal.markets || [],
    sectorRows,
    sectorSignal,
    sectorVisualRows,
    selectedSectorRow,
  }
}

function useScoreMlRows(scoreMlComponents) {
  return useMemo(
    () => (scoreMlComponents.rows || []).map((item) => ({
      Name: item.Name,
      Weight: item.Weight,
      'Score ML': item['Score ML'],
      'Score ML_IF': item['Score ML_IF'],
      Value: item.Value,
      Quality: item.Quality,
      Momentum: item.Momentum,
      Growth: item.Growth,
      LowVol: item.LowVol,
      Div: item.Div,
      Size: item.Size,
      'PE LTM': item['PE LTM'],
      'PE FY1': item['PE FY1'],
      'EPS Growth FY1': item['EPS Growth FY1'],
      ROE: item.ROE,
      'Dividend Yield': item['Dividend Yield'],
      'Earnings Yield': item['Earnings Yield'],
      Country: item.Country,
      Region: item.Region,
      Sector: item.Sector,
      ISIN: item.ISIN,
    })),
    [scoreMlComponents],
  )
}

function useTechnicalRows(dashboardState) {
  const technicalSignal = dashboardState.signals?.technical || EMPTY_DASHBOARD_STATE.signals.technical
  const technicalMetricRows = useMemo(
    () => (technicalSignal.metric_rows || []).map((item) => ({
      市场: item.市场,
      metric: item.metric,
      处理: item.处理,
      证据: item.证据,
      推荐端: item.推荐端,
      覆盖: item.覆盖,
      覆盖率: item.覆盖率,
      均值: item.均值,
      中位数: item.中位数,
      最小: item.最小,
      最大: item.最大,
      并列率: item.并列率,
      事件率: item.事件率,
      说明: item.说明,
    })),
    [technicalSignal],
  )
  const technicalSecurityRows = useMemo(
    () => (technicalSignal.security_rows || []).map((item) => ({
      市场: item.市场,
      metric: item.metric,
      处理: item.处理,
      推荐端: item.推荐端,
      Name: item.Name,
      score: item.score,
      Weight: item.Weight,
      Country: item.Country,
      Region: item.Region,
      Sector: item.Sector,
      ISIN: item.ISIN,
    })),
    [technicalSignal],
  )
  return { technicalMetricRows, technicalSecurityRows, technicalSignal }
}

function companyCellRenderer(openCompanyDetail, technical = false) {
  return (column, row) => {
    if (column === 'Name' && row.ISIN) {
      return (
        <button className="tp-table-link" onClick={() => openCompanyDetail(row)} type="button">
          {cellText(row.Name)}
        </button>
      )
    }
    if (technical && ['处理', '证据', '推荐端'].includes(column)) {
      return <span className={`tp-technical-tag ${technicalTone(row[column])}`}>{cellText(row[column])}</span>
    }
    if (!technical && column.includes('状态')) return <StatusPill value={row[column]} />
    return cellText(row[column])
  }
}

function App() {
  const [toast, setToast] = useState({ tone: 'neutral', title: 'Ready', detail: '等待操作' })
  const data = useDashboardData(setToast)
  useQueueStream(data.setDashboardState, setToast)
  const jobRuntime = useJobStream(data.refreshDashboardState, setToast)
  const navigation = useDashboardNavigation()
  const launcher = useJobLauncher({ ...jobRuntime, setToast })
  const {
    companyDetail,
    companyDetailError,
    companyDetailLoading,
    dashboardState,
    openCompanyDetail,
    refreshingState,
    refreshDashboardState,
    refreshScoreMlComponents,
    scoreMlComponents,
    scoreMlLoading,
    scoreMlSelection,
    selectedSector,
    setCompanyDetail,
    setCompanyDetailError,
    setCompanyDetailLoading,
    setPipelinePayload,
    setProjectPayload,
    setSelectedSector,
  } = { ...data, ...launcher }
  const { connection, job, refreshLatestJob } = jobRuntime
  const { activeModule, activePage, changeModule, changePage, moduleDragProps, panelClass } = navigation
  const { isBusy, launchJob, pipelinePayload, projectPayload, submitting } = launcher
  const activePhase = phaseIndex(job.phase)
  const progressPercent = job.status === 'idle' ? 0 : Math.round(((activePhase + 1) / PHASES.length) * 100)
  const {
    latestMarketBrief,
    metrics,
    queueRows,
  } = useProductionRows(job, connection, dashboardState)
  const {
    directionModelRows,
    drawdownModelRows,
    regimeHistoryRows,
    regimeModels,
    regimeRows,
    regimeSignal,
    riskModelRows,
    stateModelRows,
    volatilityModelRows,
  } = useRegimeRows(dashboardState)
  const {
    countryHistoryRows,
    countryRows,
    countrySignal,
    countryVisualRows,
    singleCountryRows,
    singleCountrySignalRows,
  } = useCountryRows(dashboardState)
  const {
    sectorMarkets,
    sectorRows,
    sectorSignal,
    sectorVisualRows,
    selectedSectorRow,
  } = useSectorRows(dashboardState, selectedSector)
  const scoreMlRows = useScoreMlRows(scoreMlComponents)
  const {
    technicalMetricRows,
    technicalSecurityRows,
    technicalSignal,
  } = useTechnicalRows(dashboardState)
  const renderTechnicalCell = companyCellRenderer(openCompanyDetail, true)
  const renderScoreMlCell = companyCellRenderer(openCompanyDetail)
  const activeSection = NAV_SECTIONS.find((section) => section.page === activePage) || NAV_SECTIONS[0]
  const activeModuleConfig = activeSection.modules.find(([id]) => id === activeModule) || activeSection.modules[0]
  const panelProps = {
    activePhase,
    companyDetail,
    companyDetailError,
    companyDetailLoading,
    countryHistoryRows,
    countryRows,
    countrySignal,
    countryVisualRows,
    dashboardState,
    directionModelRows,
    drawdownModelRows,
    isBusy,
    job,
    latestMarketBrief,
    launchJob,
    metrics,
    moduleDragProps,
    panelClass,
    pipelinePayload,
    progressPercent,
    projectPayload,
    queueRows,
    refreshScoreMlComponents,
    refreshingState,
    regimeHistoryRows,
    regimeModels,
    regimeRows,
    regimeSignal,
    renderScoreMlCell,
    renderTechnicalCell,
    riskModelRows,
    scoreMlComponents,
    scoreMlLoading,
    scoreMlRows,
    scoreMlSelection,
    sectorMarkets,
    sectorRows,
    sectorSignal,
    sectorVisualRows,
    selectedSectorRow,
    setCompanyDetail,
    setCompanyDetailError,
    setCompanyDetailLoading,
    setPipelinePayload,
    setProjectPayload,
    setSelectedSector,
    singleCountryRows,
    singleCountrySignalRows,
    stateModelRows,
    submitting,
    technicalMetricRows,
    technicalSecurityRows,
    technicalSignal,
    volatilityModelRows,
  }

  return (
    <div className="tp-shell">
      <aside className="tp-sidebar">
        <div className="tp-brand">
          <p className="tp-kicker">React job control</p>
          <h1>TP System Dashboard</h1>
          <span>{job.status_label || 'IDLE'} / {connection}</span>
        </div>
        <PageTabs activePage={activePage} activeModule={activeModule} onChange={changePage} onModuleChange={changeModule} />
      </aside>

      <div className="tp-content">
        <header className="tp-topbar">
          <div>
            <p className="tp-kicker">{activeSection.label}</p>
            <h1>{activeModuleConfig[1]}</h1>
            <span className="tp-topbar-subtitle">{activeModuleConfig[2]}</span>
          </div>
          <button
            className="tp-icon-button"
            disabled={refreshingState}
            onClick={() => {
              refreshLatestJob().catch((error) => setToast({ tone: 'bad', title: '状态读取失败', detail: error.message }))
              refreshDashboardState()
            }}
            type="button"
          >
            <RefreshCw className={refreshingState ? 'tp-spin' : ''} size={18} />
            <span>刷新状态</span>
          </button>
        </header>

        <main className="tp-main">
          <section className={`tp-dashboard-grid tp-page-${activePage} tp-module-${activeModule}`}>
          <MarketBriefPanel {...panelProps} />
          <RunControlPanel {...panelProps} />
          <LiveJobPanel {...panelProps} />
          <OverviewPanel {...panelProps} />
          <AlertsPanel {...panelProps} />
          <RegimePanel {...panelProps} />
          <CountryPanel {...panelProps} />
          <SectorPanel {...panelProps} />
          <TechnicalPanel {...panelProps} />
          <ScoreMlPanel {...panelProps} />
          <ProductionTables {...panelProps} />
          <FactorExplorerPanel {...panelProps} />
        </section>

        <section className={`tp-toast is-${toast.tone || 'neutral'}`} aria-live="polite">
          <Server size={18} />
          <div>
            <strong>{toast.title}</strong>
            <span>{toast.detail}</span>
          </div>
        </section>
        </main>
      </div>
    </div>
  )
}

export default App
