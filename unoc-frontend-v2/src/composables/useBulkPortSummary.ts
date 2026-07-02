import { ref, type Ref, watch, onUnmounted } from 'vue'

export type InterfaceSummary = {
  id?: string
  name?: string
  port_role?: string | null
  effective_status?: string | null
  occupancy?: number | null
  capacity?: number | null
}

/**
 * Bulk variant: fetch port summaries for multiple devices in ONE request.
 *
 * Usage:
 *   const deviceIds = ref(['dev1', 'dev2', 'dev3'])
 *   const { summaries, loading, error } = useBulkPortSummary(deviceIds)
 *   // summaries.value = { 'dev1': [...], 'dev2': [...], 'dev3': [...] }
 *
 * Performance:
 *   - 64 devices: 1 HTTP request (vs 64 separate)
 *   - 3 DB queries total (vs 192 separate)
 *   - ~50-100ms (vs 3-5 seconds with rate limiting)
 */
export function useBulkPortSummary(deviceIds: Ref<string[]>, pollMs = 0) {
  const summaries = ref<Record<string, InterfaceSummary[]>>({})
  const loading = ref(false)
  const error = ref('')
  let timer: number | null = null
  const loadedOnce = ref(false)
  let currentToken = 0

  type ViteEnv = { MODE?: string }
  const env =
    typeof import.meta !== 'undefined'
      ? (import.meta as unknown as { env?: ViteEnv }).env
      : undefined
  const isTest = (env?.MODE || '').toLowerCase() === 'test'

  async function fetchOnce() {
    const ids = deviceIds.value
    if (!ids || ids.length === 0) {
      summaries.value = {}
      return
    }

    error.value = ''
    if (!loadedOnce.value) loading.value = true

    try {
      const token = ++currentToken

      // Build query string: ?ids=dev1&ids=dev2&ids=dev3...
      const queryParams = ids.map((id) => `ids=${encodeURIComponent(id)}`).join('&')
      const resp = await fetch(`/api/ports/summary?${queryParams}`)

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()

      // Discard if a newer request has started
      if (token !== currentToken) return

      if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
        // Expect dict[str, list[InterfaceSummaryOut]]
        const result: Record<string, InterfaceSummary[]> = {}

        for (const [deviceId, interfaces] of Object.entries(data)) {
          if (Array.isArray(interfaces)) {
            result[deviceId] = (interfaces as unknown[]).map((x) => {
              const r = x as Record<string, unknown>
              return {
                id: (r.id as string) ?? undefined,
                name: (r.name as string) ?? undefined,
                port_role: (r.port_role as string | null) ?? null,
                effective_status: (r.effective_status as string | null) ?? null,
                occupancy:
                  typeof r.occupancy === 'number'
                    ? (r.occupancy as number)
                    : Number(r.occupancy ?? 0) || 0,
                capacity:
                  typeof r.capacity === 'number'
                    ? (r.capacity as number)
                    : Number(r.capacity ?? 0) || 0
              } satisfies InterfaceSummary
            })
          } else {
            result[deviceId] = []
          }
        }

        summaries.value = result
      } else {
        summaries.value = {}
      }

      loadedOnce.value = true
    } catch (e) {
      error.value = (e as Error)?.message || 'Fetch failed'
    } finally {
      loading.value = false
    }
  }

  function startPolling() {
    stopPolling()
    if (pollMs > 0 && !isTest) {
      timer = window.setInterval(() => {
        void fetchOnce()
      }, pollMs) as unknown as number
    }
  }

  function stopPolling() {
    if (timer) {
      window.clearInterval(timer)
      timer = null
    }
  }

  // Auto-fetch on deviceIds change
  watch(
    deviceIds,
    () => {
      void fetchOnce()
    },
    { immediate: true }
  )

  // Auto-start polling if pollMs > 0
  if (pollMs > 0 && !isTest) {
    startPolling()
  }

  onUnmounted(() => {
    stopPolling()
  })

  return {
    summaries,
    loading,
    error,
    refetch: fetchOnce,
    startPolling,
    stopPolling
  }
}
