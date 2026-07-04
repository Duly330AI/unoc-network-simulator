import { describe, expect, it } from 'vitest'
import { sortInterfaceSummaries } from '../portSummaryOrdering.js'

describe('sortInterfaceSummaries', () => {
  it('sorts interface summaries in natural name order', () => {
    const ports = [
      { id: 'p10', name: 'access10' },
      { id: 'p2', name: 'access2' },
      { id: 'p1', name: 'access1' },
      { id: 'u1', name: 'uplink1' }
    ]

    expect(sortInterfaceSummaries(ports).map((port) => port.name)).toEqual([
      'access1',
      'access2',
      'access10',
      'uplink1'
    ])
  })

  it('falls back to id and keeps input order as the final tie-break', () => {
    const blankA = { port_role: 'ACCESS' }
    const blankB = { port_role: 'PON' }
    const eth10 = { id: 'eth10' }
    const eth2 = { id: 'eth2' }

    expect(sortInterfaceSummaries([eth10, blankA, eth2, blankB])).toEqual([
      blankA,
      blankB,
      eth2,
      eth10
    ])
  })
})
