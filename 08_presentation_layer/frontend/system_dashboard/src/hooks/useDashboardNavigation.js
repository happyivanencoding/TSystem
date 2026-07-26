import { useEffect, useRef, useState } from 'react'

import {
  DEFAULT_MODULE_BY_PAGE,
  DEFAULT_MODULE_ORDER,
  DEFAULT_PAGE,
  loadModuleOrder,
  moveItem,
  parseDashboardRoute,
  saveModuleOrder,
} from '../domain/navigation.js'

export function useDashboardNavigation() {
  const [activePage, setActivePage] = useState(() => (
    typeof window === 'undefined'
      ? DEFAULT_PAGE
      : parseDashboardRoute(window.location.hash).page
  ))
  const [activeModule, setActiveModule] = useState(() => (
    typeof window === 'undefined'
      ? DEFAULT_MODULE_BY_PAGE[DEFAULT_PAGE]
      : parseDashboardRoute(window.location.hash).moduleId
  ))
  const [moduleOrder, setModuleOrder] = useState(loadModuleOrder)
  const dragModuleRef = useRef('')

  useEffect(() => {
    const onHashChange = () => {
      const route = parseDashboardRoute(window.location.hash)
      setActivePage(route.page)
      setActiveModule(route.moduleId)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  const changeModule = (page, moduleId) => {
    setActivePage(page)
    setActiveModule(moduleId)
    if (typeof window !== 'undefined') {
      window.location.hash = `${page}/${moduleId}`
    }
  }
  const changePage = (page) => {
    changeModule(page, DEFAULT_MODULE_BY_PAGE[page])
  }
  const reorderModules = (page, fromId, toId) => {
    setModuleOrder((current) => {
      const next = {
        ...current,
        [page]: moveItem(
          current[page] || DEFAULT_MODULE_ORDER[page],
          fromId,
          toId,
        ),
      }
      saveModuleOrder(next)
      return next
    })
  }
  const moduleDragProps = (page, id) => ({
    draggable: true,
    onDragStart: (event) => {
      dragModuleRef.current = id
      event.dataTransfer.effectAllowed = 'move'
      event.dataTransfer.setData('text/plain', id)
    },
    onDragOver: (event) => {
      event.preventDefault()
      event.dataTransfer.dropEffect = 'move'
    },
    onDrop: (event) => {
      event.preventDefault()
      reorderModules(
        page,
        event.dataTransfer.getData('text/plain') || dragModuleRef.current,
        id,
      )
    },
    style: {
      order: Math.max(
        0,
        (moduleOrder[page] || DEFAULT_MODULE_ORDER[page]).indexOf(id),
      ),
    },
    title: '拖动模块排序',
  })
  const panelClass = (page, id, extra = '') => [
    'tp-panel',
    extra,
    `tp-${page}-module`,
    activePage === page && activeModule === id ? 'is-active-module' : '',
  ].filter(Boolean).join(' ')

  return {
    activeModule,
    activePage,
    changeModule,
    changePage,
    moduleDragProps,
    panelClass,
  }
}
