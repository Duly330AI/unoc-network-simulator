import { defineStore } from 'pinia'
import { eventBus, type EventEnvelope } from '../lib/eventBus.js'

export interface LinkMetric {
  bps: number
  utilization: number
  version: number
  congested?: boolean
  capacity_mbps?: number
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
          }>
          tick?: number
        }
        const items = payload.links || []
        const tick = typeof payload.tick === 'number' ? payload.tick : this.lastTick
        // One clone per event, not per item (was O(n²) per tick)
        let next: Record<string, LinkMetric> | null = null
        for (const it of items) {
          if (!it || !it.id) continue
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
            next[it.id] = metric
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
        next[id] = metric
      }
      this.byId = next
      if (typeof js?.lastTick === 'number') this.lastTick = js.lastTick
    }
  }
})
