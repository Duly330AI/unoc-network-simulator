import { STATUS_COLORS, UTIL_OVERLOAD_COLOR, colorForUtil } from '../colorScale.js'

export type DeviceLite = {
  status?: string | null
  admin_override_status?: string | null
  provisioned?: boolean | null
}

export type LinkMetricLite = {
  utilization?: number | null
  congested?: boolean | null
}

function isDown(d?: DeviceLite | null): boolean {
  if (!d) return false
  const s = String(d.admin_override_status || d.status || '').toLowerCase()
  return s === 'down' || s === 'failed' || s === 'error'
}

function isUnprovisioned(d?: DeviceLite | null): boolean {
  if (!d) return false
  // Only treat as unprovisioned when field exists and is false
  return Object.prototype.hasOwnProperty.call(d, 'provisioned') && !d.provisioned
}

export function decideLinkColor(
  aDev?: DeviceLite | null,
  bDev?: DeviceLite | null,
  metric?: LinkMetricLite | null,
  opts?: { linkEffectiveStatus?: string | null; linkAdminOverride?: string | null }
): { stroke: string; overloaded: boolean } {
  const eff = (opts?.linkEffectiveStatus || '').toLowerCase()
  const lov = (opts?.linkAdminOverride || '').toLowerCase()
  // Link-level administrative / effective DOWN takes absolute precedence.
  if (lov === 'down' || eff === 'down' || eff === 'failed' || eff === 'error') {
    return { stroke: STATUS_COLORS.DOWN, overloaded: false }
  }
  // Endpoint administrative DOWN still forces link down (defensive — should already be captured by effective_status)
  if (isDown(aDev) || isDown(bDev)) {
    return { stroke: STATUS_COLORS.DOWN, overloaded: false }
  }
  if (metric?.congested === true) {
    return { stroke: UTIL_OVERLOAD_COLOR, overloaded: true }
  }
  const hasMetric = typeof metric?.utilization === 'number' && Number.isFinite(metric!.utilization!)
  if (!hasMetric && isUnprovisioned(aDev) && isUnprovisioned(bDev)) {
    return { stroke: STATUS_COLORS.UNKNOWN, overloaded: false }
  }
  const util = metric?.utilization ?? 0
  if (util >= 1) {
    return { stroke: UTIL_OVERLOAD_COLOR, overloaded: true }
  }
  const pct = util * 100
  return { stroke: colorForUtil(pct), overloaded: false }
}

export function computeDashForLength(length: number): number {
  // Reasonable dash size between 6 and 20 with very rough length scaling
  if (!Number.isFinite(length) || length <= 0) return 10
  return Math.max(6, Math.min(20, Math.round(length / 12)))
}
