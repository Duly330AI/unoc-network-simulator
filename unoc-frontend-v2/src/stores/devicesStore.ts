import { defineStore } from 'pinia'
import type { EventEnvelope } from '../lib/eventBus.js'
import { eventBus } from '../lib/eventBus.js'
import type { DeviceOut, InterfaceOut } from '../types/domain.js'

// Central status normalization + mapping helper.
// Maps various backend or legacy tokens into UI visual set: UP | DOWN | DEGRADED | UNKNOWN.
function normalizeVisualStatus(raw: unknown): string | null {
  if (typeof raw !== 'string' || !raw) return null
  let s = raw.trim()
  if (s.startsWith('Status.')) s = s.slice('Status.'.length)
  const lower = s.toLowerCase()
  // Canonical direct pass-through
  if (lower === 'up') return 'UP'
  if (lower === 'down') return 'DOWN'
  if (lower === 'degraded') return 'DEGRADED'
  if (lower === 'unknown') return 'UNKNOWN'
  // Map common operational tokens
  if (['active', 'online', 'provisioned'].includes(lower)) return 'UP'
  if (['partial'].includes(lower)) return 'DEGRADED'
  if (['failed', 'unreachable', 'offline'].includes(lower)) return 'DOWN'
  return 'UNKNOWN'
}

// Extend backend-generated DeviceOut with optical fields currently provided by API/events
export type DeviceOutX = DeviceOut & {
  signal_status?: 'OK' | 'WARNING' | 'CRITICAL' | 'NO_SIGNAL' | null
  signal_power_dbm?: number | null
  signal_margin_db?: number | null
  tx_power_dbm?: number | null
  sensitivity_min_dbm?: number | null
  // Effective status (dynamic) optionally supplied by realtime events; if absent fall back to status.
  effective_status?: string | null
  // UI-only helper (not persisted): latest total path attenuation
  total_path_attenuation_db?: number | null
  // When loaded via include_interfaces=true
  interfaces?: InterfaceOut[]
}

interface State {
  devices: DeviceOutX[]
  loading: boolean
  // Separate flag for include_interfaces fetches to avoid blocking on plain fetch
  loadingInterfaces: boolean
  error: string | null
  // Track last applied topo_version per device to drop out-of-order updates
  _lastTopoByDevice: Record<string, number>
}

interface DeviceCreatePayload {
  id: string
  name: string
  type: string
  status?: string
  parent_container_id?: string | null
  hardware_model_id?: number | null
}

