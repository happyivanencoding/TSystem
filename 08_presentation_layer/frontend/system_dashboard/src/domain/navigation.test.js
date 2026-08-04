import { expect, test } from 'vitest'

import {
  DEFAULT_MODULE_ORDER,
  NAV_SECTIONS,
  parseDashboardRoute,
} from './navigation.js'

test('factor recommendation sits between sector and score ML', () => {
  const results = NAV_SECTIONS.find((section) => section.page === 'results')
  const ids = results.modules.map(([id]) => id)

  expect(ids.indexOf('factor-recommendation')).toBe(ids.indexOf('sector') + 1)
  expect(ids.indexOf('factor-recommendation')).toBe(ids.indexOf('score-ml') - 1)
  expect(DEFAULT_MODULE_ORDER.results).toEqual(ids)
})

test('factor recommendation route resolves to the results module', () => {
  expect(parseDashboardRoute('#results/factor-recommendation')).toEqual({
    page: 'results',
    moduleId: 'factor-recommendation',
  })
})

