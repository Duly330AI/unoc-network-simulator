import { beforeEach, describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ONTCockpit from '../components/cockpits/ONTCockpit.vue'
import { useMetricsStore } from '../stores/metricsStore.js'
import { useDevicesStore } from '../stores/devicesStore.js'
import { useTariffsStore } from '../stores/tariffsStore.js'

describe('ONTCockpit', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function seedOnt(status: string, signalStatus: 'OK' | 'WARNING' | 'CRITICAL' | 'NO_SIGNAL') {
    const metrics = useMetricsStore()
    const devices = useDevicesStore()
    const tariffs = useTariffsStore()
    ;(devices as any).devices = [
      {
        id: 'ont1',
        name: 'ONT-1',
        type: 'ONT',
        status,
        signal_status: signalStatus,
        signal_power_dbm: -20.4,
        tariff_id: 1
      }
    ]
    metrics.byId = {
      ont1: {
        bps: 40_000_000,
        utilization: 0.4,
        version: 1,
        upstream_bps: 10_000_000,
        downstream_bps: 30_000_000
      }
    }
    tariffs.byId = { 1: { id: 1, name: '100/20', max_up_mbps: 20, max_down_mbps: 100 } }
  }

  function mountOnt() {
    return mount(ONTCockpit, { props: { deviceId: 'ont1' } })
  }

  function ledOpacities(wrapper: ReturnType<typeof mountOnt>) {
    return wrapper.findAll('circle').map((circle) => Number(circle.attributes('opacity')))
  }

  function statusFill(wrapper: ReturnType<typeof mountOnt>, text: string) {
    const statusText = wrapper.findAll('text').find((node) => node.text() === text)
    return statusText?.attributes('fill')
  }

  it('renders status, RX power, traffic and tariff', async () => {
    seedOnt('UP', 'OK')
    const w = mount(ONTCockpit, { props: { deviceId: 'ont1' } })
    const txt = w.text()
    // Digital rows
    expect(txt).toContain('STATUS:')
    expect(txt).toContain('RX POWER:')
    // Value formatting
    expect(txt).toContain('-20.4 dBm')
    // Tariff shown below frame
    expect(txt).toContain('100/20')
    // Should render frame rects
    const rects = w.findAll('rect')
    expect(rects.length).toBeGreaterThan(0)
  })

  it('shows throttled traffic as delivered primary with muted request labels', () => {
    seedOnt('UP', 'OK')
    const metrics = useMetricsStore()
    metrics.byId.ont1 = {
      bps: 2_000_000_000,
      utilization: 0.5,
      version: 2,
      upstream_bps: 1_000_000_000,
      downstream_bps: 1_000_000_000,
      demand_up_bps: 92_000_000_000,
      demand_down_bps: 92_000_000_000,
      scale_up: 0.011,
      scale_down: 0.011,
      throttled: true
    }

    const w = mountOnt()
    const tspans = w.findAll('tspan')
    const tspanText = tspans.map((node) => node.text())
    const trafficRows = w.findAll('text').filter((node) => node.text().includes('req 92G'))

    expect(tspanText.filter((text) => text === '1.00 Gbps')).toHaveLength(2)
    expect(tspanText.filter((text) => text === 'req 92G')).toHaveLength(2)
    expect(tspans.filter((node) => node.text() === 'req 92G').every((node) => node.attributes('font-size') === '7px')).toBe(true)
    expect(tspans.filter((node) => node.text() === 'req 92G').every((node) => node.attributes('fill') === '#c7a76a')).toBe(true)
    expect(trafficRows.map((node) => node.attributes('fill'))).toEqual(
      expect.arrayContaining(['#64b5f6', '#ffa726'])
    )
    expect(trafficRows.map((node) => node.attributes('fill'))).not.toContain('#ff9800')
  })

  it('lights green for UP with OK optical signal', () => {
    seedOnt('UP', 'OK')
    const w = mountOnt()

    expect(ledOpacities(w)).toEqual([1, 0.25, 0.25])
    expect(statusFill(w, 'UP')).toBe('#66bb6a')
  })

  it('lights amber for UP with WARNING optical signal while keeping status text UP', () => {
    seedOnt('UP', 'WARNING')
    const w = mountOnt()

    expect(ledOpacities(w)).toEqual([0.25, 1, 0.25])
    expect(w.text()).toContain('UP')
    expect(statusFill(w, 'UP')).toBe('#ffd54f')
  })

  it('lights amber for UP with CRITICAL optical signal while keeping status text UP', () => {
    seedOnt('UP', 'CRITICAL')
    const w = mountOnt()

    expect(ledOpacities(w)).toEqual([0.25, 1, 0.25])
    expect(w.text()).toContain('UP')
    expect(statusFill(w, 'UP')).toBe('#ffd54f')
  })

  it('lights red for DOWN even when optical signal is WARNING', () => {
    seedOnt('DOWN', 'WARNING')
    const w = mountOnt()

    expect(ledOpacities(w)).toEqual([0.25, 0.25, 1])
    expect(statusFill(w, 'DOWN')).toBe('#ef5350')
  })
})
