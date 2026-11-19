import { afterEach, describe, expect, it, vi } from 'vitest';
import { getTopologyExportPixelRatio, prepareTopologySvgExport } from './topologyExport';

const svgNamespace = 'http://www.w3.org/2000/svg';
const identity = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };
const translatedWorld = { a: 2, b: 0, c: 0, d: 2, e: 20, f: 40 };

const appendImage = (parent: Element, href: string) => {
  const image = document.createElementNS(svgNamespace, 'image');
  image.setAttribute('href', href);
  parent.appendChild(image);
  return image;
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('prepareTopologySvgExport', () => {
  it('crops to world graphics, removes the zoom and grid, and keeps the current SVG visibility', async () => {
    const svg = document.createElementNS(svgNamespace, 'svg');
    svg.setAttribute('width', '800');
    svg.setAttribute('height', '600');
    const background = document.createElementNS(svgNamespace, 'rect');
    background.setAttribute('class', 'topology-canvas-background');
    svg.appendChild(background);

    const world = document.createElementNS(svgNamespace, 'g');
    world.setAttribute('class', 'topology-world');
    world.setAttribute('transform', 'translate(20 40) scale(2)');
    Object.defineProperty(world, 'getCTM', { value: () => translatedWorld });
    svg.appendChild(world);

    const grid = document.createElementNS(svgNamespace, 'rect');
    grid.setAttribute('class', 'topology-grid-background');
    Object.defineProperty(grid, 'getBBox', { value: () => ({ x: -2000, y: -2000, width: 4000, height: 4000 }) });
    world.appendChild(grid);

    const content = document.createElementNS(svgNamespace, 'g');
    Object.defineProperty(content, 'getBBox', { value: () => ({ x: 100, y: 200, width: 400, height: 300 }) });
    Object.defineProperty(content, 'getCTM', { value: () => translatedWorld });
    const hiddenLabel = document.createElementNS(svgNamespace, 'g');
    hiddenLabel.setAttribute('class', 'topology-port-label-group');
    hiddenLabel.setAttribute('display', 'none');
    content.appendChild(hiddenLabel);
    world.appendChild(content);

    const result = await prepareTopologySvgExport(svg);

    expect(result).not.toBeNull();
    expect(result?.width).toBe(544);
    expect(result?.height).toBe(444);
    const exportedSvg = new DOMParser().parseFromString(result!.source, 'image/svg+xml');
    const exportedWorld = exportedSvg.querySelector('.topology-world');
    expect(exportedSvg.documentElement.getAttribute('viewBox')).toBe('28 128 544 444');
    expect(exportedWorld?.hasAttribute('transform')).toBe(false);
    expect(exportedWorld?.querySelector('.topology-grid-background')).toBeNull();
    expect(exportedSvg.querySelector('.topology-port-label-group')?.getAttribute('display')).toBe('none');
    expect(exportedSvg.querySelector('.topology-canvas-background')?.getAttribute('x')).toBe('28');
    expect(exportedSvg.querySelector('.topology-canvas-background')?.getAttribute('y')).toBe('128');
    expect(exportedSvg.querySelector('.topology-canvas-background')?.getAttribute('width')).toBe('544');
    expect(exportedSvg.querySelector('.topology-canvas-background')?.getAttribute('height')).toBe('444');
  });

  it('inlines and deduplicates same-origin image assets while leaving external and data URLs alone', async () => {
    const svg = document.createElementNS(svgNamespace, 'svg');
    svg.setAttribute('width', '800');
    svg.setAttribute('height', '600');
    const world = document.createElementNS(svgNamespace, 'g');
    world.setAttribute('class', 'topology-world');
    Object.defineProperty(world, 'getCTM', { value: () => identity });
    svg.appendChild(world);
    const content = document.createElementNS(svgNamespace, 'g');
    Object.defineProperty(content, 'getBBox', { value: () => ({ x: 10, y: 20, width: 80, height: 60 }) });
    Object.defineProperty(content, 'getCTM', { value: () => identity });
    const localAsset = new URL('/assets/router.svg', window.location.href).href;
    appendImage(content, localAsset);
    appendImage(content, localAsset);
    appendImage(content, 'https://cdn.example.test/external.svg');
    appendImage(content, 'data:image/svg+xml;base64,PHN2Zy8+');
    world.appendChild(content);

    const fetchMock = vi.fn(async () => ({
      ok: true,
      blob: async () => ({
        type: 'image/svg+xml',
        arrayBuffer: async () => new TextEncoder().encode('<svg/>').buffer,
      }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await prepareTopologySvgExport(svg);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const exportedSvg = new DOMParser().parseFromString(result!.source, 'image/svg+xml');
    const exportedImages = Array.from(exportedSvg.querySelectorAll('image'));
    expect(exportedImages[0].getAttribute('href')).toBe('data:image/svg+xml;base64,PHN2Zy8+');
    expect(exportedImages[1].getAttribute('href')).toBe('data:image/svg+xml;base64,PHN2Zy8+');
    expect(exportedImages[2].getAttribute('href')).toBe('https://cdn.example.test/external.svg');
    expect(exportedImages[3].getAttribute('href')).toBe('data:image/svg+xml;base64,PHN2Zy8+');
  });

  it('falls back to the current viewport when there are no measurable graphics', async () => {
    const svg = document.createElementNS(svgNamespace, 'svg');
    svg.setAttribute('width', '800');
    svg.setAttribute('height', '600');
    const world = document.createElementNS(svgNamespace, 'g');
    world.setAttribute('class', 'topology-world');
    world.setAttribute('transform', 'translate(8 12)');
    Object.defineProperty(world, 'getCTM', { value: () => identity });
    const empty = document.createElementNS(svgNamespace, 'g');
    Object.defineProperty(empty, 'getBBox', { value: () => ({ x: 0, y: 0, width: 0, height: 0 }) });
    world.appendChild(empty);
    svg.appendChild(world);

    const result = await prepareTopologySvgExport(svg);
    const exportedSvg = new DOMParser().parseFromString(result!.source, 'image/svg+xml');

    expect(result).toMatchObject({ width: 800, height: 600 });
    expect(exportedSvg.documentElement.getAttribute('viewBox')).toBeNull();
    expect(exportedSvg.querySelector('.topology-world')?.getAttribute('transform')).toBe('translate(8 12)');
  });
});

describe('getTopologyExportPixelRatio', () => {
  it('preserves crisp output for ordinary viewport-sized images', () => {
    expect(getTopologyExportPixelRatio(1200, 800)).toBeCloseTo(4096 / 1200);
  });

  it('reduces huge cropped exports to fit the browser canvas limits', () => {
    const width = 50_000;
    const height = 40_000;
    const ratio = getTopologyExportPixelRatio(width, height);
    expect(width * ratio).toBeLessThanOrEqual(32_767);
    expect(height * ratio).toBeLessThanOrEqual(32_767);
    expect(width * height * ratio ** 2).toBeLessThanOrEqual(16_000_000);
  });
});
