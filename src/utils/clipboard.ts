/**
 * Copy text to the clipboard with a graceful fallback for older browsers
 * or contexts where the async Clipboard API is not available.
 * Returns true on success, false otherwise.
 */
export const copyTextWithFallback = async (text: string): Promise<boolean> => {
  const selection = window.getSelection();
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index).cloneRange())
    : [];
  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const restoreSelection = () => {
    if (ranges.length > 0 && ranges.every((range) => range.startContainer.isConnected && range.endContainer.isConnected)) {
      const currentSelection = window.getSelection();
      currentSelection?.removeAllRanges();
      ranges.forEach((range) => currentSelection?.addRange(range));
    }
    activeElement?.focus({ preventScroll: true });
  };

  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      restoreSelection();
      return true;
    }
  } catch {
    // fall through to the legacy textarea approach below
  }

  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.setAttribute('aria-hidden', 'true');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const copied = typeof document.execCommand === 'function' && document.execCommand('copy');
    textarea.remove();
    restoreSelection();
    return copied;
  } catch {
    restoreSelection();
    return false;
  }
};
