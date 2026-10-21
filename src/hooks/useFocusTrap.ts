import { useLayoutEffect, useRef, type RefObject } from 'react';

interface FocusTrapRegistration {
  id: symbol;
  dialog: HTMLElement;
  previousFocus: HTMLElement | null;
}

const registrations: FocusTrapRegistration[] = [];
let listening = false;

const getFocusableElements = (dialog: HTMLElement): HTMLElement[] => Array.from(dialog.querySelectorAll<HTMLElement>(
  'button:not(:disabled), input:not([type="hidden"]):not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
)).filter((element) => (
  !element.closest('[hidden], [inert], [aria-hidden="true"], .hidden')
  && element.getAttribute('aria-disabled') !== 'true'
));

const handleDocumentKeyDown = (event: KeyboardEvent) => {
  if (event.key !== 'Tab' || event.defaultPrevented) return;
  const topmost = registrations[registrations.length - 1];
  if (!topmost) return;

  const focusable = getFocusableElements(topmost.dialog);
  if (focusable.length === 0) {
    event.preventDefault();
    topmost.dialog.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  if (event.shiftKey && (activeElement === first || !topmost.dialog.contains(activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (activeElement === last || !topmost.dialog.contains(activeElement))) {
    event.preventDefault();
    first.focus();
  }
};

const removeRegistration = (id: symbol) => {
  const index = registrations.findIndex((entry) => entry.id === id);
  if (index < 0) return;
  const wasTopmost = index === registrations.length - 1;
  const [entry] = registrations.splice(index, 1);
  if (registrations.length === 0 && listening) {
    document.removeEventListener('keydown', handleDocumentKeyDown);
    listening = false;
  }
  if (wasTopmost && entry.previousFocus?.isConnected) {
    const restoreFocus = () => {
      if (!entry.previousFocus?.isConnected) return;
      const nextTopmost = registrations[registrations.length - 1];
      if (!nextTopmost || nextTopmost.dialog.contains(entry.previousFocus)) entry.previousFocus.focus();
    };
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(restoreFocus);
    } else {
      setTimeout(restoreFocus, 0);
    }
  }
};

/** Focus the topmost open dialog, contain Tab navigation, and restore focus when it closes. */
export const useFocusTrap = <T extends HTMLElement>(
  dialogRef: RefObject<T | null>,
  enabled: boolean,
  initialFocusSelector?: string,
  returnFocusRef?: RefObject<HTMLElement | null>,
): void => {
  const wasEnabledRef = useRef(false);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  if (enabled && !wasEnabledRef.current && typeof document !== 'undefined') {
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }
  wasEnabledRef.current = enabled;

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!enabled || !dialog || typeof document === 'undefined') return;

    const registration: FocusTrapRegistration = {
      id: Symbol('focus-trap'),
      dialog,
      previousFocus: returnFocusRef?.current || previousFocusRef.current,
    };
    registrations.push(registration);
    if (!listening) {
      document.addEventListener('keydown', handleDocumentKeyDown);
      listening = true;
    }

    const focusable = getFocusableElements(dialog);
    const preferred = initialFocusSelector
      ? dialog.querySelector<HTMLElement>(initialFocusSelector)
      : null;
    const preferredIsFocusable = preferred && focusable.includes(preferred);
    (preferredIsFocusable ? preferred : focusable[0] || dialog).focus();

    return () => removeRegistration(registration.id);
  }, [dialogRef, enabled, initialFocusSelector, returnFocusRef]);
};
