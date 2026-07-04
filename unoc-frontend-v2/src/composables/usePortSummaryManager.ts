import { ref, computed, watch, onUnmounted, type Ref, shallowRef, triggerRef } from 'vue'
import { logger } from '../utils/logger.js'
import { sortInterfaceSummaries } from './portSummaryOrdering.js'

export type InterfaceSummary = {
  id?: string
  name?: string
  port_role?: string | null
  effective_status?: string | null
  occupancy?: number | null
  capacity?: number | null
}

/**
 * Global Port Summary Manager - singleton pattern
 *
 * Solves the N+1 polling problem:
 * - Before: 64 components × 64 setInterval = 64 parallel HTTP requests every 2s
 * - After: 1 global interval = 1 bulk HTTP request every 2s
 *
 * Usage:
 *   const manager = usePortSummaryManager()
 *   manager.subscribe('device-123')
 *   const summary = computed(() => manager.get('device-123'))
 *   onUnmounted(() => manager.unsubscribe('device-123'))
 */

type CacheEntry = {
  data: InterfaceSummary[]
  timestamp: number
}

class PortSummaryManager {
  private cache = new Map<string, CacheEntry>()
  private subscriptions = new Map<string, number>() // deviceId -> refCount
  private timer: number | null = null
  private pollMs = 2000
  private isFetching = false
  private pendingFetch = false // Queue next fetch if subscribe during active fetch

  // CRITICAL: Reactivity trigger for Vue components (must be public for computed())
  public updateTrigger = shallowRef(0)

  private get subscribedIds(): string[] {
    return Array.from(this.subscriptions.keys())
  }

  // Trigger reactivity for all subscribers
  private notifyUpdate() {
    this.updateTrigger.value++
  }

  subscribe(deviceId: string) {
    const count = this.subscriptions.get(deviceId) || 0
    const isNew = count === 0
    this.subscriptions.set(deviceId, count + 1)

    // Start global polling if first subscription
    if (this.subscriptions.size === 1 && !this.timer) {
      this.startPolling()
    }

    // ALWAYS trigger fetch for new devices
    if (isNew) {
      if (this.isFetching) {
        // Queue next fetch if currently fetching
        this.pendingFetch = true
      } else {
        // Immediate fetch
        void this.fetchBulk()
      }
    }
  }

  unsubscribe(deviceId: string) {
    const count = this.subscriptions.get(deviceId) || 0
    if (count <= 1) {
      this.subscriptions.delete(deviceId)
      this.cache.delete(deviceId) // Clean up cache
    } else {
      this.subscriptions.set(deviceId, count - 1)
    }

    // Stop polling if no subscribers
    if (this.subscriptions.size === 0) {
      this.stopPolling()
    }
  }

  get(deviceId: string): InterfaceSummary[] {
    return this.cache.get(deviceId)?.data || []
  }

  has(deviceId: string): boolean {
    return this.cache.has(deviceId)
  }

  /**
   * Trigger immediate refresh for specific device(s)
   * Used after operations that change port occupancy (e.g., provisioning, link creation)
   */
  triggerRefresh(deviceId: string | string[]) {
    const ids = Array.isArray(deviceId) ? deviceId : [deviceId]

    // Only refresh devices that are currently subscribed
    const toRefresh = ids.filter((id) => this.subscriptions.has(id))

    if (toRefresh.length === 0) return

    // If already fetching, queue for next fetch
    if (this.isFetching) {
      this.pendingFetch = true
      return
    }

    // Trigger immediate fetch
    void this.fetchBulk()
  }

