import { onUnmounted, ref, type Ref, unref, watch } from 'vue'
import { sortInterfaceSummaries } from './portSummaryOrdering.js'

export type InterfaceSummary = {
  id?: string
  name?: string
  port_role?: string | null
  effective_status?: string | null
  occupancy?: number | null
  capacity?: number | null
}

export function usePortSummary(deviceId: Ref<string> | string, pollMs = 0) {
  const idRef: Ref<string> =
    typeof deviceId === 'string' ? (ref(deviceId) as Ref<string>) : (deviceId as Ref<string>)
  const interfaces = ref<InterfaceSummary[]>([])
  const loading = ref(false)
  const error = ref('')
  let timer: number | null = null
  const loadedOnce = ref(false)
  // Guard against race conditions: track last request token
  let currentToken = 0
  type ViteEnv = { MODE?: string }
  const env =
    typeof import.meta !== 'undefined'
      ? (import.meta as unknown as { env?: ViteEnv }).env
      : undefined
  const isTest = (env?.MODE || '').toLowerCase() === 'test'

  async function fetchOnce() {
    const id = unref(idRef)
    if (!id) return
    error.value = ''
    if (!loadedOnce.value) loading.value = true
    try {
      const token = ++currentToken
      const resp = await fetch(`/api/ports/summary/${encodeURIComponent(id)}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      // Discard if a newer request has started
      if (token !== currentToken) return
      if (Array.isArray(data)) {
        // Expect list[InterfaceSummaryOut]
        const parsed = (data as unknown[]).map((x) => {
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
            // Preserve null: ports without a fixed capacity must not display as capacity 0
            capacity:
              typeof r.capacity === 'number'
                ? (r.capacity as number)
                : r.capacity == null
                  ? null
                  : Number(r.capacity) || 0
          } satisfies InterfaceSummary
        })

        interfaces.value = sortInterfaceSummaries(parsed)
      } else {
        interfaces.value = []
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

  watch(
    idRef,
    () => {
      // Reset state and (re)start
      interfaces.value = []
      error.value = ''
      loading.value = false
      loadedOnce.value = false
      // Bump token to invalidate in-flight response for previous deviceId
      currentToken++
      void fetchOnce()
      startPolling()
    },
    { immediate: true }
  )

  onUnmounted(() => stopPolling())

  return { interfaces, loading, error, fetchOnce, startPolling, stopPolling }
}
