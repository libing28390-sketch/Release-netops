export const hasTextSelection = (selection: Selection | null): boolean => (
  // isCollapsed is O(1); selection.toString() serializes the whole range and
  // made per-token streaming and drag-select jank on long answers.
  Boolean(selection && selection.rangeCount > 0 && !selection.isCollapsed)
);

export const cloneSelectionWithin = (selection: Selection | null, root: Node): Range | null => {
  if (!selection || !hasTextSelection(selection)) return null;

  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
  return range.cloneRange();
};

export const restoreSelection = (range: Range | null): boolean => {
  if (!range || !range.startContainer.isConnected || !range.endContainer.isConnected) return false;

  const selection = window.getSelection();
  if (!selection) return false;

  try {
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
  } catch {
    return false;
  }
};
