import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from './App.jsx'


class FakeEventSource {
  constructor(url) {
    this.url = url
    this.listeners = {}
  }

  addEventListener(type, listener) {
    this.listeners[type] = listener
  }

  close() {}
}


function jsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  }
}


beforeEach(() => {
  window.location.hash = ''
  window.localStorage.clear()
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url) => {
      if (String(url).endsWith('/api/dashboard/jobs/latest')) {
        return jsonResponse({
          job_id: '',
          phase: 'submitted',
          status: 'idle',
          status_label: 'IDLE',
        })
      }
      if (String(url).endsWith('/api/dashboard/state')) {
        return jsonResponse({
          generated_at: '2026-07-26T10:00:00',
          projects: [],
          assets: [],
          latest_market_brief: {
            status: 'ok',
            title: '测试市场简报',
            created: '2026-07-26',
            source_scope: 'test',
            okf_refresh: 'ok',
            section_count: '1',
            sections: [{ heading: '市场', body: '测试内容' }],
          },
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    }),
  )
})


afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})


test('loads dashboard state and renders the default market page', async () => {
  render(<App />)

  expect(screen.getByRole('heading', { name: 'TP System Dashboard' })).toBeInTheDocument()
  expect(await screen.findByRole('heading', { name: '测试市场简报' })).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining('/api/dashboard/state'),
    expect.objectContaining({ headers: expect.any(Object) }),
  )
})
