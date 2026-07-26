const MODULE_ORDER_STORAGE_KEY = 'tp-dashboard-module-order-v1'

export const DEFAULT_MODULE_ORDER = {
  market: ['brief'],
  production: ['overview', 'alerts', 'run-control', 'live-job', 'queue', 'core-database', 'project-assets', 'pipeline-status', 'data-assets'],
  results: ['regime', 'country', 'sector', 'score-ml', 'factor-explorer'],
  technical: ['latest'],
}

export const NAV_SECTIONS = [
  {
    page: 'market',
    label: '市场概况',
    description: '最新市场讯息',
    modules: [['brief', '市场概况', '欧美金融市场日内复盘']],
  },
  {
    page: 'results',
    label: '结果展示',
    description: '模型、信号和组合结果',
    modules: [
      ['regime', 'Regime', '市场状态识别'],
      ['country', 'Country', '国家与区域评分'],
      ['sector', 'Sector', '行业推荐'],
      ['score-ml', 'Score ML', '组合成分对比'],
      ['factor-explorer', '因子研究', '四市场收益、ratio、经济含义与稳健性证据'],
    ],
  },
  {
    page: 'technical',
    label: '技术面',
    description: '最新 Technical metrics',
    modules: [['latest', 'Technical', '按市场查看最新技术面']],
  },
  {
    page: 'production',
    label: '生产流程',
    description: '系统运行、队列、资产和 pipeline',
    modules: [
      ['overview', '总览', '状态快照与核心指标'],
      ['alerts', '告警', '生产健康信号'],
      ['run-control', '启动任务', '运行 pipeline 与检查'],
      ['live-job', '实时任务', '当前 job 与日志'],
      ['queue', '任务队列', '后台队列任务'],
      ['core-database', '核心数据库', '数据资产质量'],
      ['project-assets', '项目资产', '项目产物覆盖'],
      ['pipeline-status', 'Pipeline 状态', '步骤完成情况'],
      ['data-assets', '数据资产', '注册与发现资产'],
    ],
  },
]

export const DEFAULT_MODULE_BY_PAGE = Object.fromEntries(
  NAV_SECTIONS.map((section) => [section.page, section.modules[0][0]]),
)
export const MODULE_PAGE = Object.fromEntries(
  NAV_SECTIONS.flatMap((section) => section.modules.map(([id]) => [id, section.page])),
)
export const DEFAULT_PAGE = NAV_SECTIONS[0].page

export function parseDashboardRoute(hash = '') {
  const [rawPage, rawModule] = hash.replace(/^#/, '').split('/')
  const page = NAV_SECTIONS.some((section) => section.page === rawPage)
    ? rawPage
    : MODULE_PAGE[rawModule] || DEFAULT_PAGE
  const moduleId = MODULE_PAGE[rawModule] === page
    ? rawModule
    : DEFAULT_MODULE_BY_PAGE[page]
  return { page, moduleId }
}

export function mergeModuleOrder(savedOrder, defaultOrder) {
  if (!Array.isArray(savedOrder)) return defaultOrder
  const known = savedOrder.filter((item) => defaultOrder.includes(item))
  return [...known, ...defaultOrder.filter((item) => !known.includes(item))]
}

export function loadModuleOrder() {
  if (typeof window === 'undefined') return DEFAULT_MODULE_ORDER
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(MODULE_ORDER_STORAGE_KEY) || '{}',
    )
    return Object.fromEntries(
      NAV_SECTIONS.map((section) => [
        section.page,
        mergeModuleOrder(
          parsed[section.page],
          DEFAULT_MODULE_ORDER[section.page],
        ),
      ]),
    )
  } catch {
    return DEFAULT_MODULE_ORDER
  }
}

export function saveModuleOrder(order) {
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(
      MODULE_ORDER_STORAGE_KEY,
      JSON.stringify(order),
    )
  }
}

export function moveItem(items, fromId, toId) {
  if (!fromId || !toId || fromId === toId) return items
  const next = [...items]
  const fromIndex = next.indexOf(fromId)
  const toIndex = next.indexOf(toId)
  if (fromIndex < 0 || toIndex < 0) return items
  next.splice(fromIndex, 1)
  next.splice(toIndex, 0, fromId)
  return next
}
