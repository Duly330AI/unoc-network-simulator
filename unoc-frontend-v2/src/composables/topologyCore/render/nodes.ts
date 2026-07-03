import { createApp, h, type Component } from 'vue'
import type { Device, LayoutEntry, LinkToolState } from '../../../types/topology.js'
import { pinia } from '../../../stores/pinia.js'
import BaseCockpit from '../../../components/cockpits/BaseCockpit.vue'
import RouterCockpit from '../../../components/cockpits/RouterCockpit.vue'
import ONTCockpit from '../../../components/cockpits/ONTCockpit.vue'
import AONCPECockpit from '../../../components/cockpits/AONCPECockpit.vue'
import OLTCockpit from '../../../components/cockpits/OLTCockpit.vue'
import AONSwitchCockpit from '../../../components/cockpits/AONSwitchCockpit.vue'
import PassiveCockpit from '../../../components/cockpits/PassiveCockpit.vue'
import BackboneGatewayCockpit from '../../../components/cockpits/BackboneGatewayCockpit.vue'
import { makeDeviceClickHandler } from '../handlers.js'
import { getContainerLayout } from '../../../config/containerLayouts.js'
import { useMetricsStore } from '../../../stores/metricsStore.js'

export function drawNodes(options: {
  nodesLayer: unknown
  devices: { devices: Device[] }
  linksStore: unknown
  selection: unknown
  linkTool: LinkToolState
  openDeviceContextMenu: (ev: MouseEvent, id: string) => void
  getPrepareDrag: () => ((ev: MouseEvent, id: string) => void) | undefined
  requestRedraw: () => void
  redrawSelection: () => void
  layoutCache: Record<string, LayoutEntry & { pinned?: boolean; type?: string }>
  tooltip: {
    show: (t: string, x: number, y: number) => void
    move: (x: number, y: number) => void
    hide: () => void
  }
  normalizeVisualStatus: (raw: unknown) => string
}) {
  const {
    nodesLayer,
    devices,
    linksStore,
    selection,
    linkTool,
    openDeviceContextMenu,
    getPrepareDrag,
    requestRedraw,
    redrawSelection,
    layoutCache,
    tooltip,
    normalizeVisualStatus
  } = options
  const metrics = useMetricsStore()

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nodeGroups = (nodesLayer as any)
    .selectAll('g.device-node')
    .data(
      (devices.devices as Array<Pick<Device, 'id' | 'type' | 'name'>>).filter(
        (d) => d.type !== 'POP' && d.type !== 'CORE_SITE'
      ) as unknown,
      (d: Device) => d.id
    )

  nodeGroups
    .exit()
    .each(function (this: SVGGElement) {
      const app = (
        this as unknown as {
          __cockpit_app__?: { unmount?: () => void }
        }
      ).__cockpit_app__
      if (app?.unmount) {
        try {
          if (import.meta.env.DEV) {
            // eslint-disable-next-line no-console
            console.debug(
              '[cockpit] unmount sub-app for',
              (this as unknown as { __cockpit_id__?: string }).__cockpit_id__
            )
          }
          app.unmount()
        } catch {
          /* noop */
        }
      }
    })
    .remove()

  const nodeGroupsEnter = nodeGroups
    .enter()
    .append('g')
    .attr('class', 'device-node')
    .attr('data-pinned', '0')
    .attr('data-device-id', (d: Device) => d.id)
    .attr('data-status', (d: Device) => {
      type DeviceMaybeStatus = Device & { effective_status?: string; status?: string }
      const ds = d as DeviceMaybeStatus
      return ds.effective_status || ds.status || 'UNKNOWN'
    })
    .style('cursor', 'pointer')
    .style('pointer-events', 'all')
    .each(function (this: SVGGElement, d: Device) {
      const mountId = `cockpit-${d.id}`
      let mount = this.querySelector(`#${CSS.escape(mountId)}`)
      if (!mount) {
        mount = document.createElementNS('http://www.w3.org/2000/svg', 'g')
        mount.setAttribute('id', mountId)
        mount.setAttribute('class', 'cockpit-root')
        this.appendChild(mount)
        const Comp: Component =
          d.type === 'BACKBONE_GATEWAY'
            ? BackboneGatewayCockpit
            : d.type === 'CORE_ROUTER' || d.type === 'EDGE_ROUTER'
              ? RouterCockpit
              : d.type === 'OLT'
                ? OLTCockpit
                : d.type === 'AON_SWITCH'
                  ? AONSwitchCockpit
                  : d.type === 'ONT' || d.type === 'BUSINESS_ONT'
                    ? ONTCockpit
                    : d.type === 'AON_CPE'
                      ? AONCPECockpit
                      : d.type === 'ODF' ||
                          d.type === 'NVT' ||
                          d.type === 'SPLITTER' ||
                          d.type === 'HOP'
                        ? PassiveCockpit
                        : (BaseCockpit as unknown as Component)
        // eslint-disable-next-line vue/one-component-per-file
        const app = createApp({
          render: () => h(Comp, { deviceId: d.id } as Record<string, unknown>)
        })
        app.use(pinia)
        app.mount(mount)
        ;(this as unknown as { __cockpit_app__?: unknown }).__cockpit_app__ = app
        ;(this as unknown as { __cockpit_id__?: string }).__cockpit_id__ = d.id
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.debug('[cockpit] mounted sub-app for', d.id)
        }
      }
    })
    .on(
      'click',
      makeDeviceClickHandler(
        linkTool,
        devices,
        linksStore,
        selection,
        requestRedraw,
        redrawSelection
      ) as unknown as (this: SVGGElement, ev: MouseEvent, d: Device) => void
    )
    .on('contextmenu', (ev: MouseEvent, d: Device) => {
      openDeviceContextMenu(ev, d.id)
    })
    .on('mousedown', (ev: MouseEvent, d: Device) => {
      const fn = getPrepareDrag()
      if (fn) fn(ev, d.id)
    })
    .on('mouseenter', (ev: MouseEvent, d: Device) => {
      if (linkTool.active && linkTool.startDevice && d.id !== linkTool.startDevice) {
        if (d.type === 'POP') return
        linkTool.hoverDevice = d.id
        requestRedraw()
      }
      const content = `${d.name} (${d.type})`
      tooltip.show(content, ev.clientX, ev.clientY)
    })
    .on('mousemove', (ev: MouseEvent) => {
      tooltip.move(ev.clientX, ev.clientY)
    })
    .on('mouseleave', (_ev: MouseEvent, d: Device) => {
      if (linkTool.active && linkTool.hoverDevice === d.id) {
        linkTool.hoverDevice = null
        requestRedraw()
      }
      tooltip.hide()
    })

  const assignedSlotsByParent: Record<string, Set<string>> = {}
  nodeGroupsEnter
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .merge(nodeGroups as any)
    .attr('data-device-id', (d: Device) => d.id)
    .attr('transform', (d: Device) => {
      const lc = layoutCache[d.id]
      type DeviceWithSlot = Device & { parent_container_id?: string; slot_id?: string }
      const parentId = (d as DeviceWithSlot).parent_container_id
      if (parentId && layoutCache[parentId]) {
        const parentType = layoutCache[parentId].type
        const layout = getContainerLayout(parentType)
        if (layout) {
          const slotId = (d as DeviceWithSlot).slot_id
          type SlotLike = { id: unknown; x: number; y: number }
          const slots = layout.slots as Array<SlotLike>
          let slot = (slotId && slots.find((s) => s.id === slotId)) || null
          if (!slot) {
            const children = (devices.devices as Device[]).filter(
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              (x) => (x as any).parent_container_id === parentId
            )
            const occupied = new Set<string>(
              (children as Array<DeviceWithSlot>)
                .map((c) => c.slot_id)
                .filter((sid): sid is string => typeof sid === 'string' && sid.length > 0)
            )
            const usedNow = (assignedSlotsByParent[parentId] ||= new Set<string>())
            const free = slots.find(
              (s) => !occupied.has(String(s.id)) && !usedNow.has(String(s.id))
            )
            if (free) {
              slot = free
              usedNow.add(String(free.id))
            } else {
              const idx = Math.max(
                0,
                children.findIndex((x) => x.id === d.id)
              )
              slot = slots[idx % slots.length]
            }
          }
          const px = layoutCache[parentId].x - layout.size.width / 2 + layout.slotOffset.x + slot.x
          const py = layoutCache[parentId].y - layout.size.height / 2 + layout.slotOffset.y + slot.y
          if (lc) {
            lc.x = px
            lc.y = py
          }
          return `translate(${px},${py})`
        }
      }
      return `translate(${lc.x},${lc.y})`
    })
    .attr('data-container', (d: Device) => (d.type === 'POP' ? '1' : '0'))
    .attr('data-pinned', (d: Device) => (layoutCache[d.id].pinned ? '1' : '0'))
    .attr('data-congested', (d: Device) => (metrics.byId[d.id]?.congested ? '1' : '0'))
    .attr(
      'data-status',
      (d: Device) =>
        ((d as Device & { effective_status?: string; status?: string }).effective_status &&
          normalizeVisualStatus(
            (d as Device & { effective_status?: string }).effective_status as unknown as string
          )) ||
        ((d as Device & { status?: string }).status &&
          normalizeVisualStatus((d as Device & { status?: string }).status as unknown as string)) ||
        'UNKNOWN'
    )
}
