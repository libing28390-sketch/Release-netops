export function areAllVisiblePrefixIdsSelected(
  selectedIds: ReadonlySet<string>,
  visibleIds: string[],
): boolean {
  return visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
}

/** Toggle only the current visible page while keeping selections from other pages. */
export function toggleVisiblePrefixSelection(
  selectedIds: ReadonlySet<string>,
  visibleIds: string[],
): Set<string> {
  const next = new Set(selectedIds);
  const allVisibleSelected = areAllVisiblePrefixIdsSelected(selectedIds, visibleIds);
  for (const id of new Set(visibleIds)) {
    if (allVisibleSelected) next.delete(id);
    else next.add(id);
  }
  return next;
}
