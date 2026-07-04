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

  it('preserves B2 shaping fields from snapshots and partial updates', () => {
    const s = useMetricsStore()
    s.initRealtime()
    s.applySnapshot({
      devices: {
        A: {
          bps: 396,
          utilization: 0.33,
          version: 1,
          congested: true,
          capacity_mbps: 1000,
          demand_up_bps: 100_000_000,
          demand_down_bps: 500_000_000,
          scale_up: 0.66,
          scale_down: 0.66,
          throttled: true
        }
      },
      lastTick: 7
    })
    expect(s.byId.A.demand_up_bps).toBe(100_000_000)
    expect(s.byId.A.demand_down_bps).toBe(500_000_000)
    expect(s.byId.A.scale_up).toBe(0.66)
    expect(s.byId.A.scale_down).toBe(0.66)
    expect(s.byId.A.throttled).toBe(true)
    expect(s.byId.A.congested).toBe(true)

    // WS event carrying new shaping values replaces them ...
    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: {
        tick: 8,
        devices: [
          {
            id: 'A',
            bps: 600,
            utilization: 0.5,
            version: 2,
            demand_up_bps: 100_000_000,
            demand_down_bps: 500_000_000,
            scale_up: 1.0,
            scale_down: 1.0,
            throttled: false
          }
        ]
      }
    })
    expect(s.byId.A.scale_up).toBe(1.0)
    expect(s.byId.A.throttled).toBe(false)

    // ... and an update without shaping fields keeps the previous ones.
    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: { tick: 9, devices: [{ id: 'A', bps: 601, utilization: 0.5, version: 3 }] }
    })
    expect(s.byId.A.bps).toBe(601)
    expect(s.byId.A.demand_up_bps).toBe(100_000_000)
    expect(s.byId.A.scale_down).toBe(1.0)
    expect(s.byId.A.throttled).toBe(false)
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
      payload: {
        tick: 3,
        devices: [
          { id: 'A', bps: 99, utilization: 0.99, version: 1 },
          { id: 'B', bps: 9, utilization: 0.9, version: 1 }
        ]
      }
    })

    expect(s.byId.A).toEqual({ bps: 5, utilization: 0.2, version: 2 })
    // but B can be updated with implicit version increment when missing
    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: {
        tick: 4,
        devices: [
          { id: 'A', bps: 5, utilization: 0.2, version: 2 },
          { id: 'B', bps: 10, utilization: 1.0 }
        ]
      }
    })
    expect(s.byId.A).toEqual({ bps: 5, utilization: 0.2, version: 2 })
    expect(s.byId.B).toEqual({ bps: 10, utilization: 1.0, version: 2 })
  })

  it('deviceMetricsUpdated removes devices absent from authoritative events', () => {
    const s = useMetricsStore()
    s.initRealtime()

    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: {
        tick: 1,
        authoritative: true,
        devices: [
          { id: 'A', bps: 10, utilization: 0.1, version: 1 },
          { id: 'B', bps: 20, utilization: 0.2, version: 1 }
        ]
      }
    })
    expect(Object.keys(s.byId).sort()).toEqual(['A', 'B'])

    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: {
        tick: 2,
        authoritative: true,
        devices: [{ id: 'B', bps: 25, utilization: 0.25, version: 2 }]
      }
    })
    expect(Object.keys(s.byId)).toEqual(['B'])
    expect(s.byId.B).toEqual({ bps: 25, utilization: 0.25, version: 2 })
    expect(s.lastTick).toBe(2)

    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: { tick: 3, authoritative: true, devices: [] }
    })
    expect(s.byId).toEqual({})
    expect(s.lastTick).toBe(3)
  })

  it('deviceMetricsUpdated without authoritative flag keeps absent devices', () => {
    const s = useMetricsStore()
    s.initRealtime()
    s.applySnapshot({
      devices: {
        A: { bps: 10, utilization: 0.1, version: 1 },
        B: { bps: 20, utilization: 0.2, version: 1 }
      },
      lastTick: 1
    })

    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: { tick: 2, devices: [{ id: 'B', bps: 25, utilization: 0.25, version: 2 }] }
    })
    expect(Object.keys(s.byId).sort()).toEqual(['A', 'B'])
    expect(s.byId.A).toEqual({ bps: 10, utilization: 0.1, version: 1 })
    expect(s.byId.B).toEqual({ bps: 25, utilization: 0.25, version: 2 })

    eventBus.emit('deviceMetricsUpdated', {
      type: 'deviceMetricsUpdated',
      payload: { tick: 3, devices: [] }
    })
    expect(Object.keys(s.byId).sort()).toEqual(['A', 'B'])
    expect(s.lastTick).toBe(3)
  })
})
