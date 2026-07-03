import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { eventBus } from '../../lib/eventBus.js'
import { useLinkMetricsStore } from '../linkMetricsStore.js'

describe('linkMetricsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initial state', () => {
    const s = useLinkMetricsStore()
    expect(s.byId).toEqual({})
    expect(s.lastTick).toBe(0)
  })

  it('linkMetricsUpdated applies updates with version check', () => {
    const s = useLinkMetricsStore()
    s.initRealtime()

    // First event, two links
    eventBus.emit('linkMetricsUpdated', {
      type: 'linkMetricsUpdated',
      payload: {
        tick: 1,
        links: [
          { id: 'l_core', bps: 200_000_000, utilization: 0.2, version: 1 },
          { id: 'l_leaf', bps: 100_000_000, utilization: 0.1, version: 1 }
        ]
      }
    })
    expect(s.lastTick).toBe(1)
    expect(s.byId.l_core).toEqual({ bps: 200_000_000, utilization: 0.2, version: 1 })
    expect(s.byId.l_leaf).toEqual({ bps: 100_000_000, utilization: 0.1, version: 1 })

    // Stale update should be ignored
    eventBus.emit('linkMetricsUpdated', {
      type: 'linkMetricsUpdated',
      payload: { tick: 2, links: [{ id: 'l_core', bps: 999, utilization: 9.99, version: 1 }] }
    })
    expect(s.byId.l_core).toEqual({ bps: 200_000_000, utilization: 0.2, version: 1 })

    // Update without explicit version increments previous by 1
    eventBus.emit('linkMetricsUpdated', {
      type: 'linkMetricsUpdated',
      payload: { tick: 3, links: [{ id: 'l_leaf', bps: 110_000_000, utilization: 0.11 }] }
    })
    expect(s.byId.l_leaf).toEqual({ bps: 110_000_000, utilization: 0.11, version: 2 })
  })

  it('applySnapshot replaces state with snapshot links', () => {
    const s = useLinkMetricsStore()
    // prime some state
    s.byId = { old: { bps: 1, utilization: 0.001, version: 99 } } as any
    s.lastTick = 7
    s.applySnapshot({
      lastTick: 10,
      links: {
        l1: { bps: 50_000_000, utilization: 0.05 },
        l2: { bps: 80_000_000, utilization: 0.08, version: 3 }
      }
    })
    expect(s.lastTick).toBe(10)
    expect(Object.keys(s.byId).sort()).toEqual(['l1', 'l2'])
    expect(s.byId.l1).toEqual({ bps: 50_000_000, utilization: 0.05, version: 0 })
    expect(s.byId.l2).toEqual({ bps: 80_000_000, utilization: 0.08, version: 3 })
  })

  it('preserves congested and capacity_mbps from snapshots and partial updates', () => {
    const s = useLinkMetricsStore()
    s.initRealtime()
    s.applySnapshot({
      lastTick: 10,
      links: {
        l1: {
          bps: 950_000_000,
          utilization: 0.95,
          version: 1,
          congested: true,
          capacity_mbps: 1000
        }
      }
    })
    expect(s.byId.l1).toEqual({
      bps: 950_000_000,
      utilization: 0.95,
      version: 1,
      congested: true,
      capacity_mbps: 1000
    })

    eventBus.emit('linkMetricsUpdated', {
      type: 'linkMetricsUpdated',
      payload: { tick: 11, links: [{ id: 'l1', bps: 100_000_000, utilization: 0.1, version: 2 }] }
    })

    expect(s.byId.l1).toEqual({
      bps: 100_000_000,
      utilization: 0.1,
      version: 2,
      congested: true,
      capacity_mbps: 1000
    })
  })
})
