import { defineStore } from 'pinia'

export interface Tariff {
  id: number
  name: string
  max_up_mbps: number
  max_down_mbps: number
  technology?: 'GPON' | 'AON' | null
}

interface State {
  byId: Record<number, Tariff>
  loading: boolean
  error: string | null
}

export const useTariffsStore = defineStore('tariffs', {
  state: (): State => ({ byId: {}, loading: false, error: null }),
  getters: {
    allSorted(state): Tariff[] {
      return Object.values(state.byId).sort((a, b) => a.name.localeCompare(b.name))
    }
  },
  actions: {
    async fetchAll() {
      if (this.loading) return
      this.loading = true
      this.error = null
      try {
        const resp = await fetch('/api/tariffs')
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const arr = (await resp.json()) as Tariff[]
        const map: Record<number, Tariff> = {}
        for (const t of arr) map[t.id] = t
        this.byId = map
      } catch (e) {
        const err = e as Error
        this.error = err.message || String(e)
      } finally {
        this.loading = false
      }
    },
    async create(payload: Pick<Tariff, 'name' | 'max_up_mbps' | 'max_down_mbps' | 'technology'>) {
      const resp = await fetch('/api/tariffs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!resp.ok) {
        let msg = `Create failed ${resp.status}`
        try {
          msg = (await resp.json())?.detail || msg
        } catch {
          /* ignore */
        }
        throw new Error(msg)
      }
      const created = (await resp.json()) as Tariff
      this.byId[created.id] = created
      return created
    },
    async update(
      id: number,
      patch: Partial<Pick<Tariff, 'name' | 'max_up_mbps' | 'max_down_mbps' | 'technology'>>
    ) {
      const resp = await fetch(`/api/tariffs/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch)
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
      const updated = (await resp.json()) as Tariff
      this.byId[updated.id] = updated
      return updated
    },
    async remove(id: number) {
      const resp = await fetch(`/api/tariffs/${id}`, { method: 'DELETE' })
      if (!resp.ok) {
        throw new Error(`Delete failed ${resp.status}`)
      }
      delete this.byId[id]
    }
  }
})