  private async fetchBulk() {
    const ids = this.subscribedIds
    if (ids.length === 0 || this.isFetching) return

    this.isFetching = true
    this.pendingFetch = false // Clear pending flag
    try {
      // Build query: /api/ports/summary?ids=dev1&ids=dev2&ids=dev3...
      const queryParams = ids.map((id) => `ids=${encodeURIComponent(id)}`).join('&')
      const url = `/api/ports/summary?${queryParams}`
      logger.debug('[PortSummaryManager] Fetching:', url, '| Subscribed IDs:', ids)

      const resp = await fetch(url)

      if (!resp.ok) {
        logger.warn('[PortSummaryManager] Bulk fetch failed:', resp.status)
        return
      }

      const data = await resp.json()
      logger.debug('[PortSummaryManager] Response:', data)
      const now = Date.now()

      // Update cache for all returned devices
      if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
        for (const [deviceId, interfaces] of Object.entries(data)) {
          if (Array.isArray(interfaces)) {
            const parsed = (interfaces as unknown[]).map((x) => {
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

            const sorted = sortInterfaceSummaries(parsed)

            logger.debug(`[PortSummaryManager] Cached ${deviceId}: ${sorted.length} interfaces`)
            this.cache.set(deviceId, { data: sorted, timestamp: now })
          }
        }
        // CRITICAL: Notify Vue components that cache has updated
        this.notifyUpdate()
      }
    } catch (e) {
      logger.error('[PortSummaryManager] Bulk fetch error:', e)
    } finally {
      this.isFetching = false

      // If new subscriptions arrived during fetch, trigger another fetch
      if (this.pendingFetch) {
        this.pendingFetch = false
        void this.fetchBulk()
      }
    }
  }

  private startPolling() {
    this.stopPolling()

    // Check if running in test environment
    type ViteEnv = { MODE?: string }
    const env =
      typeof import.meta !== 'undefined'
        ? (import.meta as unknown as { env?: ViteEnv }).env
        : undefined
    const isTest = (env?.MODE || '').toLowerCase() === 'test'

    if (isTest) return // No polling in tests

    this.timer = window.setInterval(() => {
      void this.fetchBulk()
    }, this.pollMs) as unknown as number
  }

  private stopPolling() {
    if (this.timer) {
      window.clearInterval(this.timer)
      this.timer = null
    }
  }

  // Debug helpers
  getStats() {
    return {
      subscriptions: this.subscriptions.size,
      cachedDevices: this.cache.size,
      polling: !!this.timer,
      subscribedIds: this.subscribedIds
    }
  }
}

// Singleton instance
const globalManager = new PortSummaryManager()

/**
 * Hook into global Port Summary Manager
 *
 * Automatically subscribes on mount, unsubscribes on unmount.
 * Reads from shared cache (instant, no HTTP request per component).
 *
 * Performance:
 * - 64 components using this = 1 HTTP request every 2s (vs 64 requests)
 * - 3 DB queries total (vs 192 queries)
 * - Instant UI updates (read from cache)
 */
export function usePortSummaryManaged(deviceId: Ref<string> | string) {
  const idRef = ref(deviceId)

  // CRITICAL: Make interfaces reactive to manager updates
  const interfaces = computed(() => {
    // Access updateTrigger to create reactive dependency
    globalManager.updateTrigger.value // eslint-disable-line @typescript-eslint/no-unused-expressions
    return globalManager.get(idRef.value)
  })

  const loading = ref(!globalManager.has(idRef.value))

  // Subscribe on mount, resubscribe on ID change
  watch(
    idRef,
    (newId, oldId) => {
      if (oldId) globalManager.unsubscribe(oldId)
      if (newId) {
        globalManager.subscribe(newId)
        loading.value = !globalManager.has(newId)
      }
    },
    { immediate: true }
  )

  // CRITICAL FIX: Update loading state when cache changes
  watch(
    interfaces,
    (newInterfaces) => {
      // If we have interfaces, loading is done
      if (newInterfaces && newInterfaces.length > 0) {
        loading.value = false
      }
    },
    { immediate: true }
  )

  // CRITICAL: Auto-unsubscribe on component unmount
  onUnmounted(() => {
    const id = idRef.value
    if (id) globalManager.unsubscribe(id)
  })

  return {
    interfaces,
    loading,
    // Debug
    getManagerStats: () => globalManager.getStats()
  }
}

// Export singleton for direct access if needed
export { globalManager as portSummaryManager }
