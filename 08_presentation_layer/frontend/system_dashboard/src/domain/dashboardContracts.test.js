import { expect, test } from 'vitest'

import {
  EMPTY_DASHBOARD_STATE,
  EMPTY_FACTOR_RECOMMENDATION,
  normalizeDashboardState,
} from './dashboardContracts.js'

test('empty factor recommendation contract is research-only and warning-safe', () => {
  const signal = EMPTY_DASHBOARD_STATE.signals.factor_recommendation

  expect(signal).toBe(EMPTY_FACTOR_RECOMMENDATION)
  expect(signal).toMatchObject({
    status: 'research_only',
    research_only: true,
    missing: true,
    stale: true,
    regions: ['US', 'EU', 'ASIA'],
    rows: [],
    history: [],
    backtest: [],
    baselines: [],
    gates: [],
  })
  expect(signal.warnings).toEqual(expect.arrayContaining(['research_only', 'missing', 'stale', 'ASIA']))
})

test('partial factor signal keeps nested EMPTY fields', () => {
  const state = normalizeDashboardState({
    signals: { factor_recommendation: { status: 'research_only', rows: [] } },
  })

  expect(state.signals.factor_recommendation).toMatchObject({
    status: 'research_only',
    regions: ['US', 'EU', 'ASIA'],
    history: [],
    evidence: [],
    benchmark_definition: {},
  })
})

