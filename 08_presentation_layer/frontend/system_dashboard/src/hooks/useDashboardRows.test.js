import { expect, test } from 'vitest'

import {
  normalizeFactorRecommendationSignal,
  normalizeFactorRecommendationRow,
} from './useDashboardRows.js'

test('factor recommendation rows normalize flat and nested fields defensively', () => {
  const signal = normalizeFactorRecommendationSignal({
    status: 'research_only',
    latest_date: '2026-07',
    rows: [{
      market: 'US',
      latest: {
        rank: 1,
        score: 0.82,
        stance: 'overweight',
        recommended_return: 0.07,
        neutral_return: 0.03,
        predicted_return: 0.06,
        confidence: 0.74,
        drivers: ['Momentum', 'Quality'],
      },
      warnings: ['ASIA data stale'],
    }],
    history: [{ region: 'US', month: '2026-06', rank: 2, score: 0.66 }],
  })

  expect(signal.regions).toEqual(['US'])
  expect(signal.rows[0]).toMatchObject({
    region: 'US',
    latest_date: '2026-07',
    rank: 1,
    score: 0.82,
    stance: 'overweight',
    recommended_return: 0.07,
    neutral_return: 0.03,
    predicted_return: 0.06,
    confidence: 0.74,
    drivers: ['Momentum', 'Quality'],
    warnings: ['ASIA data stale'],
  })
  expect(signal.history[0]).toMatchObject({
    region: 'US',
    latest_date: '2026-06',
    rank: 2,
    score: 0.66,
  })
})

test('factor recommendation supports region maps and empty payloads', () => {
  const mapped = normalizeFactorRecommendationSignal({
    status: 'ok',
    latest_by_region: {
      EU: { rank: 3, score: 0.55, recommendation: 'neutral' },
    },
  })
  const empty = normalizeFactorRecommendationSignal({ rows: null, history: null, warnings: null })

  expect(mapped.rows[0]).toMatchObject({ region: 'EU', rank: 3, score: 0.55, stance: 'neutral' })
  expect(empty.rows).toEqual([])
  expect(empty.history).toEqual([])
  expect(empty.regions).toEqual(['US', 'EU', 'ASIA'])
})

test('single row normalization never throws on absent nested fields', () => {
  expect(() => normalizeFactorRecommendationRow(null)).not.toThrow()
  expect(normalizeFactorRecommendationRow(null)).toMatchObject({
    region: '',
    drivers: [],
    warnings: [],
  })
})

