import { useState } from 'react'

import { requestJson } from '../api/dashboardApi.js'
import {
  DEFAULT_PIPELINE_PAYLOAD,
  EMPTY_JOB,
} from '../domain/dashboardContracts.js'
export function useJobLauncher({ job, setConnection, setJob, setToast, subscribeToJob }) {
  const [pipelinePayload, setPipelinePayload] = useState(DEFAULT_PIPELINE_PAYLOAD)
  const [projectPayload, setProjectPayload] = useState({ project_id: '00_screen', mode: 'safe_check' })
  const [submitting, setSubmitting] = useState('')
  const isBusy = submitting !== '' || ['queued', 'running'].includes(job.status)

  const launchJob = async (kind) => {
    const targets = {
      checks: ['/api/dashboard/jobs/system-checks', {}, '全部项目检查', 'system_checks'],
      project: ['/api/dashboard/jobs/project', projectPayload, '子项目启动', `project:${projectPayload.project_id}:${projectPayload.mode}`],
      pipeline: ['/api/dashboard/jobs/pipeline', pipelinePayload, 'Pipeline 启动', pipelinePayload.step],
      regime: ['/api/dashboard/jobs/signals/regime', {}, 'Regime 刷新', 'signal:regime_risk_budget'],
      country: ['/api/dashboard/jobs/signals/country', {}, 'Country model 刷新', 'signal:country_model'],
    }
    const [endpoint, payload, label, pendingStep] = targets[kind]
    setSubmitting(kind)
    setConnection('submitting')
    setToast({ tone: 'info', title: `${label}已提交`, detail: '前端已立即接收点击，正在创建后台 job。' })
    setJob({
      ...EMPTY_JOB,
      job_id: 'pending',
      step: pendingStep,
      status: 'running',
      status_label: 'SUBMITTING',
      log_tail: '正在向后端提交 job...',
    })
    try {
      const result = await requestJson(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setJob(result.job)
      subscribeToJob(result.job.job_id)
      setToast({
        tone: 'good',
        title: `${label}已创建`,
        detail: `job_id ${result.job.job_id || 'N/A'} / PID ${result.job.pid || 'N/A'}`,
      })
    } catch (error) {
      setToast({ tone: 'bad', title: `${label}失败`, detail: error.message })
      setJob({ ...EMPTY_JOB, log_tail: error.message })
      setConnection('api')
    } finally {
      setSubmitting('')
    }
  }

  return {
    isBusy,
    launchJob,
    pipelinePayload,
    projectPayload,
    setPipelinePayload,
    setProjectPayload,
    submitting,
  }
}

