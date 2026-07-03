/* Core logic extracted from TopologyCanvas.vue to reduce file size and improve modularity. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { ref, reactive } from 'vue'
import { useTooltipStore } from '../stores/tooltipStore.js'
/* d3 is used in helpers */
import type { Device, LayoutEntry, LinkToolState } from '../types/topology.js'
import { colorForType, ghostFill } from './topologyCore/utils.js'
import { createDragController } from './topologyCore/drag.js'
import {
  fastRefreshNodes as fastRefreshNodesHelper,
  redrawSelection as redrawSelectionHelper
} from './topologyCore/renderHelpers.js'
import { createRenderer } from './topologyCore/draw.js'
import { createSimulationController } from './topologyCore/simulation.js'
import { createUndoRedo } from './topologyCore/undoRedo.js'
import { applyZoom } from './topologyCore/zoom.js'
import { attachCanvasWatchers } from './topologyCore/watchers.js'
import { useLayoutStore } from '../stores/layoutStore.js'
import { createDropHandler } from './topologyCore/drop.js'

interface GhostDevice {
  localId: string
  x: number
  y: number
  type: string
  baseId: string
}

export interface TopologyCanvasDeps {
  svgRef: any
  zoomRoot: any
  ghostLayerRef: any
  devices: any
  linksStore: any
  selection: any
  toasts: any
  createLinkBetween?: (a: string, b: string) => Promise<void>
}

import { useContextMenuStore } from '../stores/contextMenuStore.js'
import { useDeletion } from './useDeletion.js'
import { showDeviceContextMenu, showCanvasContextMenu } from './topologyCore/contextMenus.js'

