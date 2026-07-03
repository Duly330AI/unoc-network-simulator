import { defineStore } from 'pinia'
import { type Link } from './links/types.js'
import { registerLinkRealtime } from './links/realtime.js'
import { createBetweenDevices as createBetweenDevicesAction } from './links/createBetweenDevices.js'
import { createManyToOne as createManyToOneAction } from './links/createManyToOne.js'
// Re-export Link type so consumers can import it from this module
export type { Link } from './links/types.js'

interface State {
  links: Link[]
  loading: boolean
  error: string | null
  // Track last applied topo_version per link id to ignore stale events
  _lastTopoByLink: Record<string, number>
}

export const useLinksStore = defineStore('links', {
  state: (): State => ({ links: [], loading: false, error: null, _lastTopoByLink: {} }),
  getters: {
    byDevice: (state) => (id: string) =>
      state.links.filter((l) => l.a_device_id === id || l.b_device_id === id),
    hasLinkBetween: (state) => (a: string, b: string) => {
      if (a === b) return true
      return state.links.some(
        (l) =>
          (l.a_device_id === a && l.b_device_id === b) ||
          (l.a_device_id === b && l.b_device_id === a)
      )
    }
  },
  actions: {
    initRealtime() {
      registerLinkRealtime(this)
    },
    async fetchAll() {
      if (this.loading) return
      this.loading = true
      this.error = null
      try {
        const resp = await fetch('/api/links')
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        this.links = await resp.json()
      } catch (e) {
        const err = e as Error
        this.error = err.message
      } finally {
        this.loading = false
      }
    },
    async update(
      id: string,
      patch: Partial<
        Pick<Link, 'status' | 'admin_override_status' | 'length_km' | 'physical_medium_id'>
      >
    ) {
      const resp = await fetch(`/api/links/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch)
      })
      if (!resp.ok) {
        let msg = `Update link failed ${resp.status}`
        try {
          const j = await resp.json()
          msg = j?.detail || msg
        } catch {
          try {
            msg = await resp.text()
          } catch {
            /* ignore */
          }
        }
        throw new Error(msg)
      }
      const updated = (await resp.json()) as Link
      const idx = this.links.findIndex((l) => l.id === id)
      if (idx !== -1) this.links.splice(idx, 1, updated)
      else this.links.push(updated)
      return updated
    },
    async createBetweenDevices(
      aDeviceId: string,
      bDeviceId: string,
      opts?: { headless?: boolean }
    ) {
      return createBetweenDevicesAction(this, aDeviceId, bDeviceId, opts)
    },
    async createManyToOne(sourceDeviceIds: string[], targetDeviceId: string) {
      return createManyToOneAction(this, sourceDeviceIds, targetDeviceId)
    },
    async setOverride(id: string, status: string | null) {
      const resp = await fetch(`/api/links/${id}/override`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ admin_override_status: status })
      })
      if (!resp.ok) {
        let msg = `Override failed ${resp.status}`
        try {
          msg = (await resp.json())?.detail || msg
        } catch {
          /* ignore */
        }
        throw new Error(msg)
      }
      // PATCH /links/{id}/override is async-by-default and returns 202 Accepted
      // with a { accepted, job_id } payload. Do not overwrite the link in state
      // with that payload; instead rely on realtime events (link.override.changed
      // and link.status.changed) to merge the update when the worker processes it.
      if (resp.status === 202) {
        // Optionally surface job info to callers; keep store untouched for determinism.
        try {
          return (await resp.json()) as unknown
        } catch {
          return { accepted: true }
        }
      }
      // Fallback for possible synchronous responses (future-proof)
      const updated = (await resp.json()) as Link
      const idx = this.links.findIndex((l) => l.id === id)
      if (idx !== -1) this.links.splice(idx, 1, updated)
      else this.links.push(updated)
      return updated
    }
  }
})
