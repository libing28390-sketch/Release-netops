const INVALID_FILENAME_CHARS = /[<>:"/\\|?*\u0000-\u001f]/g;
const TOPOLOGY_EXPORT_TARGET_LONG_EDGE = 4096;
const TOPOLOGY_EXPORT_MIN_PIXEL_RATIO = 3;
const TOPOLOGY_EXPORT_MAX_PIXEL_RATIO = 5;
const TOPOLOGY_EXPORT_MAX_PIXELS = 16_000_000;

export const sanitizeTopologyFilenamePart = (value: unknown): string => {
  const normalized = String(value ?? '')
    .trim()
    .replace(INVALID_FILENAME_CHARS, '-')
    .replace(/\s+/g, '_')
    .replace(/[. ]+$/g, '');
  return normalized || 'all-sites';
};

export const getTopologyExportTimestamp = (date = new Date()): string => {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
};

export const buildTopologyExportFilename = (siteLabel: unknown, extension: string): string => {
  const safeExtension = String(extension || 'png').replace(/[^a-z0-9]/gi, '') || 'png';
  return `${sanitizeTopologyFilenamePart(siteLabel)}-拓扑图-${getTopologyExportTimestamp()}.${safeExtension}`;
};

/**
 * Keep topology exports sharp enough for 4K viewing while bounding the bitmap
 * size so a very large graph does not exhaust the browser canvas memory.
 */
export const getTopologyExportPixelRatio = (width: number, height: number): number => {
  const sourceWidth = Math.max(1, Number(width) || 1);
  const sourceHeight = Math.max(1, Number(height) || 1);
  const sourcePixels = sourceWidth * sourceHeight;
  const targetRatio = TOPOLOGY_EXPORT_TARGET_LONG_EDGE / Math.max(sourceWidth, sourceHeight);
  const preferredRatio = Math.min(
    TOPOLOGY_EXPORT_MAX_PIXEL_RATIO,
    Math.max(TOPOLOGY_EXPORT_MIN_PIXEL_RATIO, targetRatio),
  );
  const memorySafeRatio = Math.sqrt(TOPOLOGY_EXPORT_MAX_PIXELS / sourcePixels);
  return Math.max(1, Math.min(preferredRatio, memorySafeRatio));
};
