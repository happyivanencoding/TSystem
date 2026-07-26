const API_BASE = import.meta.env.VITE_TP_DASHBOARD_API || ''

export function dashboardApiUrl(path) {
  return `${API_BASE}${path}`
}

export async function requestJson(path, options = {}) {
  const response = await fetch(dashboardApiUrl(path), {
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    ...options,
  })
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`)
  }
  return payload
}
