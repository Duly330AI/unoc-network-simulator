import { describe, it, expect } from 'vitest'
import { decideLinkColor, computeDashForLength } from '../linkColor'
import { STATUS_COLORS, UTIL_OVERLOAD_COLOR } from '../../colorScale'

describe('linkColor helper', () => {
  it('prefers DOWN status over everything', () => {
    const a = { status: 'DOWN', provisioned: true }
    const b = { status: 'UP', provisioned: true }
    const m = { utilization: 2 }
    const r = decideLinkColor(a, b, m)
    expect(r.stroke).toBe(STATUS_COLORS.DOWN)
    expect(r.overloaded).toBe(false)
  })

  it('treats admin_override_status as authoritative', () => {
    const a = { status: 'UP', admin_override_status: 'down', provisioned: true }
    const b = { status: 'UP', provisioned: true }
    const r = decideLinkColor(a, b, { utilization: 0 })
    expect(r.stroke).toBe(STATUS_COLORS.DOWN)
  })

  it('does NOT use grey when metrics exist, even if one endpoint unprovisioned', () => {
    const a = { status: 'UP', provisioned: false }
    const b = { status: 'UP', provisioned: true }
    const r = decideLinkColor(a, b, { utilization: 0.2 })
    expect(r.stroke).not.toBe(STATUS_COLORS.UNKNOWN)
    expect(r.overloaded).toBe(false)
  })

  it('uses grey only when both endpoints unprovisioned and no metrics', () => {
    const a = { status: 'UP', provisioned: false }
    const b = { status: 'UP', provisioned: false }
    const r = decideLinkColor(a, b, undefined)
    expect(r.stroke).toBe(STATUS_COLORS.UNKNOWN)
    expect(r.overloaded).toBe(false)
  })

  it('maps utilization < 100% to bucket colors', () => {
    const a = { status: 'UP', provisioned: true }
    const b = { status: 'UP', provisioned: true }
    const r = decideLinkColor(a, b, { utilization: 0.42 })
    // Not asserting exact color bucket here (delegated), but not red/grey/purple
    expect([STATUS_COLORS.DOWN, STATUS_COLORS.UNKNOWN, UTIL_OVERLOAD_COLOR]).not.toContain(r.stroke)
    expect(r.overloaded).toBe(false)
  })

  it('uses overload color >=100% and sets overloaded flag', () => {
    const a = { status: 'UP', provisioned: true }
    const b = { status: 'UP', provisioned: true }
    const r = decideLinkColor(a, b, { utilization: 1.1 })
    expect(r.stroke).toBe(UTIL_OVERLOAD_COLOR)
    expect(r.overloaded).toBe(true)
  })

  it('uses overload color for congested links even below 100% utilization', () => {
    const a = { status: 'UP', provisioned: true }
    const b = { status: 'UP', provisioned: true }
    const r = decideLinkColor(a, b, { utilization: 0.42, congested: true })
    expect(r.stroke).toBe(UTIL_OVERLOAD_COLOR)
    expect(r.overloaded).toBe(true)
  })

  it('keeps DOWN precedence over congested links', () => {
    const a = { status: 'UP', provisioned: true }
    const b = { status: 'UP', provisioned: true }
    const r = decideLinkColor(a, b, { utilization: 0.42, congested: true }, {
      linkEffectiveStatus: 'DOWN'
    })
    expect(r.stroke).toBe(STATUS_COLORS.DOWN)
    expect(r.overloaded).toBe(false)
  })
})

describe('computeDashForLength', () => {
  it('clamps dash length to 6..20', () => {
    expect(computeDashForLength(0)).toBe(10)
    expect(computeDashForLength(30)).toBeGreaterThanOrEqual(6)
    expect(computeDashForLength(30)).toBeLessThanOrEqual(20)
    expect(computeDashForLength(10000)).toBe(20)
  })
})
