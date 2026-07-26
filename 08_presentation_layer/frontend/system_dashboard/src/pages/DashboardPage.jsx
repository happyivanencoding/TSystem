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

import { dashboardApiUrl, requestJson } from '../api/dashboardApi.js'
import {
  ModelRankList,
  RegimeGauge,
  RiskModelMeters,
  StateModelMatrix,
} from '../components/regime/RegimeComponents.jsx'
import {
  DEFAULT_PIPELINE_PAYLOAD,
  EMPTY_DASHBOARD_STATE,
  EMPTY_JOB,
  PHASES,
  normalizeDashboardState,
} from '../domain/dashboardContracts.js'
import {
  cellText,
  phaseIndex,
  statusText,
  statusTone,
  technicalTone,
} from '../domain/formatters.js'
import {
  NAV_SECTIONS,
} from '../domain/navigation.js'
import { useDashboardData } from '../hooks/useDashboardData.js'
import { useDashboardNavigation } from '../hooks/useDashboardNavigation.js'
import {
  useCountryRows,
  useProductionRows,
  useRegimeRows,
  useScoreMlRows,
  useSectorRows,
  useTechnicalRows,
} from '../hooks/useDashboardRows.js'
import {
  useJobStream,
  useQueueStream,
} from '../hooks/useDashboardRealtime.js'
import { useJobLauncher } from '../hooks/useJobLauncher.js'

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

function countryFlag(value) {
  const text = cellText(value)
  return COUNTRY_FLAGS[text] || COUNTRY_FLAGS[text.toUpperCase()] || '🌐'
}

function sectorIconFor(value) {
  const text = cellText(value).toLowerCase()
  const match = SECTOR_ICON_KEYS.find(([keyword]) => text.includes(keyword))
  return match ? match[1] : Building2
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
