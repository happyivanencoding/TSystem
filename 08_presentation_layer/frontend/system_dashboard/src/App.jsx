import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  CheckCircle2,
  Database,
  Loader2,
  Play,
  RefreshCw,
  Server,
  ShieldCheck,
} from 'lucide-react'

const API_BASE = import.meta.env.VITE_TP_DASHBOARD_API || ''

const PHASES = [
  ['submitted', '已提交'],
  ['running', '运行中'],
  ['evidence', '等证据'],
  ['done', '完成'],
]

const DEFAULT_PIPELINE_PAYLOAD = {
  step: 'run_all',
  input_month: '',
  as_of: '',
  update_mode: 'both',
  flags: ['skip_refresh', 'skip_backtest', 'dry_run_data', 'inspect_backtest'],
  top_pct: 0.1,
  ml_weight: 0.7,
  technical_weight: 0.3,
  max_weight: 0.05,
  optimizer_method: 'score_weight',
  portfolio_region: '',
  backtest_profile: 'default',
  bench: '',
  start_date: '',
  percentile: null,
}

const EMPTY_JOB = {
  job_id: '',
  step: '暂无启动任务',
  status: 'idle',
  status_label: 'IDLE',
  phase: 'submitted',
  pid: '',
  started_at: '',
  manifest_status: 'N/A',
  manifest: '',
  log_path: '',
  log_tail: '',
  backend: '',
  queue_name: '',
  queued_at: '',
  status_updated_at: '',
  finished_at: '',
  returncode: '',
  error: '',
}

