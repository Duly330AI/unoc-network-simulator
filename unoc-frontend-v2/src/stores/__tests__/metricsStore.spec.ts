import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { eventBus } from '../../lib/eventBus.js'
import { useMetricsStore } from '../metricsStore.js'

describe('metricsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initial state', () => {
    const s = useMetricsStore()
    expect(s.byId).toEqual({})
    expect(s.lastTick).toBe(0)
  })

  it('snapshot replaces state', () => {
    const s = useMetricsStore()
    s.applySnapshot({
      devices: { A: { bps: 10, utilization: 0.1 }, B: { bps: 20, utilization: 0.2, version: 5 } },
      lastTick: 7
    })
    expect(Object.keys(s.byId)).toEqual(['A', 'B'])
    expect(s.byId.A).toEqual({ bps: 10, utilization: 0.1, version: 0 })
    expect(s.byId.B).toEqual({ bps: 20, utilization: 0.2, version: 5 })
    expect(s.lastTick).toBe(7)
  })

  it('preserves congested and capacity_mbps from snapshots and partial updates', () => {
    const s = useMetricsStore()
    s.initRealtime()
    s.applySnapshot({
      devices: {
        A: { bps: 10, utilization: 0.95, version: 1, congested: true, capacity_mbps: 1000 }
      },
      lastTick: 7
    })
    expect(s.byId.A).toEqual({
      bps: 10,
      utilization: 0.95,
      version: 1,
      congested: true,
      capacity_mbps: 1000
    })

    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: { tick: 8, devices: [{ id: 'A', bps: 12, utilization: 0.2, version: 2 }] }
    })

    expect(s.byId.A).toEqual({
      bps: 12,
      utilization: 0.2,
      version: 2,
      congested: true,
      capacity_mbps: 1000
    })
  })

  it('deviceMetricsUpdated applies multi-device updates with version check', () => {
    const s = useMetricsStore()
    s.initRealtime()
    // seed some state
    s.applySnapshot({ devices: { A: { bps: 1, utilization: 0.01, version: 1 } }, lastTick: 1 })

    // incoming update with higher version for A and a new B
    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: {
        tick: 2,
        devices: [
          { id: 'A', bps: 5, utilization: 0.2, version: 2 },
          { id: 'B', bps: 9, utilization: 0.9, version: 1 }
        ]
      }
    })

    expect(s.lastTick).toBe(2)
    expect(s.byId.A).toEqual({ bps: 5, utilization: 0.2, version: 2 })
    expect(s.byId.B).toEqual({ bps: 9, utilization: 0.9, version: 1 })

    // stale update for A (version 1) should be ignored
    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: { tick: 3, devices: [{ id: 'A', bps: 99, utilization: 0.99, version: 1 }] }
    })

    expect(s.byId.A).toEqual({ bps: 5, utilization: 0.2, version: 2 })
    // but B can be updated with implicit version increment when missing
    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: { tick: 4, devices: [{ id: 'B', bps: 10, utilization: 1.0 }] }
    })
    expect(s.byId.B).toEqual({ bps: 10, utilization: 1.0, version: 2 })
  })
})
