<template>
  <div class="modal-backdrop">
    <div class="modal">
      <h4>{{ initial ? 'Edit Tariff' : 'New Tariff' }}</h4>
      <div class="form-grid">
        <label for="name">Name</label>
        <input id="name" v-model.trim="name" />
        <div v-if="nameError" class="field-error">{{ nameError }}</div>

        <label for="down">Down (Mbps)</label>
  <input id="down" v-model.number="down" type="number" min="0" step="0.1" />
        <div v-if="downError" class="field-error">{{ downError }}</div>

        <label for="up">Up (Mbps)</label>
  <input id="up" v-model.number="up" type="number" min="0" step="0.1" />
        <div v-if="upError" class="field-error">{{ upError }}</div>

        <label for="tech">Technology</label>
        <select id="tech" v-model="technology">
          <option disabled value="">– wählen –</option>
          <option value="GPON">GPON (ONT / Business ONT)</option>
          <option value="AON">AON (AON CPE)</option>
        </select>
        <div v-if="techError" class="field-error">{{ techError }}</div>
      </div>
      <div v-if="error" class="error">{{ error }}</div>
      <div class="actions">
        <button class="btn" :disabled="saving" @click="$emit('cancel')">Cancel</button>
        <button class="btn primary" :disabled="!canSubmit || saving" @click="submit">{{ saving ? 'Saving…' : 'Save' }}</button>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Tariff } from '../../stores/tariffsStore'

const props = defineProps<{ initial: Tariff|null; saving: boolean; error: string|null }>()
const emit = defineEmits<{ (e:'cancel'):void; (e:'submit', payload:{ name:string; max_down_mbps:number; max_up_mbps:number; technology:'GPON'|'AON' }):void }>()

const name = ref('')
const down = ref<number|undefined>(undefined)
const up = ref<number|undefined>(undefined)
const technology = ref<'GPON'|'AON'|''>('')

watch(() => props.initial, (t)=>{
  name.value = t?.name || ''
  down.value = t?.max_down_mbps
  up.value = t?.max_up_mbps
  technology.value = t?.technology ?? ''
}, { immediate:true })

const nameError = computed(()=> !name.value.trim() ? 'Name is required' : '')
const downError = computed(()=> down.value==null || down.value<0 ? 'Down must be ≥ 0' : '')
const upError = computed(()=> up.value==null || up.value<0 ? 'Up must be ≥ 0' : '')
// Required: tariffs without technology never show up in end-device selectors
const techError = computed(()=> !technology.value ? 'Technology is required (GPON or AON)' : '')
const canSubmit = computed(()=> !nameError.value && !downError.value && !upError.value && !techError.value)

function submit(){
  if(!canSubmit.value) return
  emit('submit', {
    name: name.value.trim(),
    max_down_mbps: down.value!,
    max_up_mbps: up.value!,
    technology: technology.value as 'GPON'|'AON'
  })
}
</script>
<style scoped>
.modal-backdrop{ position:fixed; inset:0; background:rgba(0,0,0,.5); display:grid; place-items:center; }
.modal{ background:#1f2937; border:1px solid #374151; color:#eee; width:min(560px, 92vw); border-radius:8px; padding:1rem; box-shadow:0 10px 24px rgba(0,0,0,.5); }
.form-grid{ display:grid; grid-template-columns: 160px 1fr; gap:.35rem .5rem; align-items:center; }
.form-grid input, .form-grid select{ background:#111827; color:#e5e7eb; border:1px solid #374151; padding:.3rem .45rem; border-radius:4px; }
.actions{ display:flex; justify-content:flex-end; gap:.5rem; margin-top: .75rem; }
.btn{ background:#374151; color:#e5e7eb; border:0; padding:.35rem .7rem; border-radius:4px; cursor:pointer; }
.btn.primary{ background:#2563eb; }
.btn:disabled{ opacity:.6; cursor:not-allowed; }
.field-error{ grid-column: 2 / span 1; color:#fca5a5; font-size:.72rem; margin-top:-.25rem; }
.error{ color:#f87171; margin-top:.5rem; }
</style>
