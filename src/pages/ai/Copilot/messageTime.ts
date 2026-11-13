const getMessageLocale = (locale?: string): string => {
  if (locale) return locale;
  if (typeof navigator !== 'undefined' && navigator.language) return navigator.language;
  return 'zh-CN';
};

/**
 * Format a conversation message timestamp with an unambiguous date, weekday,
 * and time. Older local sessions may only have a time string, so preserve
 * that value instead of rendering "Invalid Date".
 */
export const formatMessageDateTime = (value: string | undefined, locale?: string): string => {
  const normalized = value?.trim();
  if (!normalized) return '';

  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return /^\d{1,2}:\d{2}(?::\d{2})?$/.test(normalized) ? normalized : '';
  }

  return new Intl.DateTimeFormat(getMessageLocale(locale), {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    weekday: 'long',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};
