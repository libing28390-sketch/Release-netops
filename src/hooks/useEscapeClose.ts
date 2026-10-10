import { useEffect, useRef } from 'react';

interface EscapeRegistration {
  id: symbol;
  close: () => void;
}

const registrations: EscapeRegistration[] = [];
let listening = false;

const handleEscape = (event: KeyboardEvent) => {
  if (event.key !== 'Escape' || event.defaultPrevented) return;
  const topmost = registrations[registrations.length - 1];
  if (!topmost) return;

  event.preventDefault();
  event.stopPropagation();
  topmost.close();
};

const addRegistration = (entry: EscapeRegistration) => {
  registrations.push(entry);
  if (!listening) {
    document.addEventListener('keydown', handleEscape);
    listening = true;
  }
};

const removeRegistration = (id: symbol) => {
  const index = registrations.findIndex(entry => entry.id === id);
  if (index >= 0) registrations.splice(index, 1);
  if (registrations.length === 0 && listening) {
    document.removeEventListener('keydown', handleEscape);
    listening = false;
  }
};

/** Register an open dialog for Escape. If dialogs are stacked, Escape closes only the top one. */
export const useEscapeClose = (open: boolean, onClose: () => void): void => {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open || typeof document === 'undefined') return;
    const id = Symbol('escape-close');
    addRegistration({ id, close: () => closeRef.current() });
    return () => removeRegistration(id);
  }, [open]);
};
