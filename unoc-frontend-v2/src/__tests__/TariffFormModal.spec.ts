import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TariffFormModal from '../components/tariffs/TariffFormModal.vue'

describe('TariffFormModal', () => {
  it('validates fields and emits submit', async () => {
    const w = mount(TariffFormModal, { props: { initial: null, saving: false, error: null } })
    const btn = w.get('button.primary')
    expect(btn.attributes('disabled')).toBeDefined()
    await w.get('#name').setValue('Plan 100/20')
    await w.get('#down').setValue('100')
    await w.get('#up').setValue('20')
    // Technology is required: submit stays disabled until it is chosen
    expect(btn.attributes('disabled')).toBeDefined()
    await w.get('#tech').setValue('GPON')
    expect(btn.attributes('disabled')).toBeUndefined()
    await btn.trigger('click')
    const ev = w.emitted('submit')
    expect(ev && ev[0] && ev[0][0]).toMatchObject({
      name: 'Plan 100/20',
      max_down_mbps: 100,
      max_up_mbps: 20,
      technology: 'GPON'
    })
  })

  it('prefills on edit', async () => {
    const w = mount(TariffFormModal, {
      props: {
        initial: { id: 1, name: 'A', max_down_mbps: 10, max_up_mbps: 5, technology: 'AON' as const },
        saving: false,
        error: null
      }
    })
    expect((w.get('#name').element as HTMLInputElement).value).toBe('A')
    expect((w.get('#down').element as HTMLInputElement).value).toBe('10')
    expect((w.get('#up').element as HTMLInputElement).value).toBe('5')
    expect((w.get('#tech').element as HTMLSelectElement).value).toBe('AON')
  })

  it('emits cancel when Cancel is clicked', async () => {
    const w = mount(TariffFormModal, { props: { initial: null, saving: false, error: null } })
    await w.get('button.btn').trigger('click')
    expect(w.emitted('cancel')).toBeTruthy()
  })
})
