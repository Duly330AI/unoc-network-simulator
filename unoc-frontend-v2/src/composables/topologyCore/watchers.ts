/* eslint-disable @typescript-eslint/no-explicit-any */
import { watch, type WatchStopHandle } from 'vue'
import { useMetricsStore } from '../../stores/metricsStore.js'
import { useLinkMetricsStore } from '../../stores/linkMetricsStore.js'

// Cap steady-state metric-driven full redraws; structural changes still render
// on the next animation frame. Metric ticks arrive ~1/s, so this only collapses
// bursts (device metrics + link metrics + key joins of the same tick) into one
// redraw instead of up to four.
const MIN_METRIC_REDRAW_INTERVAL_MS = 250

export function attachCanvasWatchers(
  devices: any,
  linksStore: any,
  selection: any,
  redraw: () => void,
  redrawSelection: () => void
): () => void {
  const metrics = useMetricsStore()
  const linkMetrics = useLinkMetricsStore()

  let rafId: number | null = null
  let timerId: number | null = null
  let lastRedrawAt = 0

  const runRedraw = () => {
    lastRedrawAt = Date.now()
    redraw()
  }

  // Metric ticks: coalesce into one redraw per frame, rate-limited.
  const scheduleMetricRedraw = () => {
    if (rafId != null || timerId != null) return
    const since = Date.now() - lastRedrawAt
    if (since >= MIN_METRIC_REDRAW_INTERVAL_MS) {
      rafId = window.requestAnimationFrame(() => {
        rafId = null
        runRedraw()
      })
    } else {
      timerId = window.setTimeout(() => {
        timerId = null
        rafId = window.requestAnimationFrame(() => {
          rafId = null
          runRedraw()
        })
      }, MIN_METRIC_REDRAW_INTERVAL_MS - since)
    }
  }

  // Structural/status changes: render on the next frame (skip the rate limit,
  // but still coalesce multiple triggers within one frame).
  const scheduleImmediateRedraw = () => {
    if (timerId != null) {
      window.clearTimeout(timerId)
      timerId = null
    }
    if (rafId != null) return
    rafId = window.requestAnimationFrame(() => {
      rafId = null
      runRedraw()
    })
  }

  const stops: WatchStopHandle[] = []
  stops.push(
    watch(
      () => metrics.lastTick,
      () => scheduleMetricRedraw()
    )
  )
  stops.push(
    watch(
      () => Object.keys(metrics.byId).join(','),
      () => scheduleMetricRedraw()
    )
  )
  stops.push(
    watch(
      () => linkMetrics.lastTick,
      () => scheduleMetricRedraw()
    )
  )
  stops.push(
    watch(
      () => Object.keys(linkMetrics.byId).join(','),
      () => scheduleMetricRedraw()
    )
  )
  stops.push(
    watch(
      () => devices.devices.length,
      () => scheduleImmediateRedraw()
    )
  )
  stops.push(
    watch(
      () =>
        devices.devices
          .map((d: any) => `${d.id}:${d.status || ''}:${d.signal_status || ''}`)
          .join(','),
      () => scheduleImmediateRedraw()
    )
  )
  stops.push(
    watch(
      () => linksStore.links.length,
      () => scheduleImmediateRedraw()
    )
  )
  stops.push(
    watch(
      () => linksStore.links.map((l: any) => l.id).join(','),
      () => scheduleImmediateRedraw()
    )
  )
  // IMPORTANT: Previously, link override/effective status changes performed an in-place splice
  // replacement of a single element (immutably) which does NOT change the array length nor the
  // ordered list of ids. As a result, no watcher above fired and topology colors / animations
  // stayed stale until another global trigger (metrics tick, device status change, manual refresh)
  // invoked a redraw. We concatenate the small set of reactive fields that influence visual
  // styling (status, effective_status, admin_override_status) so that any change schedules a
  // redraw deterministically.
  stops.push(
    watch(
      () =>
        linksStore.links
          .map(
            (l: any) =>
              `${l.id}:${l.status || ''}:${l.effective_status || ''}:${l.admin_override_status || ''}`
          )
          .join(','),
      () => scheduleImmediateRedraw()
    )
  )
  stops.push(
    watch(
      () => selection.lastUpdated,
      () => redrawSelection()
    )
  )
  stops.push(
    watch(
      () =>
        devices.devices
          .map(
            (d: any) =>
              `${d.id}:${d.status || ''}:${d.effective_status || ''}:${d.admin_override_status || ''}:${d.signal_status || ''}`
          )
          .join(','),
      () => scheduleImmediateRedraw()
    )
  )

  return () => {
    stops.forEach((stop) => stop())
    if (rafId != null) window.cancelAnimationFrame(rafId)
    if (timerId != null) window.clearTimeout(timerId)
  }
}
