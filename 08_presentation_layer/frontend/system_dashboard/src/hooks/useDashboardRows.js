import { useMemo } from 'react'

import { EMPTY_DASHBOARD_STATE } from '../domain/dashboardContracts.js'
import { statusText } from '../domain/formatters.js'
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

