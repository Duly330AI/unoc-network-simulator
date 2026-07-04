export type SortableInterfaceSummary = {
  id?: string
  name?: string
}

const naturalPortCollator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base'
})

function portSortKey(summary: SortableInterfaceSummary): string {
  return summary.name ?? summary.id ?? ''
}

export function compareInterfaceSummary(
  a: SortableInterfaceSummary,
  b: SortableInterfaceSummary
): number {
  return naturalPortCollator.compare(portSortKey(a), portSortKey(b))
}

export function sortInterfaceSummaries<T extends SortableInterfaceSummary>(list: T[]): T[] {
  return list
    .map((item, index) => ({ item, index }))
    .sort((a, b) => compareInterfaceSummary(a.item, b.item) || a.index - b.index)
    .map(({ item }) => item)
}
