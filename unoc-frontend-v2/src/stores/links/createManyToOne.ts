import { useDevicesStore } from '../devicesStore.js'
import type { Link } from './types.js'
import { computeSelections, isContainerType, phase1GuardsOk } from './create/selection.js'

type LinksStoreApi = {
  links: Link[]
  hasLinkBetween: (a: string, b: string) => boolean
}

export interface BatchCreateResult {
  ok: number
  fail: number
  errors: string[]
}

interface BatchLinkPayload {
  id: string
  a_interface_id: string
  b_interface_id: string
  kind: string
  status: string
}

interface BatchCreatedLink extends Partial<Link> {
  [k: string]: unknown
}

interface BatchResponseBody {
  created?: BatchCreatedLink[]
  failed?: Array<{ link_id?: string; error?: string }>
}

// Same device/id derivation as creator.ts and backend canonical_link_id
const deriveDeviceId = (iid: string) => (iid.endsWith('-if0') ? iid.slice(0, -4) : iid)

function canonicalLinkId(aIface: string, bIface: string): string {
  const da = deriveDeviceId(aIface)
  const db = deriveDeviceId(bIface)
  return da <= db ? `${da}__${db}` : `${db}__${da}`
}

async function postBatch(payloads: BatchLinkPayload[]): Promise<Response> {
  return fetch('/api/links/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ links: payloads })
  })
}

function pushCreated(store: LinksStoreApi, created: BatchCreatedLink[]): number {
  let pushed = 0
  for (const linkRaw of created) {
    if (!linkRaw.id || store.links.find((l) => l.id === linkRaw.id)) continue
    if (!linkRaw.a_device_id || !linkRaw.b_device_id) {
      linkRaw.a_device_id = deriveDeviceId(linkRaw.a_interface_id || '')
      linkRaw.b_device_id = deriveDeviceId(linkRaw.b_interface_id || '')
    }
    store.links.push(linkRaw as Link)
    pushed++
  }
  return pushed
}

/**
 * Create links from many source devices to one target device via a single
 * POST /api/links/batch request (one transaction + one recompute pass on the
 * backend) instead of N parallel POST /api/links calls.
 */
export async function createManyToOne(
  store: LinksStoreApi,
  sourceDeviceIds: string[],
  targetDeviceId: string
): Promise<BatchCreateResult> {
  const result: BatchCreateResult = { ok: 0, fail: 0, errors: [] }
  const devStore = useDevicesStore()

  const sources = Array.from(new Set(sourceDeviceIds)).filter((id) => id !== targetDeviceId)
  if (!sources.length) return result

  // Ensure interfaces are loaded for intelligent selection
  const needIfaces =
    !devStore.byId(targetDeviceId)?.interfaces ||
    sources.some((id) => !devStore.byId(id)?.interfaces)
  if (needIfaces) {
    try {
      await devStore.fetchAllWithInterfaces()
    } catch {
      /* non-fatal: fallback to -if0 */
    }
  }

  const targetDev = devStore.byId(targetDeviceId)
  if (isContainerType(targetDev?.type)) {
    result.fail = sources.length
    result.errors.push('Container (POP/CORE_SITE) kann kein Link-Ziel sein')
    return result
  }

  // Thread a growing "virtual" link list through the per-pair interface
  // selection so successive sources do not pick the same free port on the
  // shared target device.
  const virtualLinks: Link[] = [...(store.links as Link[])]
  const payloads: BatchLinkPayload[] = []

  for (const sid of sources) {
    const srcDev = devStore.byId(sid)
    const srcType = String(srcDev?.type || '')
    const tgtType = String(targetDev?.type || '')
    if (isContainerType(srcDev?.type)) {
      result.fail++
      result.errors.push(`${sid}: Container-Endpunkt nicht erlaubt`)
      continue
    }
    if (srcType === 'ODF' && tgtType === 'ODF') {
      result.fail++
      result.errors.push(`${sid}: ODF↔ODF-Kaskaden nicht erlaubt`)
      continue
    }
    if (!phase1GuardsOk(virtualLinks, devStore, sid, targetDeviceId, srcType, tgtType)) {
      result.fail++
      result.errors.push(`${sid}: Verbindungsregel verletzt`)
      continue
    }
    const ordered = [sid, targetDeviceId].sort()
    if (store.hasLinkBetween(ordered[0], ordered[1])) continue

    const { aIface, bIface } = computeSelections(devStore, virtualLinks, sid, targetDeviceId)
    payloads.push({
      id: canonicalLinkId(aIface, bIface),
      a_interface_id: aIface,
      b_interface_id: bIface,
      kind: 'FIBER',
      status: 'UP'
    })
    virtualLinks.push({
      id: canonicalLinkId(aIface, bIface),
      a_interface_id: aIface,
      b_interface_id: bIface,
      a_device_id: sid,
      b_device_id: targetDeviceId,
      status: 'UP',
      kind: 'FIBER'
    })
  }

  if (!payloads.length) return result

  let resp: Response
  try {
    resp = await postBatch(payloads)
  } catch (e) {
    result.fail += payloads.length
    result.errors.push(`Batch-Request fehlgeschlagen: ${(e as Error).message || e}`)
    return result
  }

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      detail = ((await resp.json()) as { detail?: string })?.detail || detail
    } catch {
      /* ignore */
    }
    result.fail += payloads.length
    result.errors.push(`Batch fehlgeschlagen: ${detail}`)
    return result
  }

  const body = (await resp.json()) as BatchResponseBody
  let created = body.created || []
  let failed = body.failed || []

  // The backend aborts the whole batch when any link fails validation
  // (created=[] + per-link errors). Retry once with the valid subset so a
  // single bad pair does not block the rest.
  if (!created.length && failed.length && failed.length < payloads.length) {
    const failedIds = new Set(failed.map((f) => f.link_id))
    const retryPayloads = payloads.filter((p) => !failedIds.has(p.id))
    if (retryPayloads.length) {
      try {
        const retryResp = await postBatch(retryPayloads)
        if (retryResp.ok) {
          const retryBody = (await retryResp.json()) as BatchResponseBody
          created = retryBody.created || []
          failed = [...failed, ...(retryBody.failed || [])]
        }
      } catch {
        /* keep original failure reporting */
      }
    }
  }

  result.ok += pushCreated(store, created)
  result.fail += failed.length
  for (const f of failed) result.errors.push(`${f.link_id || '?'}: ${f.error || 'unbekannt'}`)
  return result
}
