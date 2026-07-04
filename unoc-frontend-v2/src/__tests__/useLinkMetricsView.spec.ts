import { describe, expect, it } from 'vitest'
import { shapedRateParts } from '../composables/useLinkMetricsView.js'

describe('shapedRateParts', () => {
  it('returns delivered as the primary value and demand as a muted request label when throttled', () => {
    expect(shapedRateParts(1_000_000_000, 92_000_000_000, 0.011)).toEqual({
      delivered: '1.00 Gbps',
      request: 'req 92G'
    })
  })

  it('omits the request label when the direction is not throttled', () => {
    expect(shapedRateParts(1_000_000_000, 92_000_000_000, 1)).toEqual({
      delivered: '1.00 Gbps',
      request: null
    })
  })
})
