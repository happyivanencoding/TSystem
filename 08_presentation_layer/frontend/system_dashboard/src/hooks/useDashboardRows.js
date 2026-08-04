import { useMemo } from 'react'

import {
  EMPTY_DASHBOARD_STATE,
  EMPTY_FACTOR_RECOMMENDATION,
  FACTOR_RECOMMENDATION_REGIONS,
} from '../domain/dashboardContracts.js'
import { statusText } from '../domain/formatters.js'

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function firstValue(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== '')
}

function listValue(value) {
  if (Array.isArray(value)) return value
  if (value === undefined || value === null || value === '') return []
  if (isRecord(value)) return Object.values(value)
  return [value]
}

function rowObjects(value) {
  if (Array.isArray(value)) return value
  if (!isRecord(value)) return []
  return Object.entries(value).map(([region, item]) => (
    isRecord(item) ? { ...item, region: firstValue(item.region, region) } : { region, value: item }
  ))
}

function factorRegion(item, fallback = '') {
  return firstValue(
    item?.region,
    item?.market,
    item?.Region,
    item?.area,
    item?.code,
    item?.name,
    item?.label,
    item?.latest?.region,
    fallback,
  ) || ''
}

function factorLatestItems(signal) {
  const candidates = [signal.factor_rows, signal.rows, signal.latest_rows, signal.latest, signal.current_rows]
  for (const candidate of candidates) {
    const items = rowObjects(candidate)
    if (items.length) return items
  }
  return rowObjects(
    signal.latest_by_region
      || signal.regions_by_region
      || (isRecord(signal.regions) ? signal.regions : null),
  )
}

export function normalizeFactorRecommendationRow(item = {}, fallbackRegion = '', fallbackDate = '') {
  const source = isRecord(item) ? item : { value: item }
  const latest = isRecord(source.latest) ? source.latest : {}
  const comparison = isRecord(source.recommended_vs_neutral)
    ? source.recommended_vs_neutral
    : {}
  const region = factorRegion(source, fallbackRegion)
  return {
    ...source,
    region,
    factor: firstValue(source.factor, source.factor_name, source.factor_label, latest.factor, ''),
    latest_date: firstValue(
      source.latest_date,
      source.latest_month,
      source.最新月份,
      source.month,
      source.date,
      latest.latest_date,
      latest.latest_month,
      latest.最新月份,
      latest.date,
      fallbackDate,
    ) || '',
    rank: firstValue(source.rank, source.latest_rank, latest.rank, latest.latest_rank),
    score: firstValue(source.score, source.latest_score, source.factor_score, latest.score, latest.latest_score, latest.factor_score),
    stance: firstValue(
      source.stance,
      source.recommendation,
      source.recommended_stance,
      latest.stance,
      latest.recommendation,
    ),
    recommended_return: firstValue(
      source.recommended_return,
      source.recommended,
      source.recommend_return,
      latest.recommended_return,
      latest.recommended,
      comparison.recommended_return,
      comparison.recommended,
      comparison.recommended?.predicted_return,
      comparison.recommended?.return,
    ),
    neutral_return: firstValue(
      source.neutral_return,
      source.neutral,
      source.neutral_return_prediction,
      latest.neutral_return,
      latest.neutral,
      comparison.neutral_return,
      comparison.neutral,
      comparison.neutral?.predicted_return,
      comparison.neutral?.return,
    ),
    predicted_return: firstValue(
      source.predicted_return,
      source.predictedReturn,
      source.prediction,
      latest.predicted_return,
      latest.predictedReturn,
      latest.prediction,
    ),
    predicted_active_return: firstValue(
      source.predicted_active_return,
      source.predicted_active,
      latest.predicted_active_return,
    ),
    score_0_100: firstValue(source.score_0_100, source.score, latest.score_0_100, latest.score),
    neutral_weight: firstValue(source.neutral_weight, source.neutral_weight_pct, latest.neutral_weight),
    recommended_weight: firstValue(source.recommended_weight, source.recommended_weight_pct, latest.recommended_weight),
    coverage: firstValue(source.coverage, source.factor_coverage, latest.coverage, latest.factor_coverage),
    confidence: firstValue(source.confidence, latest.confidence),
    drivers: listValue(firstValue(source.drivers, source.driver, latest.drivers, latest.driver)),
    warnings: listValue(firstValue(source.warnings, source.warning, latest.warnings, latest.warning)),
  }
}

export function normalizeFactorRecommendationSignal(value = {}) {
  const source = isRecord(value) ? value : {}
  const latestItems = factorLatestItems(source)
  const fallbackDate = firstValue(source.latest_date, source.latest_month, source.最新月份, '') || ''
  const historyItems = rowObjects(source.history)
  const status = firstValue(source.status, EMPTY_FACTOR_RECOMMENDATION.status)
  const researchOnly = source.research_only ?? status === 'research_only'
  const missing = source.missing ?? latestItems.length === 0
  const stale = source.stale ?? status === 'stale'
  const configuredRegions = listValue(source.regions)
    .map((item) => (isRecord(item) ? factorRegion(item) : item))
    .filter(Boolean)
  const rowRegions = [...latestItems, ...historyItems]
    .map((item) => factorRegion(item))
    .filter(Boolean)
  const regions = [...new Set(configuredRegions.length ? configuredRegions : rowRegions)]
  return {
    ...EMPTY_FACTOR_RECOMMENDATION,
    ...source,
    status,
    research_only: researchOnly,
    missing,
    stale,
    regions: regions.length ? regions : FACTOR_RECOMMENDATION_REGIONS,
    rows: latestItems.map((item) => normalizeFactorRecommendationRow(item, '', fallbackDate)),
    factorRows: rowObjects(source.factor_rows).map((item) => normalizeFactorRecommendationRow(item, '', fallbackDate)),
    forecastRows: rowObjects(source.forecast_rows).map((item) => normalizeFactorRecommendationRow(item, '', fallbackDate)),
    history: historyItems.map((item) => normalizeFactorRecommendationRow(item, '', fallbackDate)),
    warnings: source.warnings !== undefined
      ? listValue(source.warnings)
      : (researchOnly || missing || stale ? EMPTY_FACTOR_RECOMMENDATION.warnings : []),
  }
}

export function useProductionRows(job, connection, dashboardState) {
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

export function useRegimeRows(dashboardState) {
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

export function useCountryRows(dashboardState) {
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

export function useSectorRows(dashboardState, selectedSector) {
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

export function useFactorRecommendationRows(dashboardState) {
  const rawSignal = dashboardState?.signals?.factor_recommendation
  const factorRecommendationSignal = useMemo(
    () => normalizeFactorRecommendationSignal(rawSignal),
    [rawSignal],
  )
  const factorRecommendationRows = useMemo(
    () => factorRecommendationSignal.rows || [],
    [factorRecommendationSignal],
  )
  const factorRecommendationHistoryRows = useMemo(
    () => factorRecommendationSignal.history || [],
    [factorRecommendationSignal],
  )
  return {
    factorRecommendationHistoryRows,
    factorRecommendationRows,
    factorRecommendationSignal,
  }
}

export function useScoreMlRows(scoreMlComponents) {
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

export function useTechnicalRows(dashboardState) {
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
