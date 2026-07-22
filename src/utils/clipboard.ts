/**
 * Copy text to the clipboard with a graceful fallback for older browsers
 * or contexts where the async Clipboard API is not available.
 * Returns true on success, false otherwise.
 */
export const copyTextWithFallback = async (text: string): Promise<boolean> => {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy textarea approach below
  }

  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    document.body.appendChild(textarea);
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const copied = document.execCommand('copy');
    if (textarea.parentNode === document.body) {
      document.body.removeChild(textarea);
    }
    return copied;
  } catch {
    return false;
  }
};
