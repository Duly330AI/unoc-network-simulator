<template>
  <!-- AON CPE cockpit: Digital Display style (no optical RX power) -->
  <g class="aon-cpe-cockpit">
    <g transform="scale(2)">
      <!-- Frame (status-aware) -->
      <rect
x="-64" y="-34" rx="10" ry="10" width="128" height="68" fill="none" class="frame-outline" stroke-width="6"
        opacity="0.15" />
      <rect x="-64" y="-34" rx="10" ry="10" width="128" height="68" fill="#111827" class="frame" stroke-width="2" />

      <!-- Header: id + LEDs -->
      <text
x="-58" y="-20" text-anchor="start" :fill="headerColor" font-size="10px"
        font-family="var(--font-mono, monospace)">{{ deviceId }}</text>
      <g transform="translate(40, -26)">
        <circle r="4" cx="-10" cy="0" :fill="ledColor('UP')" :opacity="ledOpacity('UP')" />
        <circle r="4" cx="0" cy="0" :fill="ledColor('DEGRADED')" :opacity="ledOpacity('DEGRADED')" />
        <circle r="4" cx="8" cy="0" :fill="ledColor('DOWN')" :opacity="ledOpacity('DOWN')" />
      </g>

      <!-- Rows: STATUS, UPSTREAM, DOWNSTREAM, TARIFF -->
      <g>
        <text
:x="-58" :y="-10" text-anchor="start" :fill="labelColor" font-size="10px"
          font-family="var(--font-mono, monospace)">STATUS:</text>
        <text
:x="58" :y="-10" text-anchor="end" :fill="statusColor" font-size="10px"
          font-family="var(--font-mono, monospace)">{{ status }}</text>

        <text
:x="-58" :y="4" text-anchor="start" :fill="labelColor" font-size="10px"
          font-family="var(--font-mono, monospace)">UPSTREAM:</text>
        <text
:x="58" :y="4" text-anchor="end" :fill="upColor" font-size="10px"
          font-family="var(--font-mono, monospace)">
          <tspan>{{ upstreamParts.delivered }}</tspan>
          <tspan v-if="upstreamParts.request" dx="3" :fill="requestColor" font-size="7px">{{ upstreamParts.request }}</tspan>
        </text>

        <text
:x="-58" :y="18" text-anchor="start" :fill="labelColor" font-size="10px"
          font-family="var(--font-mono, monospace)">DOWNSTREAM:</text>
        <text
:x="58" :y="18" text-anchor="end" :fill="downColor" font-size="10px"
          font-family="var(--font-mono, monospace)">
          <tspan>{{ downstreamParts.delivered }}</tspan>
          <tspan v-if="downstreamParts.request" dx="3" :fill="requestColor" font-size="7px">{{ downstreamParts.request }}</tspan>
        </text>

        <text
:x="-58" :y="32" text-anchor="start" :fill="labelColor" font-size="10px"
          font-family="var(--font-mono, monospace)">TARIFF:</text>
        <text
:x="58" :y="32" text-anchor="end" fill="#b0bec5" font-size="10px"
          font-family="var(--font-mono, monospace)">{{ tariffName || '—' }}</text>
      </g>
    </g>
  </g>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useDevicesStore } from '../../stores/devicesStore.js'
import { useMetricsStore } from '../../stores/metricsStore.js'
import { useTariffsStore } from '../../stores/tariffsStore'
import { shapedRateParts } from '../../composables/useLinkMetricsView.js'

const props = defineProps<{ deviceId: string }>()
const devices = useDevicesStore()
const metrics = useMetricsStore()
const tariffs = useTariffsStore()

const device = computed(() => devices.byId(props.deviceId))
const status = computed(() => device.value?.status ?? 'UNKNOWN')

// Styling/colors
const headerColor = '#cfd8dc'
const labelColor = '#eceff1'
const requestColor = '#c7a76a'
function ledColor(key: 'UP' | 'DEGRADED' | 'DOWN') {
  if (key === 'UP') return '#66bb6a'
  if (key === 'DEGRADED') return '#ef6c00'
  if (key === 'DOWN') return '#ef5350'
  return '#90caf9'
}
function ledOpacity(key: 'UP' | 'DEGRADED' | 'DOWN') {
  return status.value === key ? 1.0 : 0.25
}
const statusColor = computed(() => {
  if (status.value === 'UP') return '#66bb6a'
  if (status.value === 'DEGRADED') return '#ffd54f'
  if (status.value === 'DOWN') return '#ef5350'
  return '#b0bec5'
})
// Metrics: delivered stays primary; throttled demand is a muted request label.
const metric = computed(() => metrics.byId[props.deviceId])
const upColor = '#64b5f6'
const downColor = '#ffa726'
const upstreamParts = computed(() => {
  const m = metric.value
  if (!m) return { delivered: '—', request: null }
  const v = typeof m.upstream_bps === 'number' ? m.upstream_bps : m.bps / 2
  return shapedRateParts(v, m.demand_up_bps, m.scale_up)
})
const downstreamParts = computed(() => {
  const m = metric.value
  if (!m) return { delivered: '—', request: null }
  const v = typeof m.downstream_bps === 'number' ? m.downstream_bps : m.bps / 2
  return shapedRateParts(v, m.demand_down_bps, m.scale_down)
})

// Tariff
type CpeDev = { tariff_id?: number | null }
const tariffId = computed(() => (device.value as CpeDev | undefined)?.tariff_id)
const tariffName = computed(() => (tariffId.value ? tariffs.byId[tariffId.value]?.name : undefined))

onMounted(() => {
  if (tariffId.value && !tariffs.byId[tariffId.value]) void tariffs.fetchAll()
})
watch(tariffId, (n) => {
  if (n && !tariffs.byId[n]) void tariffs.fetchAll()
})
</script>

<style scoped>
.aon-cpe-cockpit {
  pointer-events: all;
}
</style>
