import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createTestingPinia } from '../test/pinia-shim'
import { useDevicesStore } from '../stores/devicesStore.js'
import { useLinksStore } from '../stores/linksStore.js'
import { useSelectionStore } from '../stores/selectionStore.js'
import { makeDeviceClickHandler } from '../composables/topologyCore/handlers'

function devicesFixture() {
  return [
    { id: 'a', name: 'A', type: 'EDGE_ROUTER' },
    { id: 'b', name: 'B', type: 'EDGE_ROUTER' },
    { id: 'c', name: 'C', type: 'CORE_ROUTER' },
    { id: 'o1', name: 'O1', type: 'ONT' },
    { id: 'o2', name: 'O2', type: 'ONT' }
  ]
}

describe('Multi-Link Creation Workflow (handlers)', () => {
  beforeEach(() => {
    // prefer testing pinia to auto-spy actions if needed later
    const tp = createTestingPinia({ stubActions: false })
    setActivePinia(tp)
  })

  it('creates links for each eligible source to the clicked target and exits mode', async () => {
    const devices = useDevicesStore()
    const links = useLinksStore()
    const selection = useSelectionStore()
    devices.devices = devicesFixture() as any

    const linkTool = {
      active: true,
      mode: 'multi' as const,
      sources: ['a', 'b'],
      startDevice: null,
      hoverDevice: null
    }
    const spyCreate = vi
      .spyOn(links, 'createManyToOne')
      .mockResolvedValue({ ok: 2, fail: 0, errors: [] } as unknown as any)

    const handler = makeDeviceClickHandler(
      linkTool as any,
      devices as any,
      links as any,
      selection as any,
      () => {},
      () => {}
    )

    const evt = { stopPropagation: () => {} } as unknown as MouseEvent
    await handler(evt, { id: 'c', type: 'CORE_ROUTER' })

    expect(spyCreate).toHaveBeenCalledWith(['a', 'b'], 'c')
    expect(spyCreate).toHaveBeenCalledTimes(1)
    expect(linkTool.active).toBe(false)
    expect(linkTool.mode).toBe('single')
    expect(linkTool.sources?.length).toBe(0)
  })

  it('filters out invalid ONT↔ONT pairs and exits with no calls', async () => {
    const devices = useDevicesStore()
    const links = useLinksStore()
    const selection = useSelectionStore()
    devices.devices = devicesFixture() as any

    const linkTool = {
      active: true,
      mode: 'multi' as const,
      sources: ['o1'],
      startDevice: null,
      hoverDevice: null
    }
    const spyCreate = vi
      .spyOn(links, 'createManyToOne')
      .mockResolvedValue({ ok: 0, fail: 0, errors: [] } as unknown as any)

    const handler = makeDeviceClickHandler(
      linkTool as any,
      devices as any,
      links as any,
      selection as any,
      () => {},
      () => {}
    )
    const evt = { stopPropagation: () => {} } as unknown as MouseEvent
    await handler(evt, { id: 'o2', type: 'ONT' })
    expect(spyCreate).not.toHaveBeenCalled()
    expect(linkTool.active).toBe(false)
    expect(linkTool.mode).toBe('single')
  })
})
