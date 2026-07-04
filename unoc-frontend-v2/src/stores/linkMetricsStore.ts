import { defineStore } from 'pinia'
import { eventBus, type EventEnvelope } from '../lib/eventBus.js'

export interface LinkMetric {
  bps: number
  utilization: number
  version: number
  congested?: boolean
  capacity_mbps?: number
  // B2 shaping: requested (pre-shaping) demand crossing the link; bps stays
  // delivered traffic.
  demand_up_bps?: number
  demand_down_bps?: number
}

interface State {
  byId: Record<string, LinkMetric>
  lastTick: number
}

export const useLinkMetricsStore = defineStore('linkMetrics', {
  state: (): State => ({ byId: {}, lastTick: 0 }),
  actions: {
    initRealtime() {
      eventBus.on<EventEnvelope>('linkMetricsUpdated', (env) => {
        if (import.meta.env?.DEV) {
          const payloadUnknown: unknown = env?.payload
          const lcount =
            payloadUnknown && typeof payloadUnknown === 'object' && 'links' in payloadUnknown
              ? Array.isArray((payloadUnknown as { links?: unknown[] }).links)
                ? ((payloadUnknown as { links?: unknown[] }).links as unknown[]).length
                : 0
              : 0
          const tickVal =
            payloadUnknown && typeof payloadUnknown === 'object' && 'tick' in payloadUnknown
              ? (payloadUnknown as { tick?: unknown }).tick
              : undefined
          // eslint-disable-next-line no-console
          console.debug('[linkMetricsStore] linkMetricsUpdated', { count: lcount, tick: tickVal })
        }
        const payload = (env?.payload || {}) as {
          links?: Array<{
            id: string
            bps: number
            utilization: number
            version?: number
            congested?: boolean
            capacity_mbps?: number
            demand_up_bps?: number
            demand_down_bps?: number
          }>
          tick?: number
          authoritative?: boolean
        }
        const items = payload.links || []
        const tick = typeof payload.tick === 'number' ? payload.tick : this.lastTick
        const authoritative = payload.authoritative === true
        // One clone per event, not per item (was O(n²) per tick)
        const incomingIds = new Set<string>()
        let next: Record<string, LinkMetric> | null = null
        for (const it of items) {
          if (!it || !it.id) continue
          incomingIds.add(it.id)
          const cur = this.byId[it.id]
          const incomingVersion =
            typeof it.version === 'number' ? it.version : (cur?.version ?? 0) + 1
          if (!cur || incomingVersion > cur.version) {
            if (!next) next = { ...this.byId }
            const metric: LinkMetric = {
              bps: it.bps,
              utilization: it.utilization,
              version: incomingVersion
            }
            const congested = it.congested ?? cur?.congested
            const capacityMbps = it.capacity_mbps ?? cur?.capacity_mbps
            if (typeof congested === 'boolean') metric.congested = congested
            if (typeof capacityMbps === 'number') metric.capacity_mbps = capacityMbps
            const demandUp = it.demand_up_bps ?? cur?.demand_up_bps
            const demandDown = it.demand_down_bps ?? cur?.demand_down_bps
            if (typeof demandUp === 'number') metric.demand_up_bps = demandUp
            if (typeof demandDown === 'number') metric.demand_down_bps = demandDown
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
    applySnapshot(js: {
      links?: Record<
        string,
        {
          bps: number
          utilization: number
          version?: number
          congested?: boolean
          capacity_mbps?: number
          demand_up_bps?: number
          demand_down_bps?: number
        }
      >
      lastTick?: number
    }) {
      const incoming = js?.links || {}
      const next: Record<string, LinkMetric> = {}
      for (const [id, m] of Object.entries(incoming)) {
        if (!id || !m) continue
        const metric: LinkMetric = {
          bps: m.bps,
          utilization: m.utilization,
          version: m.version ?? 0
        }
        if (typeof m.congested === 'boolean') metric.congested = m.congested
        if (typeof m.capacity_mbps === 'number') metric.capacity_mbps = m.capacity_mbps
        if (typeof m.demand_up_bps === 'number') metric.demand_up_bps = m.demand_up_bps
        if (typeof m.demand_down_bps === 'number') metric.demand_down_bps = m.demand_down_bps
        next[id] = metric
      }
      this.byId = next
      if (typeof js?.lastTick === 'number') this.lastTick = js.lastTick
    }
  }
})
