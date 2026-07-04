import { defineStore } from 'pinia'
import { eventBus, type EventEnvelope } from '../lib/eventBus.js'

export interface DeviceMetric {
  bps: number
  utilization: number // 0..inf (1.0 == 100%)
  version: number
  upstream_bps?: number
  downstream_bps?: number
  congested?: boolean
  capacity_mbps?: number
  // B2 shaping: requested (pre-shaping) demand, applied scales and throttled
  // marker. bps/upstream_bps/downstream_bps remain delivered traffic.
  demand_up_bps?: number
  demand_down_bps?: number
  scale_up?: number
  scale_down?: number
  throttled?: boolean
}

export interface InterfaceMetric {
  bps: number
  utilization: number
  version: number
}

interface State {
  byId: Record<string, DeviceMetric>
  lastTick: number
  portsByDevice: Record<string, Record<string, InterfaceMetric>>
}

export const useMetricsStore = defineStore('metrics', {
  state: (): State => ({ byId: {}, lastTick: 0, portsByDevice: {} }),
  actions: {
    initRealtime() {
      eventBus.on<EventEnvelope>('deviceMetricsUpdated', (env) => {
        if (import.meta.env?.DEV) {
          const payloadUnknown: unknown = env?.payload
          const dcount =
            payloadUnknown && typeof payloadUnknown === 'object' && 'devices' in payloadUnknown
              ? Array.isArray((payloadUnknown as { devices?: unknown[] }).devices)
                ? ((payloadUnknown as { devices?: unknown[] }).devices as unknown[]).length
                : 0
              : 0
          const tickVal =
            payloadUnknown && typeof payloadUnknown === 'object' && 'tick' in payloadUnknown
              ? (payloadUnknown as { tick?: unknown }).tick
              : undefined
          // eslint-disable-next-line no-console
          console.debug('[metricsStore] deviceMetricsUpdated', { count: dcount, tick: tickVal })
        }
        const payload = (env?.payload || {}) as {
          devices?: Array<{
            id: string
            bps: number
            utilization: number
            version?: number
            upstream_bps?: number
            downstream_bps?: number
            congested?: boolean
            capacity_mbps?: number
            demand_up_bps?: number
            demand_down_bps?: number
            scale_up?: number
            scale_down?: number
            throttled?: boolean
          }>
          tick?: number
          authoritative?: boolean
        }
        const items = payload.devices || []
        const tick = typeof payload.tick === 'number' ? payload.tick : this.lastTick
        const authoritative = payload.authoritative === true
        // Apply version-checked updates into ONE clone per event (a clone per
        // item made this O(n²) per tick and was a real RAM/CPU hog at scale)
        const incomingIds = new Set<string>()
        let next: Record<string, DeviceMetric> | null = null
        for (const it of items) {
          if (!it || !it.id) continue
          incomingIds.add(it.id)
          const cur = this.byId[it.id]
          const incomingVersion =
            typeof it.version === 'number' ? it.version : (cur?.version ?? 0) + 1
          if (!cur || incomingVersion > cur.version) {
            if (!next) next = { ...this.byId }
            const metric: DeviceMetric = {
              bps: it.bps,
              utilization: it.utilization,
              version: incomingVersion,
              upstream_bps: it.upstream_bps ?? cur?.upstream_bps,
              downstream_bps: it.downstream_bps ?? cur?.downstream_bps
            }
            const congested = it.congested ?? cur?.congested
            const capacityMbps = it.capacity_mbps ?? cur?.capacity_mbps
            if (typeof congested === 'boolean') metric.congested = congested
            if (typeof capacityMbps === 'number') metric.capacity_mbps = capacityMbps
            const demandUp = it.demand_up_bps ?? cur?.demand_up_bps
            const demandDown = it.demand_down_bps ?? cur?.demand_down_bps
            const scaleUp = it.scale_up ?? cur?.scale_up
            const scaleDown = it.scale_down ?? cur?.scale_down
            const throttled = it.throttled ?? cur?.throttled
            if (typeof demandUp === 'number') metric.demand_up_bps = demandUp
            if (typeof demandDown === 'number') metric.demand_down_bps = demandDown
            if (typeof scaleUp === 'number') metric.scale_up = scaleUp
            if (typeof scaleDown === 'number') metric.scale_down = scaleDown
            if (typeof throttled === 'boolean') metric.throttled = throttled
            next[it.id] = metric
          }
        }
        if (authoritative) {
          for (const id of Object.keys(this.byId)) {
            if (!incomingIds.has(id)) {
              if (!next) next = { ...this.byId }
              delete next[id]
            }
          }
        }
        if (next) this.byId = next
        this.lastTick = tick
      })
    },
    // Replace full snapshot
    applySnapshot(snapshot: {
      devices: Record<
        string,
        {
          bps: number
          utilization: number
          version?: number
          upstream_bps?: number
          downstream_bps?: number
          congested?: boolean
          capacity_mbps?: number
          demand_up_bps?: number
          demand_down_bps?: number
          scale_up?: number
          scale_down?: number
          throttled?: boolean
        }
      >
      links?: Record<string, unknown>
      ports?: Record<string, Record<string, { bps: number; utilization: number; version?: number }>>
      lastTick: number
    }) {
      const next: Record<string, DeviceMetric> = {}
      for (const [id, m] of Object.entries(snapshot.devices || {})) {
        const metric: DeviceMetric = {
          bps: m.bps,
          utilization: m.utilization,
          version: typeof m.version === 'number' ? m.version : 0,
          upstream_bps: m.upstream_bps,
          downstream_bps: m.downstream_bps
        }
        if (typeof m.congested === 'boolean') metric.congested = m.congested
        if (typeof m.capacity_mbps === 'number') metric.capacity_mbps = m.capacity_mbps
        if (typeof m.demand_up_bps === 'number') metric.demand_up_bps = m.demand_up_bps
        if (typeof m.demand_down_bps === 'number') metric.demand_down_bps = m.demand_down_bps
        if (typeof m.scale_up === 'number') metric.scale_up = m.scale_up
        if (typeof m.scale_down === 'number') metric.scale_down = m.scale_down
        if (typeof m.throttled === 'boolean') metric.throttled = m.throttled
        next[id] = metric
      }
      this.byId = next
      this.lastTick = snapshot.lastTick ?? 0
      this.portsByDevice = {}
      if (snapshot.ports && typeof snapshot.ports === 'object') {
        for (const [devId, ports] of Object.entries(snapshot.ports)) {
          const portMap: Record<string, InterfaceMetric> = {}
          for (const [ifId, pm] of Object.entries(ports || {})) {
            portMap[ifId] = {
              bps: pm.bps,
              utilization: pm.utilization,
              version: typeof pm.version === 'number' ? pm.version : 0
            }
          }
          this.portsByDevice[devId] = portMap
        }
      }
    }
  }
})
