import React, { useEffect, useMemo, useState } from 'react'
import {
  Building2,
  Cpu,
  Factory,
  HeartPulse,
  Home,
  Landmark,
  ShoppingBag,
  Truck,
  X,
  Zap,
} from 'lucide-react'

import { cellText } from '../../domain/formatters.js'
import { countryFlag, countryScoreWidth } from './CountryComponents.jsx'

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

function sectorIconFor(value) {
  const text = cellText(value).toLowerCase()
  const match = SECTOR_ICON_KEYS.find(([keyword]) => text.includes(keyword))
  return match ? match[1] : Building2
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

export function SectorRotationMap({ rotation, rows, onSelect }) {
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

export function SectorMarketBoard({ market, rows, onSelect, selectedSector }) {
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

export function SectorAnalysisDrawer({ item, monthlyReport, onClose }) {
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
