/* eslint-disable @typescript-eslint/no-explicit-any */

export function showDeviceContextMenu(
  evt: MouseEvent,
  deviceId: string,
  deps: {
    devices: any
    selection: any
    ctxStore: any
    toasts?: any
    redraw: () => void
  }
) {
  const { devices, selection, ctxStore, toasts, redraw } = deps
  evt.preventDefault()
  evt.stopPropagation()
  const dev = devices.devices.find((d: any) => d.id === deviceId)
  const multi = (selection.items as any[]).filter((i: any) => i.kind === 'device').map((i) => i.id)
  const selectionSet = new Set(multi)
  const PROVISIONABLE = new Set([
    'CORE_ROUTER',
    'EDGE_ROUTER',
    'OLT',
    'AON_SWITCH',
    'ONT',
    'BUSINESS_ONT',
    'AON_CPE'
  ])
  const provisionable = (id: string) => {
    const d: any = devices.devices.find((x: any) => x.id === id)
    if (!d) return false
    if (!PROVISIONABLE.has(d.type) || d.provisioned) return false
    if (['OLT', 'AON_SWITCH'].includes(d.type) && !(d as any).parent_container_id) return false
    return true
  }
  const provisionableIds = multi.filter(provisionable)
  const items: any[] = []
  const isContainer = (t: unknown) => t === 'POP' || t === 'CORE_SITE'
  items.push({
    id: 'start-link',
    label: 'Link von hier starten',
    disabled: !dev || isContainer(dev.type),
    reason: dev && isContainer(dev.type) ? 'Container kann kein Link-Startpunkt sein' : undefined,
    action: () => {
      if (dev)
        window.dispatchEvent(new CustomEvent('unoc:startLinkFrom', { detail: { id: dev.id } }))
    }
  })
  // Multi-link: use the current multi-selection as sources, then click a target
  const multiLinkSources = multi.filter((id) => {
    const d: any = devices.devices.find((x: any) => x.id === id)
    return d && !isContainer(d.type)
  })
  items.push({
    id: 'start-multi-link',
    label: `Multi-Link von Auswahl (${multiLinkSources.length})`,
    disabled: multiLinkSources.length < 2,
    reason: multiLinkSources.length < 2 ? 'Mindestens 2 Geräte auswählen' : undefined,
    action: () => {
      window.dispatchEvent(
        new CustomEvent('unoc:startMultiLink', { detail: { sources: multiLinkSources } })
      )
    }
  })
  items.push({
    id: 'provision-one',
    label: 'Provisionieren',
    disabled: !(dev && provisionable(dev.id)),
    action: () => devices.provision(dev.id)
  })
  items.push({
    id: 'provision-selected',
    label: `Provisioniere Auswahl (${provisionableIds.length})`,
    disabled: provisionableIds.length === 0,
    reason:
      multi.length && provisionableIds.length === 0 ? 'Keine provisionierbaren Geräte' : undefined,
    action: async () => {
      for (const id of provisionableIds) {
        try {
          await devices.provision(id)
        } catch (e) {
          console.warn('Provision failed', id, e)
        }
      }
    }
  })
  items.push({
    id: 'delete',
    label: multi.length > 1 ? `Lösche ${multi.length} Geräte` : 'Gerät löschen',
    disabled: false,
    action: async () => {
      const ids = multi.length ? multi : [deviceId]
      for (const id of ids) {
        try {
          await devices.remove(id)
        } catch (e) {
          console.warn('Delete failed', id, e)
        }
      }
      selection.clear()
    }
  })
  const selectionDevices = devices.devices.filter((d: any) => selectionSet.has(d.id))
  const pop: any = selectionDevices.find((d: any) => d.type === 'POP')
  const children = selectionDevices.filter((d: any) => ['OLT', 'AON_SWITCH'].includes(d.type))
  const parentAssignEligible = !!pop && children.length > 0
  items.push({
    id: 'assign-pop',
    label: 'POP als Parent zuweisen',
    disabled: !parentAssignEligible,
    reason: !parentAssignEligible ? 'Erfordert genau eine POP + Zielgeräte' : undefined,
    action: async () => {
      if (!pop) return
      let changed = 0
      for (const c of children) {
        if ((c as any).parent_container_id === pop.id) continue
        try {
          const updated = await devices.update(c.id, { parent_container_id: pop.id })
          const local = devices.devices.find((d: any) => d.id === updated.id)
          if (local) (local as any).parent_container_id = updated.parent_container_id
          changed++
        } catch (e) {
          console.warn('Parent assign failed', c.id, e)
        }
      }
      if (changed) toasts?.push?.(`${changed} Parent-Zuweisung(en) gespeichert`, 'info')
      redraw()
    }
  })
  ctxStore.show(evt.clientX, evt.clientY, items, { kind: 'device', id: deviceId })
}

export function showCanvasContextMenu(
  evt: MouseEvent,
  deps: {
    devices: any
    selection: any
    ctxStore: any
    forceLayout: () => void
    linkTool: { active: boolean; startDevice: string | null; hoverDevice: string | null }
    showParentTethers: { value: boolean }
    redraw: () => void
  }
) {
  const { devices, selection, ctxStore, forceLayout, linkTool, showParentTethers, redraw } = deps
  evt.preventDefault()
  evt.stopPropagation()
  const items: any[] = []
  const hasSelection = (selection.items || []).length > 0
  items.push({
    id: 'deselect-all',
    label: 'Auswahl aufheben',
    disabled: !hasSelection,
    action: () => selection.clear()
  })
  items.push({
    id: 'select-all-devices',
    label: 'Alle Geräte auswählen',
    disabled: (devices.devices || []).length === 0,
    action: () => {
      ;(devices.devices || []).forEach((d: any) => selection.select(d.id, 'device', true))
    }
  })
  items.push({
    id: 'auto-layout',
    label: 'Auto Layout (unpinned)',
    disabled: false,
    action: () => forceLayout()
  })
  items.push({
    id: 'toggle-link-tool',
    label: linkTool.active ? 'Link-Tool beenden' : 'Link-Tool starten',
    disabled: false,
    action: () => {
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
  })
  items.push({
    id: 'toggle-parent-tethers',
    label: showParentTethers.value ? 'Parent-Tethers ausblenden' : 'Parent-Tethers einblenden',
    disabled: false,
    action: () => {
      showParentTethers.value = !showParentTethers.value
      redraw()
    }
  })
  ctxStore.show(evt.clientX, evt.clientY, items, { kind: 'canvas', id: null })
}
