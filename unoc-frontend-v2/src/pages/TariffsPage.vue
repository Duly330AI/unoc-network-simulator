<template>
  <div class="tariffs-page">
    <div class="toolbar">
      <h3>Tariffs</h3>
      <button class="btn" @click="openCreate">New Tariff</button>
      <button class="btn" :disabled="store.loading" @click="reload">Reload</button>
    </div>
    <div v-if="store.error" class="error">{{ store.error }}</div>
    <table v-if="rows.length" class="tbl">
      <thead>
        <tr>
          <th>Name</th>
          <th>Down (Mbps)</th>
          <th>Up (Mbps)</th>
          <th>Technology</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in rows" :key="t.id">
          <td>{{ t.name }}</td>
          <td>{{ t.max_down_mbps }}</td>
          <td>{{ t.max_up_mbps }}</td>
          <td :class="{ 'tech-missing': !t.technology }">{{ t.technology || '⚠ fehlt' }}</td>
          <td class="actions">
            <button class="btn sm" @click="openEdit(t)">Edit</button>
            <button class="btn sm danger" @click="confirmDelete(t)">Delete</button>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else-if="!store.loading && !store.error" class="empty">No tariffs yet</div>

    <TariffFormModal
      v-if="showModal"
      :initial="editing"
      :saving="saving"
      :error="modalError"
      @cancel="closeModal"
      @submit="onSubmit"
    />
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useTariffsStore, type Tariff } from '../stores/tariffsStore'
import TariffFormModal from '../components/tariffs/TariffFormModal.vue'

const store = useTariffsStore()
const rows = computed(()=> store.allSorted)

onMounted(()=>{ void store.fetchAll() })
const reload = ()=> store.fetchAll()

const showModal = ref(false)
const saving = ref(false)
const modalError = ref<string|null>(null)
const editing = ref<Tariff|null>(null)

function openCreate(){ editing.value = null; modalError.value = null; showModal.value = true }
function openEdit(t: Tariff){ editing.value = t; modalError.value = null; showModal.value = true }
function closeModal(){ if(saving.value) return; showModal.value = false }

async function confirmDelete(t: Tariff){
  if(!confirm(`Delete tariff ${t.name}?`)) return
  try{ await store.remove(t.id) } catch(e){ alert((e as Error).message) }
}

async function onSubmit(payload: { name: string; max_down_mbps: number; max_up_mbps: number; technology: 'GPON'|'AON' }){
  saving.value = true
  modalError.value = null
  try{
    if(editing.value){ await store.update(editing.value.id, payload) }
    else{ await store.create(payload) }
    showModal.value = false
  }catch(e){ modalError.value = (e as Error).message }
  finally{ saving.value = false }
}
</script>
<style scoped>
.tariffs-page{ padding:1rem; color:#eee; font-size:.8rem; }
.toolbar{ display:flex; align-items:center; gap:.5rem; margin-bottom:.5rem; }
.btn{ background:#333; color:#ccc; border:0; padding:.35rem .7rem; border-radius:4px; cursor:pointer; }
.btn:hover{ background:#444; color:#fff; }
.btn.sm{ padding:.25rem .5rem; font-size:.7rem; }
.btn.danger{ background:#5a1c1c; }
.tbl{ width:100%; border-collapse:collapse; }
.tbl th,.tbl td{ border-bottom:1px solid #2d2d2d; padding:.4rem .5rem; text-align:left; }
.actions{ display:flex; gap:.25rem; }
.empty{ opacity:.6; font-style:italic; }
.tech-missing{ color:#fbbf24; }
.error{ color:#f87171; margin:.5rem 0; }
</style>
