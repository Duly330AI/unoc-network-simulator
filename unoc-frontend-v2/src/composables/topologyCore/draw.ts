/* eslint-disable @typescript-eslint/no-explicit-any */
import * as d3 from 'd3'
import type { Device, LinkRecord, LayoutEntry, LinkToolState } from '../../types/topology.js'
import { layoutPositions, linkStatus, linkKind } from './utils.js'
import { useLinkMetricsStore } from '../../stores/linkMetricsStore.js'
import { decideLinkColor, computeDashForLength } from '../../logic/linkColor.js'
import { makeLinkClickHandler } from './handlers.js'
import { useTooltipStore } from '../../stores/tooltipStore.js'
import { drawContainers } from './render/containers.js'
import { drawNodes } from './render/nodes.js'
import { normalizeVisualStatus } from './status.js'

export function createRenderer(args: {
  svgRef: { value: SVGSVGElement | null }
  devices: any
  linksStore: any
  selection: any
  linkTool: LinkToolState
  getLayoutCache: () => Record<string, LayoutEntry>
  showParentTethers: { value: boolean }
  openDeviceContextMenu: (ev: MouseEvent, id: string) => void
  getPrepareDrag: () => ((ev: MouseEvent, id: string) => void) | undefined
  requestRedraw: () => void
  redrawSelection: () => void
}) {
  const {
    svgRef,
    devices,
    linksStore,
    selection,
    linkTool,
    getLayoutCache,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    showParentTethers,
    openDeviceContextMenu,
    getPrepareDrag,
    requestRedraw,
    redrawSelection
  } = args

  // metrics and signal rendering handled within cockpits now
  const linkMetrics = useLinkMetricsStore()
  const tooltip = useTooltipStore()

  // rAF-based flow animation for traffic-bearing links (decoupled from metrics tick)
  let __rafId: number | null = null
  let __lastTs = 0
  function __animate(ts: number) {
    // Pause when no SVG or when tab likely not visible
    if (
      !svgRef.value ||
      (typeof document !== 'undefined' && document.visibilityState === 'hidden')
    ) {
      __lastTs = ts
      __rafId = requestAnimationFrame(__animate)
      return
    }
    const dt = __lastTs ? (ts - __lastTs) / 1000 : 0
    __lastTs = ts
    try {
      const svg = d3.select(svgRef.value)
      const linksLayer = svg.select('g.links-layer')
      const all = linksLayer.selectAll('line.link')
      all.each(function (this: SVGLineElement, d: any) {
        const el = d3.select(this as SVGLineElement)
        // Animate whenever the element is flagged for animation (has utilization > 0)
        if (el.attr('data-animate') !== '1') {
          // Reset offset if previously set
          if ((this as SVGLineElement).style.strokeDashoffset)
            el.style('stroke-dashoffset', '0').attr('data-dashoffset', '0')
          return
        }
        // Speed based on utilization (px/sec). Cap to avoid absurd speeds.
        const util = linkMetrics.byId[d.id]?.utilization ?? 0
        const pxPerSec = 40 + Math.min(util, 2) * 160 // 40..360 px/s for util 0..2
        const prev = Number(el.attr('data-dashoffset') || '0')
        const next = (prev + pxPerSec * dt) % 10000
        el.attr('data-dashoffset', String(next)).style('stroke-dashoffset', String(next))
      })
    } catch {
      // ignore
    }
    __rafId = requestAnimationFrame(__animate)
  }
  if (typeof window !== 'undefined' && typeof requestAnimationFrame === 'function') {
    if (__rafId == null) __rafId = requestAnimationFrame(__animate)
  }

  function formatMbps(value: number): string {
    if (!Number.isFinite(value)) return '?'
    if (value >= 1000) {
      const gbps = value / 1000
      return `${Number.isInteger(gbps) ? gbps.toFixed(0) : gbps.toFixed(1)} Gbps`
    }
    return `${Math.round(value)} Mbps`
  }

  function formatLinkCapacity(metric: { bps?: number; capacity_mbps?: number } | undefined) {
    if (!metric || typeof metric.capacity_mbps !== 'number' || metric.capacity_mbps <= 0) {
      return ''
    }
    const trafficMbps = typeof metric.bps === 'number' ? metric.bps / 1_000_000 : 0
    return ` • ${formatMbps(trafficMbps)} / ${formatMbps(metric.capacity_mbps)}`
  }

  function redraw() {
    if (!svgRef.value) return
    const layoutCache = getLayoutCache()
    const svg = d3.select(svgRef.value)
    const linksLayer = svg.select('g.links-layer')
    const nodesLayer = svg.select('g.nodes-layer')
    const parentGroup = linksLayer.empty()
      ? svg
      : d3.select((linksLayer.node() as SVGGElement).parentNode as SVGGElement)
    let containersLayer = parentGroup.select('g.containers-layer')
    if (containersLayer.empty()) {
      containersLayer = parentGroup.insert('g', ':first-child').attr('class', 'containers-layer')
    }
    let preview = linksLayer.select('line.link-preview')
    if (
      linkTool.active &&
      linkTool.startDevice &&
      linkTool.hoverDevice &&
      linkTool.hoverDevice !== linkTool.startDevice
    ) {
      if (preview.empty())
        preview = linksLayer
          .append('line')
          .attr('class', 'link-preview')
          .attr('pointer-events', 'none')
      preview
        .attr('x1', layoutCache[linkTool.startDevice].x)
        .attr('y1', layoutCache[linkTool.startDevice].y)
        .attr('x2', layoutCache[linkTool.hoverDevice].x)
        .attr('y2', layoutCache[linkTool.hoverDevice].y)
    } else if (!preview.empty()) {
      preview.remove()
    }
    const data = devices.devices as Device[]
    const pos = layoutPositions(data.length)
    const oldCache = layoutCache
    // rebuild cache shallowly with persisted positions
    const newCache: Record<string, any> = {}
    data.forEach((d, i) => {
      const prev = oldCache[d.id]
      newCache[d.id] = prev
        ? { x: prev.x, y: prev.y, type: d.type, pinned: prev.pinned }
        : { x: pos[i].x, y: pos[i].y, type: d.type, pinned: false }
    })
    // swap back into caller cache by mutation
    Object.keys(oldCache).forEach((k) => delete (oldCache as any)[k])
    Object.entries(newCache).forEach(([k, v]) => ((oldCache as any)[k] = v))

    // Remove legacy dashed parent-child tethers (visual nesting replaces this metaphor)
    linksLayer.selectAll('line.parent-tether').remove()

    // Render containers via helper
    drawContainers({
      containersLayer,
      devices,
      linksStore,
      selection,
      linkTool,
      openDeviceContextMenu,
      getPrepareDrag,
      requestRedraw,
      redrawSelection,
      layoutCache: oldCache as any
    })

    // Node adornments (halos/rings/labels) are now rendered inside cockpits; no external halos.

    const linkData: LinkRecord[] = linksStore.links as LinkRecord[]
    const linkSel = linksLayer.selectAll('line.link').data(linkData as any, (d: LinkRecord) => d.id)
    linkSel.exit().remove()
    const linkEnter = linkSel
      .enter()
      .append('line')
      .attr('class', 'link')
      .attr('stroke-width', 2)
      .attr('stroke-linecap', 'round')
      .attr('pointer-events', 'stroke')
      .style('cursor', 'pointer')
      .on('click', makeLinkClickHandler(selection, redrawSelection))
      .on('mouseenter', function (this: SVGLineElement, ev: MouseEvent, d: LinkRecord) {
        // highlight hovered link
        d3.select(this).classed('hover', true)
        // Compose a friendly label from device names with fallback to ids
        const devs = (devices.devices || []) as Device[]
        const aName = devs.find((x) => x.id === d.a_device_id)?.name || d.a_device_id
        const bName = devs.find((x) => x.id === d.b_device_id)?.name || d.b_device_id
        // Metrics lookup with defensive fallback
        const m = linkMetrics.byId[d.id]
        const utilPct =
          m && typeof m.utilization === 'number' ? Math.round(m.utilization * 100) : null
        const utilText = utilPct === null ? '—' : `${utilPct}%`
        const capacityText = formatLinkCapacity(m)
        const congestedText = m?.congested ? ' • CONGESTED' : ''
        const content = `${aName} ↔ ${bName} • Util ${utilText}${capacityText}${congestedText}`
        tooltip.show(content, ev.clientX, ev.clientY)
      })
      .on('mousemove', function (this: SVGLineElement, ev: MouseEvent) {
        tooltip.move(ev.clientX, ev.clientY)
      })
      .on('mouseleave', function (this: SVGLineElement) {
        d3.select(this).classed('hover', false)
        tooltip.hide()
      })
    linkEnter
      .merge(linkSel as any)
      .each(function (this: SVGLineElement, d: any) {
        const ax = oldCache[d.a_device_id]?.x
        const ay = oldCache[d.a_device_id]?.y
        const bx = oldCache[d.b_device_id]?.x
        const by = oldCache[d.b_device_id]?.y
        // Guard: skip rendering if endpoints are missing or zero-length
        const invalid =
          ax == null || ay == null || bx == null || by == null || (ax === bx && ay === by)
        const sel = d3.select(this)
        if (invalid) {
          sel.attr('display', 'none')
          return
        }
        sel.attr('display', null).attr('x1', ax).attr('y1', ay).attr('x2', bx).attr('y2', by)
      })
      .attr('class', (d: any) => `link link-kind-${linkKind(d)} link-status-${linkStatus(d)}`)
      .each(function (this: SVGLineElement, d: any) {
        // Compute color via helper with precedence and overload flag
        const devs = (devices.devices || []) as Device[]
        const aDev = devs.find((x) => x.id === d.a_device_id)
        const bDev = devs.find((x) => x.id === d.b_device_id)
        const m = linkMetrics.byId[d.id]
        const { stroke: nextColor, overloaded } = decideLinkColor(aDev as any, bDev as any, m as any, {
          linkEffectiveStatus: d.effective_status || d.status,
          linkAdminOverride: d.admin_override_status
        })
        const width = linkKind(d) === 'backbone' ? 4 : 3
        // Smooth color/width transition
        d3.select(this)
          .classed('link-congested', overloaded)
          .attr('data-congested', overloaded ? '1' : '0')
          .transition()
          .duration(350)
          // Use inline styles so CSS rules won't override our computed color/width
          .style('stroke', nextColor as any)
          .style('stroke-width', String(width))
        // Flow animation: animate whenever utilization is positive and link is effectively up
        const util = (m && typeof m.utilization === 'number' ? m.utilization : 0) as number
        // Animation suppressed whenever effective_status (or fallback status) not strictly 'up'
        const effStatus = (d.effective_status || d.status || '').toLowerCase()
        const shouldAnimate = util > 0 && effStatus === 'up'
        if (shouldAnimate) {
          const length = Math.hypot(
            (oldCache[d.b_device_id]?.x || 0) - (oldCache[d.a_device_id]?.x || 0),
            (oldCache[d.b_device_id]?.y || 0) - (oldCache[d.a_device_id]?.y || 0)
          )
          const dash = computeDashForLength(length)
          d3.select(this)
            // Control dash pattern with inline style
            .style('stroke-dasharray', `${dash},${dash}`)
            .attr('data-animate', '1')
        } else {
          // Ensure solid line and disable animation flag
          d3.select(this).style('stroke-dasharray', 'none').attr('data-animate', '0')
        }
      })

    // Note: flow animation handled by rAF loop above

    // Render nodes via helper (handles mounting sub-apps and transforms)
    drawNodes({
      nodesLayer,
      devices,
      linksStore,
      selection,
      linkTool,
      openDeviceContextMenu,
      getPrepareDrag,
      requestRedraw,
      redrawSelection,
      layoutCache: oldCache as any,
      tooltip,
      normalizeVisualStatus
    })
    redrawSelection()
  }

  return { redraw }
}

// normalizeVisualStatus moved to status.ts
