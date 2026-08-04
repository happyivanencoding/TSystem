import React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, test } from 'vitest'

import { FactorRecommendationPanel } from './FactorRecommendationComponents.jsx'

afterEach(() => cleanup())

test('empty factor recommendation renders tabs and research-only warnings', () => {
  render(<FactorRecommendationPanel />)

  expect(screen.getByRole('heading', { name: '月度因子推荐' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'US' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'EU' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'ASIA' })).toBeInTheDocument()
  expect(screen.getAllByText('research_only').length).toBeGreaterThan(0)
  expect(screen.getByText('暂无 history')).toBeInTheDocument()
  expect(screen.getByText('暂无 evidence')).toBeInTheDocument()
})

test('research-only rows render latest metrics, evidence, gates and benchmark', () => {
  render(
    <FactorRecommendationPanel
      factorRecommendationHistoryRows={[{
        region: 'US',
        latest_date: '2026-06',
        rank: 2,
        score: 0.64,
        stance: 'neutral',
        predicted_return: 0.02,
        confidence: 0.51,
      }]}
      factorRecommendationRows={[{
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
        warnings: ['stale'],
      }]}
      factorRecommendationSignal={{
        status: 'research_only',
        research_only: true,
        latest_date: '2026-07',
        warnings: ['research_only', 'stale'],
        evidence: ['walk-forward holdout'],
        backtest: [{ name: 'holdout', status: 'passed', detail: '2022+' }],
        baselines: [{ name: 'neutral', status: 'reference' }],
        gates: [{ gate: 'promotion', status: 'research_only' }],
        benchmark_definition: { universe: 'US/EU/ASIA', rebalance: 'monthly' },
      }}
    />,
  )

  expect(screen.getByText('overweight')).toBeInTheDocument()
  expect(screen.getByText('0.07 / 0.03')).toBeInTheDocument()
  expect(screen.getByText('0.06')).toBeInTheDocument()
  expect(screen.getByText('Momentum')).toBeInTheDocument()
  expect(screen.getByText('Quality')).toBeInTheDocument()
  expect(screen.getByText('walk-forward holdout')).toBeInTheDocument()
  expect(screen.getByText('holdout')).toBeInTheDocument()
  expect(screen.getByText('monthly')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'EU' }))
  expect(screen.getByText('暂无可展示的研究结果，等待该区域的月度因子证据。')).toBeInTheDocument()
})
