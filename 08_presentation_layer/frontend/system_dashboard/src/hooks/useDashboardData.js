import { useEffect, useState } from 'react'

import { requestJson } from '../api/dashboardApi.js'
import {
  EMPTY_DASHBOARD_STATE,
  normalizeDashboardState,
} from '../domain/dashboardContracts.js'
export function useDashboardData(setToast) {
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

