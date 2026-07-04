import { computed, type ComputedRef } from 'vue'
import { useLinkMetricsStore } from '../stores/linkMetricsStore.js'

export function formatPercent(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  const pct = Math.round(v * 100)
  return `${pct}%`
}

export function formatBps(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)} Gbps`
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)} Mbps`
  if (abs >= 1e3) return `${(v / 1e3).toFixed(2)} Kbps`
  return `${v.toFixed(0)} bps`
}

// Mirrors Go traffic.ThrottleScaleThreshold: a direction counts as throttled
// when shaping scaled it below this factor.
export const THROTTLE_SCALE_THRESHOLD = 0.98

// Compact form ("330M", "1.5G") so "delivered / requested" fits a cockpit row.
export function formatBpsCompact(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e9) {
    const gbps = v / 1e9
    return `${Number.isInteger(gbps) ? gbps.toFixed(0) : gbps.toFixed(1)}G`
  }
  if (abs >= 1e6) return `${Math.round(v / 1e6)}M`
  if (abs >= 1e3) return `${Math.round(v / 1e3)}K`
  return `${Math.round(v)}b`
}

// Leaf rate display: delivered stays the primary value; when shaping
// throttled the direction (scale below threshold) show "delivered / requested".
export function formatShapedRate(
  deliveredBps: number | null | undefined,
  demandBps: number | null | undefined,
  scale: number | null | undefined
): string {
  if (deliveredBps == null || Number.isNaN(deliveredBps)) return '—'
  const throttled =
    typeof scale === 'number' &&
    scale < THROTTLE_SCALE_THRESHOLD &&
    typeof demandBps === 'number' &&
    demandBps > 0
  if (throttled) {
    return `${formatBpsCompact(deliveredBps)} / ${formatBpsCompact(demandBps)}`
  }
  return formatBps(deliveredBps)
}

export function shapedRateParts(
  deliveredBps: number | null | undefined,
  demandBps: number | null | undefined,
  scale: number | null | undefined
): { delivered: string; request: string | null } {
  const hasDelivered = typeof deliveredBps === 'number' && !Number.isNaN(deliveredBps)
  const throttled =
    hasDelivered &&
    typeof scale === 'number' &&
    scale < THROTTLE_SCALE_THRESHOLD &&
    typeof demandBps === 'number' &&
    demandBps > 0

  return {
    delivered: formatBps(deliveredBps),
    request: throttled ? `req ${formatBpsCompact(demandBps)}` : null
  }
}

export function useLinkMetricsView(linkId: ComputedRef<string>) {
  const store = useLinkMetricsStore()
  const linkMetric = computed(() => store.byId[linkId.value] || null)
  const linkUtilText = computed(() => formatPercent(linkMetric.value?.utilization))
  const linkBpsText = computed(() => formatBps(linkMetric.value?.bps))

  return {
    linkMetric,
    linkUtilText,
    linkBpsText
  }
}