export const useDevicesStore = defineStore('devices', {
  state: (): State => ({
    devices: [],
    loading: false,
    loadingInterfaces: false,
    error: null,
    _lastTopoByDevice: {}
  }),
  getters: {
    byId: (state) => (id: string) => state.devices.find((d: DeviceOutX) => d.id === id)
  },
  actions: {
    initRealtime() {
      // Device status change handler
      eventBus.on<EventEnvelope>('device.status.changed', (env) => {
        if (import.meta.env?.DEV) {
          const p: unknown = env?.payload
          const id = p && typeof p === 'object' && 'id' in p ? (p as { id?: string }).id : undefined
          // eslint-disable-next-line no-console
          console.debug('[devicesStore] status.changed', id)
        }
        const payload = (env?.payload || {}) as {
          id: string
          status?: DeviceOutX['status']
          effective_status?: string | null
          admin_override_status?: DeviceOutX['admin_override_status']
          // optional optical fields piggybacked
          signal_status?: DeviceOutX['signal_status']
          signal_power_dbm?: DeviceOutX['signal_power_dbm']
          signal_margin_db?: DeviceOutX['signal_margin_db']
        }
        if (!payload?.id) return
        const topo = typeof env?.topo_version === 'number' ? (env.topo_version as number) : null
        if (topo != null) {
          const last = this._lastTopoByDevice[payload.id]
          if (typeof last === 'number' && topo < last) {
            if (import.meta.env?.DEV) {
              // eslint-disable-next-line no-console
              console.debug(
                '[devicesStore] drop stale status.changed',
                payload.id,
                topo,
                'last=',
                last
              )
            }
            return
          }
        }
        const idx = this.devices.findIndex((d: DeviceOutX) => d.id === payload.id)
        if (idx === -1) return
        const after: DeviceOutX = { ...this.devices[idx] }
        const normalize = (s: unknown): string | null => {
          if (typeof s !== 'string') return null
          return s.startsWith('Status.') ? s.slice('Status.'.length) : s
        }
        const ns = normalize(payload.status)
        if (ns) after.status = ns as DeviceOutX['status']
        // Accept effective_status even if null/empty to permit clearing stale values (normalize tokens like Status.DOWN)
        if ('effective_status' in payload)
          after.effective_status = normalize(payload.effective_status)
        if ('admin_override_status' in payload)
          after.admin_override_status = normalize(payload.admin_override_status)
        if ('signal_status' in payload) after.signal_status = payload.signal_status ?? null
        if ('signal_power_dbm' in payload) after.signal_power_dbm = payload.signal_power_dbm ?? null
        if ('signal_margin_db' in payload) after.signal_margin_db = payload.signal_margin_db ?? null
        // Replace immutably
        this.devices.splice(idx, 1, after)
        if (topo != null) this._lastTopoByDevice[payload.id] = topo

        // Direct DOM patch: in some edge cases the initial draw() may run before
        // the first realtime status event arrives, leaving data-status="UNKNOWN"
        // until a subsequent watcher-triggered redraw. To make the frame color
        // flip deterministic and instant, update the attribute here as well.
        try {
          const el = document.querySelector(
            `g.device-node[data-device-id="${CSS.escape(payload.id)}"]`
          ) as SVGGElement | null
          if (el) {
            const cur = normalize(after.effective_status) || normalize(after.status) || 'UNKNOWN'
            if (el.getAttribute('data-status') !== cur) el.setAttribute('data-status', cur)
          }
        } catch {
          /* non-fatal */
        }
      })

      // Dedicated optical update event
      eventBus.on<EventEnvelope>('device.optical.updated', (env) => {
        if (import.meta.env?.DEV) {
          const p: unknown = env?.payload
          const id = p && typeof p === 'object' && 'id' in p ? (p as { id?: string }).id : undefined
          // eslint-disable-next-line no-console
          console.debug('[devicesStore] optical.updated', id)
        }
        const payload = (env?.payload || {}) as {
          id: string
          signal_status?: DeviceOutX['signal_status']
          signal_power_dbm?: DeviceOutX['signal_power_dbm']
          signal_margin_db?: DeviceOutX['signal_margin_db']
          received_dbm?: DeviceOutX['signal_power_dbm']
          margin_db?: DeviceOutX['signal_margin_db']
          attenuation_db?: number | null
          tx_power_dbm?: DeviceOutX['tx_power_dbm']
          sensitivity_min_dbm?: DeviceOutX['sensitivity_min_dbm']
          total_path_attenuation_db?: number | null
        }
        if (!payload?.id) return
        const topo = typeof env?.topo_version === 'number' ? (env.topo_version as number) : null
        if (topo != null) {
          const last = this._lastTopoByDevice[payload.id]
          if (typeof last === 'number' && topo < last) {
            if (import.meta.env?.DEV) {
              // eslint-disable-next-line no-console
              console.debug(
                '[devicesStore] drop stale optical.updated',
                payload.id,
                topo,
                'last=',
                last
              )
            }
            return
          }
        }
        const idx = this.devices.findIndex((d: DeviceOutX) => d.id === payload.id)
        if (idx === -1) return
        const before = this.devices[idx]
        const after: DeviceOutX = { ...before }
        if ('signal_status' in payload) after.signal_status = payload.signal_status ?? null
        const signalPower =
          payload.signal_power_dbm !== undefined ? payload.signal_power_dbm : payload.received_dbm
        const signalMargin =
          payload.signal_margin_db !== undefined ? payload.signal_margin_db : payload.margin_db
        if (signalPower !== undefined) after.signal_power_dbm = signalPower ?? null
        if (signalMargin !== undefined) after.signal_margin_db = signalMargin ?? null
        if ('tx_power_dbm' in payload) after.tx_power_dbm = payload.tx_power_dbm ?? null
        if ('sensitivity_min_dbm' in payload)
          after.sensitivity_min_dbm = payload.sensitivity_min_dbm ?? null
        // Store non-schema field used by UI for display only
        const attenuation =
          payload.total_path_attenuation_db !== undefined
            ? payload.total_path_attenuation_db
            : payload.attenuation_db
        if (attenuation !== undefined) after.total_path_attenuation_db = attenuation ?? null
        this.devices.splice(idx, 1, after)
        if (topo != null) this._lastTopoByDevice[payload.id] = topo
      })
    },
    async fetchAll() {
      if (this.loading) return
      this.loading = true
      this.error = null
      try {
        const resp = await fetch('/api/devices')
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const incoming = (await resp.json()) as DeviceOutX[]
        const prevById = new Map(this.devices.map((d) => [d.id, d]))
        this.devices = incoming.map((d) => {
          const baseStatus =
            normalizeVisualStatus(d.effective_status) ||
            normalizeVisualStatus(d.status) ||
            'UNKNOWN'
          const normalized: DeviceOutX = {
            ...d,
            status: (normalizeVisualStatus(d.status) || baseStatus) as DeviceOutX['status'],
            effective_status: normalizeVisualStatus(d.effective_status) || baseStatus,
            // Map backend's attenuation_db to frontend's total_path_attenuation_db
            total_path_attenuation_db:
              ('attenuation_db' in d
                ? ((d as Record<string, unknown>).attenuation_db as number | null)
                : null) ??
              d.total_path_attenuation_db ??
              null
          }
          const prev = prevById.get(d.id)
          // preserve previously loaded interfaces
          if (prev && prev.interfaces) normalized.interfaces = prev.interfaces
          return normalized
        })
      } catch (e) {
        const err = e as Error
        this.error = err.message || String(e)
      } finally {
        this.loading = false
      }
    },
    async fetchAllWithInterfaces() {
      // Do not block on plain fetch; run interfaces fetch independently
      if (this.loadingInterfaces) return
      this.loadingInterfaces = true
      this.error = null
      try {
        const resp = await fetch('/api/devices?include_interfaces=true')
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const arr = (await resp.json()) as (DeviceOutX & { interfaces?: InterfaceOut[] })[]
        const byId = new Map(this.devices.map((d) => [d.id, d]))
        const merged: DeviceOutX[] = arr.map((d) => {
          const baseStatus =
            normalizeVisualStatus(d.effective_status) ||
            normalizeVisualStatus(d.status) ||
            'UNKNOWN'
          const normalized: DeviceOutX = {
            ...d,
            status: (normalizeVisualStatus(d.status) || baseStatus) as DeviceOutX['status'],
            effective_status: normalizeVisualStatus(d.effective_status) || baseStatus
          }
          const prev = byId.get(d.id)
          return prev ? { ...prev, ...normalized } : normalized
        })
        this.devices = merged
      } catch (e) {
        const err = e as Error
        this.error = err.message || String(e)
      } finally {
        this.loadingInterfaces = false
      }
    },
    async create(device: DeviceCreatePayload) {
      // Remove undefined/null parent_container_id to keep payload minimal
      const payload: Partial<DeviceCreatePayload> &
        Pick<DeviceCreatePayload, 'id' | 'name' | 'type'> = { ...device }
      if (payload.parent_container_id == null) delete payload.parent_container_id
      if (payload.hardware_model_id == null) delete payload.hardware_model_id
      const resp = await fetch('/api/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!resp.ok) throw new Error(`Create failed ${resp.status}`)
      const created: DeviceOutX = await resp.json()
      this.devices.push(created)
      return created
    },
    async update(
      id: string,
      patch: Partial<
        Pick<
          DeviceOutX,
          | 'name'
          | 'status'
          | 'tx_power_dbm'
          | 'sensitivity_min_dbm'
          | 'insertion_loss_db'
          | 'parent_container_id'
          | 'slot_id'
        >
      > & {
        admin_override_status?: DeviceOutX['admin_override_status']
      }
    ) {
      const resp = await fetch(`/api/devices/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch)
      })
      if (!resp.ok) {
        let msg = `Update failed ${resp.status}`
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
      const updated: DeviceOutX = await resp.json()
      const idx = this.devices.findIndex((d: DeviceOutX) => d.id === id)
      if (idx !== -1) this.devices[idx] = updated
      else this.devices.push(updated)
      return updated
    },
    async remove(id: string) {
      const resp = await fetch(`/api/devices/${id}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error(`Delete failed ${resp.status}`)
      this.devices = this.devices.filter((d: DeviceOutX) => d.id !== id)
    },
    async updateTariffOnly(id: string, tariff_id: number | null) {
      const resp = await fetch(`/api/devices/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tariff_id })
      })
      if (!resp.ok) {
        let msg = `Update failed ${resp.status}`
        try {
          msg = (await resp.json())?.detail || msg
        } catch {
          /* ignore */
        }
        throw new Error(msg)
      }
      const updated: DeviceOutX = await resp.json()
      const idx = this.devices.findIndex((d: DeviceOutX) => d.id === id)
      if (idx !== -1) this.devices[idx] = updated
      else this.devices.push(updated)
      return updated
    },
    async setOverride(id: string, status: string | null) {
      const resp = await fetch(`/api/devices/${id}/override`, {
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
      const updated: DeviceOutX = await resp.json()
      const idx = this.devices.findIndex((d: DeviceOutX) => d.id === id)
      if (idx !== -1) this.devices.splice(idx, 1, updated)
      else this.devices.push(updated)
      return updated
    },
    async provision(id: string) {
      const resp = await fetch(`/api/devices/${id}/provision`, { method: 'POST' })
      if (!resp.ok) {
        let msg = `Provision failed ${resp.status}`
        try {
          msg = (await resp.json())?.detail || msg
        } catch {
          try {
            msg = await resp.text()
          } catch {
            /* ignore */
          }
        }
        throw new Error(msg)
      }
      const body = await resp.json()
      const updated: DeviceOutX = body.device || body // endpoint returns { device }
      const idx = this.devices.findIndex((d: DeviceOutX) => d.id === id)
      if (idx !== -1) this.devices[idx] = updated
      else this.devices.push(updated)
      return updated
    },
    // Helper: immutable replace ensuring referential change only when something actually changed.
    _replaceDevice(idx: number, next: DeviceOutX) {
      const prev = this.devices[idx]
      // Shallow compare selected status-related keys; if identical keep existing reference to avoid unnecessary watchers.
      if (
        prev.status === next.status &&
        prev.effective_status === next.effective_status &&
        prev.admin_override_status === next.admin_override_status &&
        prev.signal_status === next.signal_status &&
        prev.signal_power_dbm === next.signal_power_dbm &&
        prev.signal_margin_db === next.signal_margin_db
      ) {
        return
      }
      this.devices.splice(idx, 1, next)
    }
  }
})