export function useTopologyCanvasCore(deps: TopologyCanvasDeps) {
  const deletion = useDeletion()
  // Context menu integration (device right-click)
  const ctxStore = useContextMenuStore()
  const openDeviceContextMenu = (evt: MouseEvent, deviceId: string) =>
    showDeviceContextMenu(evt, deviceId, {
      devices,
      selection,
      ctxStore,
      toasts,
      redraw
    })

  // Canvas background context menu (no specific target)
  const onCanvasContextMenu = (evt: MouseEvent) =>
    showCanvasContextMenu(evt, {
      devices,
      selection,
      ctxStore,
      forceLayout,
      linkTool,
      showParentTethers,
      redraw
    })

  const { svgRef, zoomRoot, devices, linksStore, selection, toasts } = deps
  const ghosts = reactive<GhostDevice[]>([])
  const linkTool = reactive<LinkToolState>({
    active: false,
    startDevice: null,
    hoverDevice: null,
    mode: 'single',
    sources: []
  })
  const showParentTethers = ref(false)

  // Drag handling moved to topologyCore/drag.ts
  let prepareDrag: (ev: MouseEvent, id: string) => void

  const layoutCache: Record<string, LayoutEntry> = {}

  // Undo/Redo via helper
  const { pushUndo, undoLayout, redoLayout, emitStacks } = createUndoRedo(
    () => layoutCache as any,
    (ids: string[]) => fastRefreshNodes(ids)
  )

  // Persist queue via helper
  const layoutStore = useLayoutStore()
  const queuePositions = (ids: string[]) => {
    ids.forEach((id) => {
      const l = (layoutCache as any)[id]
      if (l) layoutStore.markMoved(id, l.x, l.y, true)
    })
  }
  const attachFocusRetry = () => {
    if (typeof window !== 'undefined') {
      window.addEventListener('focus', () => {
        // Best-effort flush of any pending dirty positions
        layoutStore.flushNow().catch(() => {
          /* non-fatal */
        })
      })
    }
  }
  attachFocusRetry()
  const fastRefreshNodes = (ids: string[]) =>
    fastRefreshNodesHelper(svgRef as any, layoutCache as any, ids)
  const redrawSelection = () => redrawSelectionHelper(svgRef as any, selection)
  const renderer = createRenderer({
    svgRef: svgRef as any,
    devices,
    linksStore,
    selection,
    linkTool: linkTool as any,
    getLayoutCache: () => layoutCache as any,
    showParentTethers,
    openDeviceContextMenu,
    getPrepareDrag: () => prepareDrag,
    requestRedraw: () => redraw(),
    redrawSelection
  })
  const redraw = () => renderer.redraw()
  // Simulation controller
  const sim = createSimulationController({
    svgRef,
    devices,
    linksStore,
    layoutCache: layoutCache as any,
    fastRefreshNodes,
    queuePositions
  })
  function forceLayout() {
    sim.forceLayout()
  }

  const { onDrop } = createDropHandler(
    svgRef as any,
    () => layoutCache as any,
    devices,
    selection,
    ghosts as any,
    toasts,
    () => redraw(),
    (ids: string[]) => queuePositions(ids),
    (ids: string[]) => fastRefreshNodes(ids),
    (
      ctx: {
        type: string
        suggestedId: string
        screen: { x: number; y: number }
        graph: { x: number; y: number }
        parentId: string | null
      },
      confirm: (hardwareModelId: number | null) => Promise<void>,
      cancel: () => void
    ) => {
      // Broadcast an event so the canvas component can render the modal
      window.dispatchEvent(
        new CustomEvent('unoc:openHardwareSelector', { detail: { ctx, confirm, cancel } })
      )
    }
  )

  // dragMove/dragEnd handled inside drag controller

  function keyHandler(e: KeyboardEvent) {
    if (e.key === 'l' || e.key === 'L') {
      const devIds = selection.items.filter((i: any) => i.kind === 'device').map((i: any) => i.id)
      if (devIds.length === 2) {
        linksStore.createBetweenDevices(devIds[0], devIds[1]).then(() => redraw())
      }
    }
    if (e.key === 'Escape') {
      if (linkTool.active) {
        linkTool.startDevice = null
        linkTool.hoverDevice = null
        linkTool.active = false
        redraw()
        window.dispatchEvent(new CustomEvent('unoc:linkToolState', { detail: { active: false } }))
      } else {
        const onlyLinks =
          selection.items.length > 0 && selection.items.every((i: any) => i.kind === 'link')
        if (onlyLinks) {
          selection.clear()
          redrawSelection()
        }
      }
    }
    if (e.key === 'k' || e.key === 'K') {
      const selectedDevs = selection.items
        .filter((i: any) => i.kind === 'device')
        .map((i: any) => i.id)
      // Multi-Link Target Mode if more than one device is selected
      if (selectedDevs.length > 1) {
        linkTool.active = true
        linkTool.mode = 'multi'
        linkTool.sources = selectedDevs
        linkTool.startDevice = null
        linkTool.hoverDevice = null
        // UI feedback
        try {
          toasts.push(
            `Multi-Link Target Mode: ${selectedDevs.length} Quellen → Ziel klicken`,
            'info'
          )
        } catch {
          /* non-fatal toast */
        }
      } else {
        // Toggle normal single-link mode
        linkTool.active = !linkTool.active
        linkTool.mode = 'single'
        if (!linkTool.active) {
          linkTool.startDevice = null
          linkTool.hoverDevice = null
          linkTool.sources = []
        }
      }
      redraw()
      window.dispatchEvent(
        new CustomEvent('unoc:linkToolState', { detail: { active: linkTool.active } })
      )
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
      undoLayout()
      e.preventDefault()
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.shiftKey && e.key === 'Z'))) {
      redoLayout()
      e.preventDefault()
    }
    // 'p' toggled tethers previously; nesting replaces that metaphor
    if (e.key === 'Delete') {
      const devCount = selection.items.filter((i: any) => i.kind === 'device').length
      const linkCount = selection.items.filter((i: any) => i.kind === 'link').length
      if (devCount) {
        deletion.deleteSelectedDevices().then(() => {
          redraw()
          redrawSelection()
        })
      } else if (linkCount) {
        deletion.deleteSelectedLinks().then(() => {
          redraw()
          redrawSelection()
        })
      }
    }
  }

  // Named window-event handlers so destroy() can unregister every one of them.
  // Anonymous listeners accumulated across canvas remounts and leaked memory.
  const onLayoutUndo = () => undoLayout()
  const onLayoutRedo = () => redoLayout()
  const onForceLayout = () => forceLayout()
  const onToggleLinkTool = () => {
    linkTool.active = !linkTool.active
    if (!linkTool.active) {
      linkTool.startDevice = null
      linkTool.hoverDevice = null
    }
    redraw()
    window.dispatchEvent(
      new CustomEvent('unoc:linkToolState', { detail: { active: linkTool.active } })
    )
  }
  // Context menu: "Link von hier starten" → activate single-link mode with
  // the clicked device preselected as start endpoint.
  const onStartLinkFrom = (e: Event) => {
    const id = (e as CustomEvent<{ id?: string }>).detail?.id
    if (!id) return
    const dev = devices.devices.find((d: Device) => d.id === id)
    if (!dev || dev.type === 'POP' || dev.type === 'CORE_SITE') return
    linkTool.active = true
    linkTool.mode = 'single'
    linkTool.sources = []
    linkTool.startDevice = id
    linkTool.hoverDevice = null
    redraw()
    window.dispatchEvent(new CustomEvent('unoc:linkToolState', { detail: { active: true } }))
  }
  // Context menu: multi-link from current selection → activate multi target
  // mode (same behavior as pressing "K" with a multi-selection).
  const onStartMultiLink = (e: Event) => {
    const sources = ((e as CustomEvent<{ sources?: string[] }>).detail?.sources || []).filter(
      Boolean
    )
    if (sources.length < 2) return
    linkTool.active = true
    linkTool.mode = 'multi'
    linkTool.sources = sources
    linkTool.startDevice = null
    linkTool.hoverDevice = null
    try {
      toasts.push(`Multi-Link Target Mode: ${sources.length} Quellen → Ziel klicken`, 'info')
    } catch {
      /* non-fatal toast */
    }
    redraw()
    window.dispatchEvent(new CustomEvent('unoc:linkToolState', { detail: { active: true } }))
  }

  let detachWatchers: (() => void) | null = null

  function init() {
    // Store for tooltip interactions within canvas gestures
    const tooltip = useTooltipStore()
    Promise.all([devices.fetchAll(), linksStore.fetchAll()]).then(async () => {
      // Ensure layout store is hydrated (idempotent if already done at app startup)
      try {
        if (!Object.keys(layoutStore.byId).length) await layoutStore.hydrate()
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[TopologyCanvasCore] layoutStore hydrate failed', e)
      }
      // Seed local cache from store for known devices
      Object.values(layoutStore.byId).forEach((p: any) => {
        layoutCache[p.id] = {
          x: p.x,
          y: p.y,
          type: devices.devices.find((d: Device) => d.id === p.id)?.type || 'UNKNOWN',
          pinned: !!p.userPinned
        }
      })
      redraw()
      applyZoom(svgRef as any, zoomRoot as any, () => tooltip.hide())
      // Initialize drag controller once helpers are ready
      const ctrl = createDragController(
        () => layoutCache as any,
        selection,
        (ids: string[]) => pushUndo(ids),
        (ids: string[]) => queuePositions(ids),
        (ids: string[]) => fastRefreshNodes(ids),
        svgRef as any
      )
      prepareDrag = ctrl.prepareDrag
      window.addEventListener('keydown', keyHandler)
      window.addEventListener('unoc:layoutUndo', onLayoutUndo)
      window.addEventListener('unoc:layoutRedo', onLayoutRedo)
      window.addEventListener('unoc:forceLayout', onForceLayout)
      window.addEventListener('unoc:toggleLinkTool', onToggleLinkTool)
      window.addEventListener('unoc:startLinkFrom', onStartLinkFrom)
      window.addEventListener('unoc:startMultiLink', onStartMultiLink)
      emitStacks()
    })
    // Attach redraw watchers (returns a disposer for destroy())
    detachWatchers = attachCanvasWatchers(
      devices,
      linksStore,
      selection,
      () => redraw(),
      () => redrawSelection()
    )
  }

  // Debounced resize handling
  let resizeTimer: number | null = null
  function onResize() {
    if (resizeTimer) window.clearTimeout(resizeTimer)
    resizeTimer = window.setTimeout(() => {
      resizeTimer = null
      redraw()
    }, 140)
  }

  function destroy() {
    window.removeEventListener('keydown', keyHandler)
    window.removeEventListener('resize', onResize)
    window.removeEventListener('unoc:layoutUndo', onLayoutUndo)
    window.removeEventListener('unoc:layoutRedo', onLayoutRedo)
    window.removeEventListener('unoc:forceLayout', onForceLayout)
    window.removeEventListener('unoc:toggleLinkTool', onToggleLinkTool)
    window.removeEventListener('unoc:startLinkFrom', onStartLinkFrom)
    window.removeEventListener('unoc:startMultiLink', onStartMultiLink)
    if (detachWatchers) {
      detachWatchers()
      detachWatchers = null
    }
  }

  // Attach resize after init sets up DOM
  // Note: call once here so it's ready even if init is delayed
  if (typeof window !== 'undefined') window.addEventListener('resize', onResize)

  return {
    ghosts,
    linkTool,
    onDrop,
    forceLayout,
    ghostFill,
    colorForType,
    init,
    destroy,
    onCanvasContextMenu
  }
}