const EMPTY_DASHBOARD_STATE = {
  generated_at: '',
  overview: [],
  alerts: [],
  projects: [],
  assets: [],
  core_database: [],
  pipeline: [],
  queue: {
    queue_name: '',
    thread_worker_alive: false,
    in_memory_pending: 0,
    total_records: 0,
    counts: { queued: 0, running: 0, completed: 0, failed: 0, other: 0 },
    latest_job_id: '',
    recent: [],
  },
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    ...options,
  })
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`)
  }
  return payload
}

function phaseIndex(phase) {
  return Math.max(0, PHASES.findIndex(([value]) => value === phase))
}

function statusText(status) {
  if (status === 'queued') return '已排队'
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'evidence_waiting') return '等待证据'
  return '空闲'
}

function cellText(value) {
  if (value === null || value === undefined || value === '') return 'N/A'
  return String(value)
}

function statusTone(value) {
  const text = cellText(value).toLowerCase()
  if (['ok', 'success', 'passed', 'completed', '已完成'].some((item) => text.includes(item))) return 'is-ok'
  if (['fail', 'failed', 'error', '缺失'].some((item) => text.includes(item))) return 'is-bad'
  if (['check', 'warning', '等待', '未检查', 'n/a'].some((item) => text.includes(item))) return 'is-warn'
  return 'is-muted'
}

function ActionButton({ icon: Icon, label, description, disabled, active = false, busy = false, onClick }) {
  const ButtonIcon = busy ? Loader2 : Icon
  return (
    <button
      aria-busy={busy ? 'true' : 'false'}
      className={active ? 'tp-action-button is-active' : 'tp-action-button'}
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      <ButtonIcon className={busy ? 'tp-spin' : ''} size={18} />
      <span>
        <strong>{label}</strong>
        <small>{description}</small>
      </span>
    </button>
  )
}

function StatusPill({ value }) {
  return <span className={`tp-status-pill ${statusTone(value)}`}>{cellText(value)}</span>
}

function DataTable({ columns, rows, limit = 8 }) {
  const visibleRows = rows.slice(0, limit)
  if (!visibleRows.length) {
    return <div className="tp-empty">暂无数据</div>
  }
  return (
    <div className="tp-table-wrap">
      <table className="tp-data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((row, rowIndex) => (
            <tr key={`${rowIndex}-${columns.map((column) => row[column]).join('-')}`}>
              {columns.map((column) => (
                <td key={column} title={cellText(row[column])}>
                  {column.includes('状态') ? <StatusPill value={row[column]} /> : cellText(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function App() {
  const [job, setJob] = useState(EMPTY_JOB)
  const [dashboardState, setDashboardState] = useState(EMPTY_DASHBOARD_STATE)
  const [pipelinePayload, setPipelinePayload] = useState(DEFAULT_PIPELINE_PAYLOAD)
  const [projectPayload, setProjectPayload] = useState({ project_id: '00_screen', mode: 'safe_check' })
  const [toast, setToast] = useState({ tone: 'neutral', title: 'Ready', detail: '等待操作' })
  const [submitting, setSubmitting] = useState('')
  const [refreshingState, setRefreshingState] = useState(false)
  const [connection, setConnection] = useState('api')
  const eventSourceRef = useRef(null)
  const queueSourceRef = useRef(null)
  const pollingRef = useRef(null)
  const queuePollingRef = useRef(null)
  const pollingInFlightRef = useRef(false)

  const activePhase = phaseIndex(job.phase)
  const isBusy = submitting !== '' || ['queued', 'running'].includes(job.status)
  const progressPercent = job.status === 'idle' ? 0 : Math.round(((activePhase + 1) / PHASES.length) * 100)

  const stopPolling = () => {
    if (pollingRef.current) {
      window.clearInterval(pollingRef.current)
      pollingRef.current = null
    }
    pollingInFlightRef.current = false
  }

  const closeSource = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }

  const mergeQueueState = (queue) => {
    setDashboardState((current) => ({
      ...current,
      queue: {
        ...EMPTY_DASHBOARD_STATE.queue,
        ...queue,
        counts: {
          ...EMPTY_DASHBOARD_STATE.queue.counts,
          ...(queue?.counts || {}),
        },
      },
    }))
  }

  const stopQueuePolling = () => {
    if (queuePollingRef.current) {
      window.clearInterval(queuePollingRef.current)
      queuePollingRef.current = null
    }
  }

  const closeQueueSource = () => {
    if (queueSourceRef.current) {
      queueSourceRef.current.close()
      queueSourceRef.current = null
    }
  }

  const startQueuePolling = () => {
    stopQueuePolling()
    const pollQueue = async () => {
      try {
        mergeQueueState(await requestJson('/api/dashboard/jobs/queue'))
      } catch (error) {
        setToast({ tone: 'bad', title: '队列状态读取失败', detail: error.message })
      }
    }
    pollQueue()
    queuePollingRef.current = window.setInterval(pollQueue, 5000)
  }

  const subscribeToQueue = () => {
    closeQueueSource()
    stopQueuePolling()
    if (typeof EventSource === 'undefined') {
      startQueuePolling()
      return
    }
    const source = new EventSource(`${API_BASE}/api/dashboard/jobs/queue/events`)
    queueSourceRef.current = source
    source.addEventListener('queue', (event) => {
      mergeQueueState(JSON.parse(event.data))
    })
    source.onerror = () => {
      closeQueueSource()
      startQueuePolling()
    }
  }

  const refreshDashboardState = async ({ quiet = false } = {}) => {
    setRefreshingState(true)
    if (!quiet) {
      setToast({ tone: 'info', title: '正在刷新状态', detail: '正在读取项目、资产、核心库和 pipeline 快照。' })
    }
    try {
      const nextState = await requestJson('/api/dashboard/state')
      setDashboardState({ ...EMPTY_DASHBOARD_STATE, ...nextState })
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

  const startJobPolling = (jobId) => {
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
        if (nextJob.status === 'completed' || nextJob.status === 'failed') {
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
      startJobPolling(jobId)
      return
    }
    const source = new EventSource(`${API_BASE}/api/dashboard/jobs/${encodeURIComponent(jobId)}/events`)
    eventSourceRef.current = source
    setConnection('sse')
    source.addEventListener('job', (event) => {
      const nextJob = JSON.parse(event.data)
      setJob(nextJob)
      if (nextJob.status === 'completed' || nextJob.status === 'failed') {
        closeSource()
        setConnection('api')
        refreshDashboardState({ quiet: true })
      }
    })
    source.onerror = () => {
      closeSource()
      setToast({ tone: 'warn', title: '实时连接已切换', detail: 'SSE 暂不可用，正在用 API 轮询保持状态更新。' })
      startJobPolling(jobId)
    }
  }

  const refreshLatestJob = async () => {
    const latest = await requestJson('/api/dashboard/jobs/latest')
    setJob(latest)
    if (latest.job_id && !eventSourceRef.current) {
      subscribeToJob(latest.job_id)
    }
  }

  useEffect(() => {
    refreshLatestJob().catch((error) => {
      setToast({ tone: 'bad', title: '状态读取失败', detail: error.message })
    })
    refreshDashboardState({ quiet: true })
    subscribeToQueue()
    return () => {
      closeSource()
      stopPolling()
      closeQueueSource()
      stopQueuePolling()
    }
  }, [])

  const launchJob = async (kind) => {
    const targets = {
      checks: {
        endpoint: '/api/dashboard/jobs/system-checks',
        payload: {},
        label: '全部项目检查',
        pendingStep: 'system_checks',
      },
      project: {
        endpoint: '/api/dashboard/jobs/project',
        payload: projectPayload,
        label: '子项目启动',
        pendingStep: `project:${projectPayload.project_id}:${projectPayload.mode}`,
      },
      pipeline: {
        endpoint: '/api/dashboard/jobs/pipeline',
        payload: pipelinePayload,
        label: 'Pipeline 启动',
        pendingStep: pipelinePayload.step,
      },
    }
    const target = targets[kind]
    setSubmitting(kind)
    setConnection('submitting')
    setToast({ tone: 'info', title: `${target.label}已提交`, detail: '前端已立即接收点击，正在创建后台 job。' })
    setJob({
      ...EMPTY_JOB,
      job_id: 'pending',
      step: target.pendingStep,
      status: 'running',
      status_label: 'SUBMITTING',
      log_tail: '正在向后端提交 job...',
    })
    try {
      const result = await requestJson(target.endpoint, {
        method: 'POST',
        body: JSON.stringify(target.payload),
      })
      setJob(result.job)
      subscribeToJob(result.job.job_id)
      setToast({
        tone: 'good',
        title: `${target.label}已创建`,
        detail: `job_id ${result.job.job_id || 'N/A'} / PID ${result.job.pid || 'N/A'}`,
      })
    } catch (error) {
      setToast({ tone: 'bad', title: `${target.label}失败`, detail: error.message })
      setJob({ ...EMPTY_JOB, log_tail: error.message })
      setConnection('api')
    } finally {
      setSubmitting('')
    }
  }

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
    () =>
      (dashboardState.queue.recent || []).map((item) => ({
        job_id: item.job_id,
        状态: item.status,
        step: item.step,
        更新时间: item.updated_at,
        backend: item.backend || item.queue_name,
      })),
    [dashboardState.queue.recent],
  )

  return (
    <div className="tp-shell">
      <header className="tp-topbar">
        <div>
          <p className="tp-kicker">React job control</p>
          <h1>TP System Dashboard</h1>
        </div>
        <button
          className="tp-icon-button"
          disabled={refreshingState}
          onClick={() => {
            refreshLatestJob().catch((error) => setToast({ tone: 'bad', title: '状态读取失败', detail: error.message }))
            refreshDashboardState()
          }}
          type="button"
        >
          <RefreshCw className={refreshingState ? 'tp-spin' : ''} size={18} />
          <span>刷新状态</span>
        </button>
      </header>

      <main className="tp-main">
        <section className="tp-status-strip">
          {metrics.map(([label, value, note]) => (
            <div className="tp-metric" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
              <small>{note}</small>
            </div>
          ))}
        </section>

        <section className="tp-workspace">
          <div className="tp-panel tp-run-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Run control</p>
                <h2>启动任务</h2>
              </div>
              {isBusy && <Loader2 className="tp-spin" size={20} />}
            </div>

            <div className="tp-action-grid">
              <ActionButton
                active={submitting === 'checks' || (job.step === 'system_checks' && ['queued', 'running'].includes(job.status))}
                busy={submitting === 'checks'}
                description="安全 smoke / inspect"
                disabled={isBusy}
                icon={ShieldCheck}
                label="全部项目检查"
                onClick={() => launchJob('checks')}
              />
              <ActionButton
                active={submitting === 'project' || (job.step?.startsWith('project:') && ['queued', 'running'].includes(job.status))}
                busy={submitting === 'project'}
                description={`${projectPayload.project_id} / ${projectPayload.mode}`}
                disabled={isBusy}
                icon={Database}
                label="启动子项目"
                onClick={() => launchJob('project')}
              />
              <ActionButton
                active={submitting === 'pipeline' || (!job.step?.startsWith('project:') && job.step !== 'system_checks' && ['queued', 'running'].includes(job.status))}
                busy={submitting === 'pipeline'}
                description={`${pipelinePayload.step} / ${pipelinePayload.update_mode}`}
                disabled={isBusy}
                icon={Play}
                label="启动 Pipeline"
                onClick={() => launchJob('pipeline')}
              />
            </div>

            <div className="tp-form-grid">
              <label>
                <span>Pipeline step</span>
                <select
                  value={pipelinePayload.step}
                  onChange={(event) => setPipelinePayload({ ...pipelinePayload, step: event.target.value })}
                >
                  <option value="run_all">run_all</option>
                  <option value="refresh_data">refresh_data</option>
                  <option value="export_signals">export_signals</option>
                  <option value="build_candidates">build_candidates</option>
                  <option value="optimize_portfolio">optimize_portfolio</option>
                  <option value="run_backtest">run_backtest</option>
                  <option value="generate_report">generate_report</option>
                </select>
              </label>
              <label>
                <span>Update mode</span>
                <select
                  value={pipelinePayload.update_mode}
                  onChange={(event) =>
                    setPipelinePayload({ ...pipelinePayload, update_mode: event.target.value })
                  }
                >
                  <option value="both">both</option>
                  <option value="screen_only">screen_only</option>
                  <option value="returns_only">returns_only</option>
                </select>
              </label>
              <label>
                <span>Project</span>
                <input
                  value={projectPayload.project_id}
                  onChange={(event) => setProjectPayload({ ...projectPayload, project_id: event.target.value })}
                />
              </label>
              <label>
                <span>Project mode</span>
                <select
                  value={projectPayload.mode}
                  onChange={(event) => setProjectPayload({ ...projectPayload, mode: event.target.value })}
                >
                  <option value="safe_check">safe_check</option>
                  <option value="registered_command">registered_command</option>
                </select>
              </label>
            </div>
          </div>

          <div className="tp-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Live job</p>
                <h2>{job.status_label || 'IDLE'}</h2>
              </div>
              {job.status === 'completed' ? <CheckCircle2 size={22} /> : <Activity size={22} />}
            </div>

            <div className={`tp-job-badge tp-job-${job.status}`}>{job.step || 'N/A'}</div>
            <div className="tp-job-progress" aria-label="任务进度">
              <span style={{ width: `${progressPercent}%` }} />
            </div>
            <div className="tp-phase-row">
              {PHASES.map(([, label], index) => (
                <span className={index <= activePhase ? 'tp-phase tp-phase-active' : 'tp-phase'} key={label}>
                  {label}
                </span>
              ))}
            </div>

            <dl className="tp-details">
              <div>
                <dt>job_id</dt>
                <dd>{job.job_id || 'N/A'}</dd>
              </div>
              <div>
                <dt>PID</dt>
                <dd>{job.pid || 'N/A'}</dd>
              </div>
              <div>
                <dt>backend</dt>
                <dd>{job.backend || 'N/A'}{job.queue_name ? ` / ${job.queue_name}` : ''}</dd>
              </div>
              <div>
                <dt>updated</dt>
                <dd>{job.status_updated_at || job.queued_at || 'N/A'}</dd>
              </div>
              <div>
                <dt>manifest</dt>
                <dd>{job.manifest_status || 'N/A'} / {job.manifest || 'N/A'}</dd>
              </div>
              <div>
                <dt>result</dt>
                <dd>{job.error || (job.returncode ? `returncode ${job.returncode}` : job.finished_at || 'N/A')}</dd>
              </div>
            </dl>

            <pre className="tp-log">{job.log_tail || '暂无日志摘要'}</pre>
          </div>
        </section>

        <section className="tp-dashboard-grid">
          <div className="tp-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">State API</p>
                <h2>系统概览</h2>
              </div>
              {refreshingState && <Loader2 className="tp-spin" size={20} />}
            </div>
            <div className="tp-signal-list">
              {dashboardState.overview.map((item) => (
                <div className="tp-signal-row" key={item.label}>
                  <span>{item.label}</span>
                  <strong>{cellText(item.value)}</strong>
                  <small>{cellText(item.note)}</small>
                </div>
              ))}
            </div>
          </div>

          <div className="tp-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Alerts</p>
                <h2>告警</h2>
              </div>
            </div>
            <div className="tp-alert-list">
              {dashboardState.alerts.slice(0, 6).map((alert, index) => (
                <div className="tp-alert-row" key={`${alert.模块}-${alert.对象}-${index}`}>
                  <StatusPill value={alert.级别 || alert.状态} />
                  <div>
                    <strong>{cellText(alert.模块)} / {cellText(alert.对象)}</strong>
                    <small>{cellText(alert.证据)}</small>
                  </div>
                </div>
              ))}
              {!dashboardState.alerts.length && <div className="tp-empty">暂无告警</div>}
            </div>
          </div>

          <div className="tp-panel tp-wide-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Queue stream</p>
                <h2>后台队列任务</h2>
              </div>
            </div>
            <DataTable columns={['job_id', '状态', 'step', '更新时间', 'backend']} rows={queueRows} />
          </div>

          <div className="tp-panel tp-wide-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Core database</p>
                <h2>核心数据库</h2>
              </div>
            </div>
            <DataTable columns={['数据资产', '更新状态', '最新日期', '行', 'Schema']} rows={dashboardState.core_database} />
          </div>

          <div className="tp-panel tp-wide-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Project assets</p>
                <h2>项目资产</h2>
              </div>
            </div>
            <DataTable
              columns={['项目', '资产状态', '注册资产', '自动发现', '必需缺失', '总大小', '最新更新时间']}
              rows={dashboardState.projects}
            />
          </div>

          <div className="tp-panel tp-wide-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Pipeline</p>
                <h2>Pipeline 状态</h2>
              </div>
            </div>
            <DataTable columns={['步骤', '状态', '最近完成', '未通过校验']} rows={dashboardState.pipeline} />
          </div>

          <div className="tp-panel tp-wide-panel">
            <div className="tp-panel-heading">
              <div>
                <p className="tp-kicker">Data assets</p>
                <h2>数据资产</h2>
              </div>
            </div>
            <DataTable
              columns={['项目', '数据/产物', '来源', '状态', '行', '大小', '更新时间']}
              limit={12}
              rows={dashboardState.assets}
            />
          </div>
        </section>

        <section className={`tp-toast is-${toast.tone || 'neutral'}`} aria-live="polite">
          <Server size={18} />
          <div>
            <strong>{toast.title}</strong>
            <span>{toast.detail}</span>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
