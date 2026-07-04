import { describe, it, expect } from 'vitest'
import {
  formatBpsCompact,
  formatShapedRate,
  THROTTLE_SCALE_THRESHOLD
} from '../composables/useLinkMetricsView.js'

describe('formatBpsCompact', () => {
  it('formats magnitudes compactly', () => {
    expect(formatBpsCompact(1_500_000_000)).toBe('1.5G')
    expect(formatBpsCompact(92_000_000_000)).toBe('92G')
    expect(formatBpsCompact(330_000_000)).toBe('330M')
    expect(formatBpsCompact(5_000)).toBe('5K')
    expect(formatBpsCompact(42)).toBe('42b')
    expect(formatBpsCompact(null)).toBe('—')
    expect(formatBpsCompact(Number.NaN)).toBe('—')
  })
})

describe('formatShapedRate', () => {
  it('shows plain delivered value when not throttled', () => {
    expect(formatShapedRate(330_000_000, 330_000_000, 1.0)).toBe('330.00 Mbps')
    expect(formatShapedRate(330_000_000, undefined, undefined)).toBe('330.00 Mbps')
  })

  it('shows delivered / requested when scale is below the throttle threshold', () => {
    expect(formatShapedRate(330_000_000, 500_000_000, 0.66)).toBe('330M / 500M')
  })

  it('uses the shared throttle threshold boundary', () => {
    expect(formatShapedRate(980, 1000, THROTTLE_SCALE_THRESHOLD)).toBe('980 bps')
    expect(formatShapedRate(979, 1000, THROTTLE_SCALE_THRESHOLD - 0.001)).toBe('979b / 1K')
  })

  it('never shows requested without a positive demand', () => {
    expect(formatShapedRate(100, 0, 0.5)).toBe('100 bps')
    expect(formatShapedRate(100, null, 0.5)).toBe('100 bps')
  })

  it('returns placeholder for missing delivered value', () => {
    expect(formatShapedRate(null, 100, 0.5)).toBe('—')
  })
})
