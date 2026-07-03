import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from '../../test/pinia-shim'
import { useDevicesStore } from '../devicesStore.js'

describe('devicesStore provisioning', () => {
  const origFetch = globalThis.fetch

  beforeEach(() => {
    setActivePinia(createPinia())
    ;(globalThis as unknown as { fetch: unknown }).fetch = vi.fn()
  })

  afterEach(() => {
    ;(globalThis as unknown as { fetch: unknown }).fetch =
      origFetch as unknown as typeof globalThis.fetch
    vi.restoreAllMocks()
  })

  it('throws backend detail on provisioning failure', async () => {
    const store = useDevicesStore()
    ;(globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({
        detail: 'Cannot provision ONT: no valid provisioned OLT path found.'
      })
    })

    await expect(store.provision('ont-no-parent')).rejects.toThrow(
      'Cannot provision ONT: no valid provisioned OLT path found.'
    )
  })
})
