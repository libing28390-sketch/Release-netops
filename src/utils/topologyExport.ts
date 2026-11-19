const INVALID_FILENAME_CHARS = /[<>:"/\\|?*\u0000-\u001f]/g;
const TOPOLOGY_EXPORT_TARGET_LONG_EDGE = 4096;
const TOPOLOGY_EXPORT_MIN_PIXEL_RATIO = 3;
const TOPOLOGY_EXPORT_MAX_PIXEL_RATIO = 5;
const TOPOLOGY_EXPORT_MAX_PIXELS = 16_000_000;
const TOPOLOGY_EXPORT_MAX_CANVAS_DIMENSION = 32_767;
const TOPOLOGY_EXPORT_CONTENT_PADDING = 72;
const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const XLINK_NAMESPACE = 'http://www.w3.org/1999/xlink';

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

type Matrix2D = { a: number; b: number; c: number; d: number; e: number; f: number };
type ExportBounds = { minX: number; minY: number; maxX: number; maxY: number };

const invertMatrix = (matrix: Matrix2D): Matrix2D | null => {
  const determinant = matrix.a * matrix.d - matrix.b * matrix.c;
  if (!Number.isFinite(determinant) || Math.abs(determinant) < Number.EPSILON) return null;
  return {
    a: matrix.d / determinant,
    b: -matrix.b / determinant,
    c: -matrix.c / determinant,
    d: matrix.a / determinant,
    e: (matrix.c * matrix.f - matrix.d * matrix.e) / determinant,
    f: (matrix.b * matrix.e - matrix.a * matrix.f) / determinant,
  };
};

const multiplyMatrices = (left: Matrix2D, right: Matrix2D): Matrix2D => ({
  a: left.a * right.a + left.c * right.b,
  b: left.b * right.a + left.d * right.b,
  c: left.a * right.c + left.c * right.d,
  d: left.b * right.c + left.d * right.d,
  e: left.a * right.e + left.c * right.f + left.e,
  f: left.b * right.e + left.d * right.f + left.f,
});

const includeTransformedBounds = (
  union: ExportBounds | null,
  box: DOMRect | SVGRect,
  matrix: Matrix2D,
): ExportBounds | null => {
  const corners = [
    { x: box.x, y: box.y },
    { x: box.x + box.width, y: box.y },
    { x: box.x, y: box.y + box.height },
    { x: box.x + box.width, y: box.y + box.height },
  ].map((point) => ({
    x: matrix.a * point.x + matrix.c * point.y + matrix.e,
    y: matrix.b * point.x + matrix.d * point.y + matrix.f,
  }));
  const points = corners.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (points.length !== 4) return union;
  const minX = Math.min(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxX = Math.max(...points.map((point) => point.x));
  const maxY = Math.max(...points.map((point) => point.y));
  if (maxX <= minX || maxY <= minY) return union;
  if (!union) return { minX, minY, maxX, maxY };
  return {
    minX: Math.min(union.minX, minX),
    minY: Math.min(union.minY, minY),
    maxX: Math.max(union.maxX, maxX),
    maxY: Math.max(union.maxY, maxY),
  };
};

const getWorldBounds = (world: SVGGElement): ExportBounds | null => {
  let bounds: ExportBounds | null = null;
  try {
    const worldMatrix = world.getCTM() as Matrix2D | null;
    if (!worldMatrix) return null;
    const inverseWorldMatrix = invertMatrix(worldMatrix);
    if (!inverseWorldMatrix) return null;
    Array.from(world.children).forEach((child) => {
      if (child.classList.contains('topology-grid-background')) return;
      const graphic = child as SVGGraphicsElement;
      const box = graphic.getBBox();
      if (!Number.isFinite(box.x) || !Number.isFinite(box.y)
        || !Number.isFinite(box.width) || !Number.isFinite(box.height)
        || box.width <= 0 || box.height <= 0) return;
      const childMatrix = graphic.getCTM() as Matrix2D | null;
      if (!childMatrix) return;
      bounds = includeTransformedBounds(bounds, box, multiplyMatrices(inverseWorldMatrix, childMatrix));
    });
  } catch {
    return null;
  }
  return bounds;
};

const blobAsDataUrl = async (blob: Blob): Promise<string> => {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  const extensionMimeType = blob.type || 'application/octet-stream';
  return `data:${extensionMimeType};base64,${btoa(binary)}`;
};

const inlineLocalImages = async (svg: SVGSVGElement): Promise<void> => {
  if (typeof window === 'undefined' || typeof fetch === 'undefined') return;
  const urlCache = new Map<string, Promise<string | null>>();
  const images = Array.from(svg.querySelectorAll('image'));
  await Promise.all(images.map(async (image) => {
    const originalUrl = image.getAttribute('href') || image.getAttributeNS(XLINK_NAMESPACE, 'href');
    if (!originalUrl || originalUrl.startsWith('data:') || originalUrl.startsWith('blob:')) return;
    let resolvedUrl: URL;
    try {
      resolvedUrl = new URL(originalUrl, document.baseURI);
    } catch {
      return;
    }
    if (!['http:', 'https:'].includes(resolvedUrl.protocol) || resolvedUrl.origin !== window.location.origin) return;

    let dataUrlRequest = urlCache.get(resolvedUrl.href);
    if (!dataUrlRequest) {
      dataUrlRequest = fetch(resolvedUrl.href, { credentials: 'same-origin' })
        .then((response) => response.ok ? response.blob() : null)
        .then((blob) => blob ? blobAsDataUrl(blob) : null)
        .catch(() => null);
      urlCache.set(resolvedUrl.href, dataUrlRequest);
    }
    const dataUrl = await dataUrlRequest;
    if (!dataUrl) return;
    image.setAttribute('href', dataUrl);
    if (image.hasAttributeNS(XLINK_NAMESPACE, 'href')) {
      image.setAttributeNS(XLINK_NAMESPACE, 'xlink:href', dataUrl);
    }
  }));
};

/** Crop a cloned topology SVG to its visible world content and inline local device icons. */
export const prepareTopologySvgExport = async (
  svg: SVGSVGElement,
): Promise<{ source: string; width: number; height: number } | null> => {
  const exportSvg = svg.cloneNode(true) as SVGSVGElement;
  const world = svg.querySelector<SVGGElement>('.topology-world');
  let width = Math.max(1, Number(svg.clientWidth) || Number(svg.getAttribute('width')) || 1);
  let height = Math.max(1, Number(svg.clientHeight) || Number(svg.getAttribute('height')) || 1);

  if (world) {
    const bounds = getWorldBounds(world);
    if (bounds) {
      const minX = Math.floor(bounds.minX - TOPOLOGY_EXPORT_CONTENT_PADDING);
      const minY = Math.floor(bounds.minY - TOPOLOGY_EXPORT_CONTENT_PADDING);
      width = Math.ceil(bounds.maxX + TOPOLOGY_EXPORT_CONTENT_PADDING - minX);
      height = Math.ceil(bounds.maxY + TOPOLOGY_EXPORT_CONTENT_PADDING - minY);
      const exportWorld = exportSvg.querySelector<SVGGElement>('.topology-world');
      exportWorld?.removeAttribute('transform');
      exportWorld?.querySelectorAll('.topology-grid-background').forEach((element) => element.remove());
      const background = exportSvg.querySelector<SVGRectElement>('.topology-canvas-background');
      background?.setAttribute('x', String(minX));
      background?.setAttribute('y', String(minY));
      background?.setAttribute('width', String(width));
      background?.setAttribute('height', String(height));
      exportSvg.setAttribute('viewBox', `${minX} ${minY} ${width} ${height}`);
      exportSvg.setAttribute('width', String(width));
      exportSvg.setAttribute('height', String(height));
    }
  }

  await inlineLocalImages(exportSvg);
  const source = new XMLSerializer().serializeToString(exportSvg);
  let serialized = source;
  if (!serialized.match(/^<svg[^>]+xmlns="http:\/\/www\.w3\.org\/2000\/svg"/)) {
    serialized = serialized.replace(/^<svg/, `<svg xmlns="${SVG_NAMESPACE}"`);
  }
  if (!serialized.match(/^<svg[^>]+xmlns:xlink="http:\/\/www\.w3\.org\/1999\/xlink"/)) {
    serialized = serialized.replace(/^<svg/, `<svg xmlns:xlink="${XLINK_NAMESPACE}"`);
  }
  return { source: serialized, width, height };
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
  const longEdge = Math.max(sourceWidth, sourceHeight);
  const dimensionSafeRatio = TOPOLOGY_EXPORT_MAX_CANVAS_DIMENSION / longEdge;
  const safeRatio = Math.min(preferredRatio, memorySafeRatio, dimensionSafeRatio);
  const minimumRatio = sourcePixels <= TOPOLOGY_EXPORT_MAX_PIXELS && longEdge <= TOPOLOGY_EXPORT_MAX_CANVAS_DIMENSION
    ? 1
    : Number.EPSILON;
  return Math.max(minimumRatio, safeRatio);
};
