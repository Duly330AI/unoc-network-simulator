import { defineStore } from 'pinia'
import { eventBus, type EventEnvelope } from '../lib/eventBus.js'

export interface DeviceMetric {
  bps: number
  utilization: number // 0..inf (1.0 == 100%)
  version: number
  upstream_bps?: number
  downstream_bps?: number
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
          }>
          tick?: number
        }
        const items = payload.devices || []
        const tick = typeof payload.tick === 'number' ? payload.tick : this.lastTick
        // Apply version-checked updates into ONE clone per event (a clone per
        // item made this O(n²) per tick and was a real RAM/CPU hog at scale)
        let next: Record<string, DeviceMetric> | null = null
        for (const it of items) {
          if (!it || !it.id) continue
          const cur = this.byId[it.id]
          const incomingVersion =
            typeof it.version === 'number' ? it.version : (cur?.version ?? 0) + 1
          if (!cur || incomingVersion > cur.version) {
            if (!next) next = { ...this.byId }
            next[it.id] = {
              bps: it.bps,
              utilization: it.utilization,
              version: incomingVersion,
              upstream_bps: it.upstream_bps ?? cur?.upstream_bps,
              downstream_bps: it.downstream_bps ?? cur?.downstream_bps
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
        }
      >
      links?: Record<string, unknown>
      ports?: Record<string, Record<string, { bps: number; utilization: number; version?: number }>>
      lastTick: number
    }) {
      const next: Record<string, DeviceMetric> = {}
      for (const [id, m] of Object.entries(snapshot.devices || {})) {
        next[id] = {
          bps: m.bps,
          utilization: m.utilization,
          version: typeof m.version === 'number' ? m.version : 0,
          upstream_bps: m.upstream_bps,
          downstream_bps: m.downstream_bps
        }
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
