/**
 * Lightweight class name utility.
 * Filters falsy values and joins remaining class strings.
 * Drop-in replacement for clsx when tailwind-merge is not needed.
 */
export function cn(...inputs: (string | boolean | undefined | null)[]): string {
  return inputs.filter(Boolean).join(' ');
}
