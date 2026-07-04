/* eslint-disable @typescript-eslint/no-explicit-any */
import type { LinkToolState } from '../../types/topology.js'

export function makeLinkClickHandler(selection: any, redrawSelection: () => void) {
  return (ev: MouseEvent, d: any) => {
    ev.stopPropagation()
    const multi = (ev as any).shiftKey || (ev as any).ctrlKey || (ev as any).metaKey
    selection.toggle(d.id, 'link', multi)
    redrawSelection()
  }
}

export function makeDeviceClickHandler(
  linkTool: LinkToolState,
  devices: any,
  linksStore: any,
  selection: any,
  redraw: () => void,
  redrawSelection: () => void
) {
  return async (event: MouseEvent, d: any) => {
    event.stopPropagation()
    // New: Multi-Link Target Mode
    if (linkTool.active && linkTool.mode === 'multi') {
      if ((d as any).type === 'POP') return
      const sources = (linkTool.sources || []).filter((id) => id !== d.id)
      if (!sources.length) return
      // Client-side eligibility: disallow ONT↔ONT and POP endpoints quickly
      const devs = devices.devices as any[]
      const getType = (id: string) => devs.find((x) => x.id === id)?.type || 'UNKNOWN'
      const targetType = (d as any).type
      const eligible = sources.filter((sid) => {
        const st = getType(sid)
        if (st === 'POP' || targetType === 'POP') return false
        // quick invalid peer rule: ONT/BUSINESS_ONT cannot link to ONT/BUSINESS_ONT
        const ontSet = new Set(['ONT', 'BUSINESS_ONT'])
        if (ontSet.has(st) && ontSet.has(targetType)) return false
        return true
      })
      if (!eligible.length) {
        try {
          ;(devices as any).toasts?.push?.('Keine gültigen Quellen für dieses Ziel', 'warn')
        } catch {
          /* toast optional */
        }
        // Exit multi-mode but keep selection
        linkTool.active = false
        linkTool.mode = 'single'
        linkTool.sources = []
        redraw()
        return
      }
      // Progress toast
      let toastId: string | null = null
      try {
        toastId = (devices as any).toasts?.pending?.(`Erstelle ${eligible.length} Links…`) ?? null
      } catch {
        /* toast optional */
      }
      // Single batch request: one transaction + one recompute pass on the backend
      let ok = 0
      let fail = 0
      try {
        const res = await linksStore.createManyToOne(eligible, d.id)
        ok = res?.ok ?? 0
        fail = res?.fail ?? 0
        if (fail && Array.isArray(res?.errors) && res.errors.length) {
          console.warn('[multiLink] batch errors:', res.errors)
        }
      } catch (e) {
        fail = eligible.length
        console.warn('[multiLink] batch create failed', e)
      }
      if (toastId) {
        try {
          const mgr = (devices as any).toasts
          if (mgr?.replace)
            mgr.replace(
              toastId,
              `${ok} erstellt, ${fail} fehlgeschlagen`,
              fail ? 'warn' : 'success'
            )
        } catch {
          /* toast optional */
        }
      }
      // Exit mode after one batch
      linkTool.active = false
      linkTool.mode = 'single'
      linkTool.sources = []
      redraw()
      return
    }
    if (linkTool.active) {
      if (!linkTool.startDevice) {
        // Do not allow containers as starting endpoint
        if (d.type === 'POP' || d.type === 'CORE_SITE') return
        linkTool.startDevice = d.id
        linkTool.hoverDevice = null
        redraw()
        return
      }
      if (linkTool.startDevice && d.id !== linkTool.startDevice) {
        const startDev = (devices.devices as any[]).find(
          (dd: any) => dd.id === linkTool.startDevice
        )
        if (startDev?.type === 'POP' || startDev?.type === 'CORE_SITE') {
          linkTool.startDevice = null
          linkTool.hoverDevice = null
          redraw()
          return
        }
        // If target is a container (POP/CORE_SITE), open proxy modal to pick internal child
        if (d.type === 'POP' || d.type === 'CORE_SITE') {
          const containerId = d.id
          const sourceId = linkTool.startDevice
          const devs = devices.devices as any[]
          const kids = devs.filter((x) => x.parent_container_id === containerId)
          // Filter invalid pairs quickly (ONT↔ONT disallowed; exclude containers)
          const ontSet = new Set(['ONT', 'BUSINESS_ONT'])
          const srcType = devs.find((x) => x.id === sourceId)?.type
          const candidates = kids.filter((k) => {
            if (!k || !k.id || !k.type) return false
            if (k.type === 'POP' || k.type === 'CORE_SITE') return false
            if (ontSet.has(k.type) && ontSet.has(srcType)) return false
            return true
          })
          if (!candidates.length) {
            try {
              ;(devices as any).toasts?.push?.('Keine gültigen Ziele im Container', 'warn')
            } catch {
              /* toast optional */
            }
            linkTool.startDevice = null
            linkTool.hoverDevice = null
            redraw()
            return
          }
          const confirm = async (targetId: string | null) => {
            if (!targetId) return
            await linksStore.createBetweenDevices(sourceId, targetId, { headless: !event.altKey })
          }
          const cancel = () => {
            /* no-op */
          }
          window.dispatchEvent(
            new CustomEvent('unoc:openLinkProxySelector', {
              detail: {
                sourceId,
                containerId,
                candidates: candidates.map((c) => ({
                  id: c.id,
                  label: `${c.name || c.id} (${c.type})`
                })),
                preselectId: candidates[0]?.id || null,
                confirm,
                cancel
              }
            })
          )
          // Keep tool active until modal responds; reset selection now for clarity
          linkTool.startDevice = null
          linkTool.hoverDevice = null
          redraw()
          return
        }
        await linksStore.createBetweenDevices(linkTool.startDevice, d.id, {
          headless: !event.altKey
        })
        linkTool.startDevice = null
        linkTool.hoverDevice = null
        redraw()
        return
      }
      if (linkTool.startDevice === d.id) {
        linkTool.startDevice = null
        linkTool.hoverDevice = null
        redraw()
        return
      }
    }
    const multi = (event as any).shiftKey || (event as any).ctrlKey || (event as any).metaKey
    selection.toggle(d.id, 'device', multi)
    redrawSelection()
  }
}
