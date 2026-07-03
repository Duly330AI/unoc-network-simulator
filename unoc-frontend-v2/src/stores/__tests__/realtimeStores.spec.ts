import { describe, it, expect } from 'vitest'
import { createPinia, setActivePinia } from '../../test/pinia-shim'
import { useDevicesStore } from '../devicesStore.js'
import { useLinksStore } from '../linksStore.js'
import { eventBus } from '../../lib/eventBus.js'

describe('realtime store handlers', () => {
  it('updates device status on device.status.changed', async () => {
    setActivePinia(createPinia())
    const dev = useDevicesStore()
    dev.devices = [
      {
        id: 'd1',
        name: 'd1',
        type: 'CORE_ROUTER' as unknown as any,
        status: 'DOWN' as unknown as any,
        provisioned: false,
        role: 'active',
        admin_override_status: null
      }
    ]
    dev.initRealtime()
    eventBus.emit('device.status.changed', {
      type: 'device.status.changed',
      payload: { id: 'd1', status: 'UP' }
    })
    expect(dev.byId('d1')?.status).toBe('UP')
  })

  it('applies effective_status when provided', async () => {
    setActivePinia(createPinia())
    const dev = useDevicesStore()
    dev.devices = [
      {
        id: 'd3',
        name: 'd3',
        type: 'CORE_ROUTER' as unknown as any,
        status: 'UP' as unknown as any,
        effective_status: 'UP',
        provisioned: true,
        role: 'active',
        admin_override_status: null
      }
    ]
    dev.initRealtime()
    // Emit event that changes only effective_status (simulate dependency degradation)
    eventBus.emit('device.status.changed', {
      type: 'device.status.changed',
      payload: { id: 'd3', effective_status: 'DOWN' }
    })
    const after = dev.byId('d3')!
    expect(after.effective_status).toBe('DOWN')
    // Ensure base status unchanged
    expect(after.status).toBe('UP')
  })

  it('maps legacy optical event fields into signal fields', async () => {
    setActivePinia(createPinia())
    const dev = useDevicesStore()
    dev.devices = [
      {
        id: 'ont-legacy-optical',
        name: 'ont-legacy-optical',
        type: 'ONT' as unknown as any,
        status: 'UP' as unknown as any,
        effective_status: 'UP',
        provisioned: true,
        role: 'active',
        admin_override_status: null,
        signal_power_dbm: -12,
        signal_margin_db: 10,
        total_path_attenuation_db: 6
      }
    ]
    dev.initRealtime()

    eventBus.emit('device.optical.updated', {
      type: 'device.optical.updated',
      payload: {
        id: 'ont-legacy-optical',
        received_dbm: -44.5,
        margin_db: -3.2,
        attenuation_db: 48.5,
        signal_status: 'NO_SIGNAL'
      }
    })

    const after = dev.byId('ont-legacy-optical')!
    expect(after.signal_power_dbm).toBe(-44.5)
    expect(after.signal_margin_db).toBe(-3.2)
    expect(after.total_path_attenuation_db).toBe(48.5)
    expect(after.signal_status).toBe('NO_SIGNAL')
  })

  it('adds/removes links on link.created/deleted', async () => {
    setActivePinia(createPinia())
    const links = useLinksStore()
    links.initRealtime()
    eventBus.emit('link.created', {
      type: 'link.created',
      payload: {
        id: 'A__B',
        a_interface_id: 'A-if0',
        b_interface_id: 'B-if0',
        kind: 'FIBER',
        status: 'UP'
      }
    })
    expect(links.links.length).toBe(1)
    eventBus.emit('link.deleted', { type: 'link.deleted', payload: { id: 'A__B' } })
    expect(links.links.length).toBe(0)
  })

  it('updates admin_override_status immutably on device.status.changed', async () => {
    setActivePinia(createPinia())
    const dev = useDevicesStore()
    dev.devices = [
      {
        id: 'd2',
        name: 'd2',
        type: 'CORE_ROUTER' as unknown as any,
        status: 'UP' as unknown as any,
        provisioned: false,
        role: 'active',
        admin_override_status: null
      }
    ]
    dev.initRealtime()
    // set override
    eventBus.emit('device.status.changed', {
      type: 'device.status.changed',
      payload: { id: 'd2', admin_override_status: 'MAINTENANCE' }
    })
    const after1 = dev.byId('d2')!
    expect(after1.admin_override_status).toBe('MAINTENANCE')
    // clear override
    eventBus.emit('device.status.changed', {
      type: 'device.status.changed',
      payload: { id: 'd2', admin_override_status: null }
    })
    const after2 = dev.byId('d2')!
    expect(after2.admin_override_status).toBeNull()
  })

  it('ignores out-of-order device.status.changed by topo_version', async () => {
    setActivePinia(createPinia())
    const dev = useDevicesStore()
    dev.devices = [
      {
        id: 'd3',
        name: 'd3',
        type: 'CORE_ROUTER' as unknown as any,
        status: 'DOWN' as unknown as any,
        provisioned: false,
        role: 'active',
        admin_override_status: null
      }
    ]
    dev.initRealtime()
    // Apply newer topo_version first
    eventBus.emit('device.status.changed', {
      type: 'device.status.changed',
      topo_version: 10,
      payload: { id: 'd3', status: 'UP' }
    })
    expect(dev.byId('d3')?.status).toBe('UP')
    // Then an older event arrives; should be ignored
    eventBus.emit('device.status.changed', {
      type: 'device.status.changed',
      topo_version: 5,
      payload: { id: 'd3', status: 'DOWN' }
    })
    expect(dev.byId('d3')?.status).toBe('UP')
  })

  it('ignores out-of-order link.created/link.deleted by topo_version', async () => {
    setActivePinia(createPinia())
    const links = useLinksStore()
    links.initRealtime()
    // Newer create
    eventBus.emit('link.created', {
      type: 'link.created',
      topo_version: 20,
      payload: {
        id: 'A__B',
        a_interface_id: 'A-if0',
        b_interface_id: 'B-if0',
        kind: 'FIBER',
        status: 'UP'
      }
    })
    expect(links.links.length).toBe(1)
    // Older delete should be ignored
    eventBus.emit('link.deleted', {
      type: 'link.deleted',
      topo_version: 10,
      payload: { id: 'A__B' }
    })
    expect(links.links.length).toBe(1)
    // Newer delete should remove
    eventBus.emit('link.deleted', {
      type: 'link.deleted',
      topo_version: 25,
      payload: { id: 'A__B' }
    })
    expect(links.links.length).toBe(0)
  })

  it('ignores duplicate link.created and derives device ids from interface ids', async () => {
    setActivePinia(createPinia())
    const links = useLinksStore()
    links.initRealtime()
    // create once
    eventBus.emit('link.created', {
      type: 'link.created',
      payload: {
        id: 'X__Y',
        a_interface_id: 'X-if0',
        b_interface_id: 'Y-if0',
        kind: 'FIBER',
        status: 'UP'
      }
    })
    expect(links.links.length).toBe(1)
    // duplicate create should be ignored
    eventBus.emit('link.created', {
      type: 'link.created',
      payload: {
        id: 'X__Y',
        a_interface_id: 'X-if0',
        b_interface_id: 'Y-if0',
        kind: 'FIBER',
        status: 'UP'
      }
    })
    expect(links.links.length).toBe(1)
    // device ids are derived when not provided by backend
    const only = links.links[0]
    expect(only.a_device_id).toBe('X')
    expect(only.b_device_id).toBe('Y')
  })
})
