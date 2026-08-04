import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { useDashboardData } from './useDashboardData.js'

function jsonResponse(payload, ok = true, status = 200) {
  return { ok, status, json: async () => payload }
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const path = String(url)
    if (path.endsWith('/api/dashboard/state')) return jsonResponse({ projects: [], assets: [], signals: {} })
    if (path.endsWith('/api/dashboard/backtest')) return jsonResponse([])
    if (path.endsWith('/api/dashboard/signals/factor-recommendation')) {
      return jsonResponse({ error: 'not available yet' }, false, 404)
    }
    if (path.includes('/api/dashboard/signals/')) return jsonResponse({ status: 'ok', rows: [] })
    if (path.includes('/api/dashboard/score-ml-components')) return jsonResponse({ status: 'ok', rows: [] })
    throw new Error(`Unexpected request: ${path}`)
  }))
})

afterEach(() => vi.unstubAllGlobals())

test('factor recommendation endpoint is optional and keeps EMPTY state on missing data', async () => {
  const { result } = renderHook(() => useDashboardData(vi.fn()))

  await waitFor(() => expect(result.current.dashboardState.signals.factor_recommendation.status).toBe('research_only'))
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining('/api/dashboard/signals/factor-recommendation'),
    expect.objectContaining({ headers: expect.any(Object) }),
  )
  expect(result.current.dashboardState.signals.factor_recommendation.rows).toEqual([])
})

