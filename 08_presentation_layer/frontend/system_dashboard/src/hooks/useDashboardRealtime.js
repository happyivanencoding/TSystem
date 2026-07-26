import { useEffect, useRef, useState } from 'react'

import { dashboardApiUrl, requestJson } from '../api/dashboardApi.js'
import {
  EMPTY_JOB,
  normalizeDashboardState,
} from '../domain/dashboardContracts.js'
export function useQueueStream(setDashboardState, setToast) {
  const sourceRef = useRef(null)
  const pollingRef = useRef(null)

  const stopPolling = () => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }
  const closeSource = () => {
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
    }
  }
  const mergeQueueState = (queue) => {
    setDashboardState((current) => normalizeDashboardState({
      ...current,
      queue: {
        ...current.queue,
        ...queue,
        counts: { ...current.queue?.counts, ...(queue?.counts || {}) },
      },
    }))
  }
  const startPolling = () => {
    stopPolling()
    const pollQueue = async () => {
      try {
        mergeQueueState(await requestJson('/api/dashboard/jobs/queue'))
      } catch (error) {
        setToast({ tone: 'bad', title: '队列状态读取失败', detail: error.message })
      }
    }
    pollQueue()
    pollingRef.current = window.setInterval(pollQueue, 5000)
  }
  const subscribe = () => {
    closeSource()
    stopPolling()
    if (typeof EventSource === 'undefined') {
      startPolling()
      return
    }
    const source = new EventSource(dashboardApiUrl('/api/dashboard/jobs/queue/events'))
    sourceRef.current = source
    source.addEventListener('queue', (event) => mergeQueueState(JSON.parse(event.data)))
    source.onerror = () => {
      closeSource()
      startPolling()
    }
  }

  useEffect(() => {
    subscribe()
    return () => {
      closeSource()
      stopPolling()
    }
  }, [])
}

export function useJobStream(refreshDashboardState, setToast) {
  const [job, setJob] = useState(EMPTY_JOB)
  const [connection, setConnection] = useState('api')
  const sourceRef = useRef(null)
  const pollingRef = useRef(null)
  const pollingInFlightRef = useRef(false)

  const stopPolling = () => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    pollingInFlightRef.current = false
  }
  const closeSource = () => {
    if (sourceRef.current) {
      sourceRef.current.close()
      sourceRef.current = null
    }
  }
  const startPolling = (jobId) => {
    stopPolling()
    if (!jobId) {
      setConnection('api')
      return
    }
    setConnection('polling')
    const pollOnce = async () => {
      if (pollingInFlightRef.current) return
      pollingInFlightRef.current = true
      try {
        const nextJob = await requestJson(`/api/dashboard/jobs/${encodeURIComponent(jobId)}`)
        setJob(nextJob)
        if (['completed', 'failed'].includes(nextJob.status)) {
          stopPolling()
          setConnection('api')
          refreshDashboardState({ quiet: true })
        }
      } catch (error) {
        setToast({ tone: 'bad', title: '任务状态轮询失败', detail: error.message })
      } finally {
        pollingInFlightRef.current = false
      }
    }
    pollOnce()
    pollingRef.current = window.setInterval(pollOnce, 3000)
  }
  const subscribeToJob = (jobId) => {
    closeSource()
    stopPolling()
    if (!jobId || typeof EventSource === 'undefined') {
      startPolling(jobId)
      return
    }
    const source = new EventSource(
      dashboardApiUrl(`/api/dashboard/jobs/${encodeURIComponent(jobId)}/events`),
    )
    sourceRef.current = source
    setConnection('sse')
    source.addEventListener('job', (event) => {
      const nextJob = JSON.parse(event.data)
      setJob(nextJob)
      if (['completed', 'failed'].includes(nextJob.status)) {
        closeSource()
        setConnection('api')
        refreshDashboardState({ quiet: true })
      }
    })
    source.onerror = () => {
      closeSource()
      setToast({ tone: 'warn', title: '实时连接已切换', detail: 'SSE 暂不可用，正在用 API 轮询保持状态更新。' })
      startPolling(jobId)
    }
  }
  const refreshLatestJob = async () => {
    const latest = await requestJson('/api/dashboard/jobs/latest')
    setJob(latest)
    if (latest.job_id && !sourceRef.current) subscribeToJob(latest.job_id)
  }

  useEffect(() => {
    refreshLatestJob().catch((error) => {
      setToast({ tone: 'bad', title: '状态读取失败', detail: error.message })
    })
    return () => {
      closeSource()
      stopPolling()
    }
  }, [])

  return { connection, job, refreshLatestJob, setConnection, setJob, subscribeToJob }
}

