<template>
    <!-- ONT cockpit: Digital Display style with signal and traffic rows -->
    <g class="ont-cockpit">
        <g transform="scale(2)">
            <!-- Frame (status-aware) -->
            <rect
x="-64" y="-34" rx="10" ry="10" width="128" height="68" fill="none" class="frame-outline"
                stroke-width="6" opacity="0.15" />
            <rect
x="-64" y="-34" rx="10" ry="10" width="128" height="68" fill="#111827" class="frame"
                stroke-width="2" />

            <!-- Header: id + LEDs -->
            <text
x="-58" y="-20" text-anchor="start" :fill="headerColor" font-size="10px"
                font-family="var(--font-mono, monospace)">{{ deviceId }}</text>
            <g transform="translate(40, -26)">
                <circle r="4" cx="-10" cy="0" :fill="ledColor('UP')" :opacity="ledOpacity('UP')" />
                <circle r="4" cx="0" cy="0" :fill="ledColor('DEGRADED')" :opacity="ledOpacity('DEGRADED')" />
                <circle r="4" cx="8" cy="0" :fill="ledColor('DOWN')" :opacity="ledOpacity('DOWN')" />
            </g>

            <!-- Rows: STATUS, RX POWER, UPSTREAM, DOWNSTREAM -->
            <g>
                <text
:x="-58" :y="-10" text-anchor="start" :fill="labelColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">STATUS:</text>
                <text
:x="58" :y="-10" text-anchor="end" :fill="statusColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">{{ status }}</text>

                <text
:x="-58" :y="4" text-anchor="start" :fill="labelColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">RX POWER:</text>
                <text
:x="58" :y="4" text-anchor="end" :fill="sigColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">{{ rxPowerText }}</text>

                <text
:x="-58" :y="18" text-anchor="start" :fill="labelColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">UPSTREAM:</text>
                <text
:x="58" :y="18" text-anchor="end" :fill="upColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">
                    <tspan>{{ upstreamParts.delivered }}</tspan>
                    <tspan v-if="upstreamParts.request" dx="3" :fill="requestColor" font-size="7px">{{ upstreamParts.request }}</tspan>
                </text>

                <text
:x="-58" :y="32" text-anchor="start" :fill="labelColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">DOWNSTREAM:</text>
                <text
:x="58" :y="32" text-anchor="end" :fill="downColor" font-size="10px"
                    font-family="var(--font-mono, monospace)">
                    <tspan>{{ downstreamParts.delivered }}</tspan>
                    <tspan v-if="downstreamParts.request" dx="3" :fill="requestColor" font-size="7px">{{ downstreamParts.request }}</tspan>
                </text>
            </g>
        </g>

        <!-- Tariff name placed below the frame -->
        <text
x="0" y="44" text-anchor="middle" fill="#b0bec5" font-size="8px"
            font-family="var(--font-mono, monospace)">
            {{ tariffName || '-' }}
        </text>
    </g>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useDevicesStore } from '../../stores/devicesStore.js'
import { useMetricsStore } from '../../stores/metricsStore.js'
import { useTariffsStore } from '../../stores/tariffsStore'
import { shapedRateParts } from '../../composables/useLinkMetricsView.js'
import { deriveNodeVisualStatus } from '../../composables/topologyCore/status.js'

const props = defineProps<{ deviceId: string }>()
const devices = useDevicesStore()
const metrics = useMetricsStore()
const tariffs = useTariffsStore()

const device = computed(() => devices.byId(props.deviceId))
const status = computed(() => device.value?.status ?? 'UNKNOWN')
const visualStatus = computed(() =>
    deriveNodeVisualStatus(status.value, (device.value as OptDev | undefined)?.signal_status)
)

// Styling/colors consistent with other Digital Display cockpits
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
    return visualStatus.value === key ? 1.0 : 0.25
}
const statusColor = computed(() => {
    if (visualStatus.value === 'UP') return '#66bb6a'
    if (visualStatus.value === 'DEGRADED') return '#ffd54f'
    if (visualStatus.value === 'DOWN') return '#ef5350'
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

// Signal (ONT-family only; neutral otherwise)
type OptDev = {
    signal_status?: 'OK' | 'WARNING' | 'CRITICAL' | 'NO_SIGNAL' | null
    signal_power_dbm?: number | null
    tariff_id?: number | null
}
const sig = computed(() => (device.value as OptDev | undefined)?.signal_status)
const rx = computed(() => (device.value as OptDev | undefined)?.signal_power_dbm)
const sigColor = computed(() => {
    switch (sig.value) {
        case 'OK':
            return '#4caf50'
        case 'WARNING':
            return '#ff9800'
        case 'CRITICAL':
            return '#d32f2f'
        case 'NO_SIGNAL':
            return '#9e9e9e'
        default:
            return '#b0bec5'
    }
})
const rxPowerText = computed(() => {
    if (rx.value === null || rx.value === undefined || Number.isNaN(rx.value)) return '— dBm'
    const v = Math.round((rx.value as number) * 10) / 10
    return `${v} dBm`
})

// Tariff
const tariffId = computed(() => (device.value as OptDev | undefined)?.tariff_id)
const tariffName = computed(() => (tariffId.value ? tariffs.byId[tariffId.value]?.name : undefined))
onMounted(() => {
    if (tariffId.value && !tariffs.byId[tariffId.value]) void tariffs.fetchAll()
})
watch(tariffId, (n) => {
    if (n && !tariffs.byId[n]) void tariffs.fetchAll()
})
</script>

<style scoped>
.ont-cockpit {
    pointer-events: all;
}

.frame-outline {
    stroke-width: 6;
    opacity: 0.15;
}

.frame {
    stroke-width: 2;
}
</style>
