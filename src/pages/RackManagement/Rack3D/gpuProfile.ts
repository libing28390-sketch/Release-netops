export type GraphicsQualityMode = 'eco' | 'high';
export type GraphicsPreference = 'auto' | GraphicsQualityMode;

export interface GpuProfile {
  renderer: string;
  isIntegratedOrSoftware: boolean;
  recommendedMode: GraphicsQualityMode;
}

export interface RoomRenderBudget {
  mode: GraphicsQualityMode;
  dpr: [number, number];
  shadows: boolean;
  useIbl: boolean;
  maxHtmlLabels: number;
  airflowDefault: boolean;
  airflowFps: number;
  maxAirflowRacks: number;
  airflowParticlesPerRack: number;
}

const STORAGE_KEY = 'nexora_rack3d_graphics_pref';

let cachedGpuDetection: { renderer: string; isIntegratedOrSoftware: boolean } | null = null;

/**
 * Classify a WebGL renderer string as integrated / software / low-power vs discrete GPU.
 * Conservative when masked or unavailable so office laptops never stutter on first load.
 */
export function isIntegratedGpuRenderer(renderer: string): boolean {
  const r = (renderer || '').trim().toLowerCase();
  if (!r) return true;

  // Discrete workstation / gaming GPUs
  if (
    /(nvidia|geforce|rtx\s?\d|gtx\s?\d|quadro|tesla|titan|radeon\s+rx\s?\d|radeon\s+pro|firepro|intel\(r\)\s+arc|arc\s+[ab]\d{3})/.test(r)
  ) {
    return false;
  }

  // Known integrated, mobile, or software WebGL rasterizers
  if (
    /(intel|uhd|iris|hd graphics|vega|radeon\(tm\)\s*graphics|amd radeon graphics|swiftshader|llvmpipe|mesa|microsoft basic|software|warp|mali|adreno|powervr)/.test(r)
  ) {
    return true;
  }

  // Apple Silicon integrated GPU is fast for modest scenes, keep eco only when fleet is large
  if (/apple/.test(r)) {
    return false;
  }

  return true;
}

export function probeWebGlRenderer(): { renderer: string; isIntegratedOrSoftware: boolean } {
  if (cachedGpuDetection) return cachedGpuDetection;
  if (typeof document === 'undefined') {
    return { renderer: '', isIntegratedOrSoftware: true };
  }
  try {
    const canvas = document.createElement('canvas');
    const gl = (canvas.getContext('webgl2') || canvas.getContext('webgl')) as WebGLRenderingContext | null;
    if (!gl) {
      cachedGpuDetection = { renderer: '', isIntegratedOrSoftware: true };
      return cachedGpuDetection;
    }
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    const rawRenderer = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || '') : String(gl.getParameter(gl.RENDERER) || '');
    // Release probe context immediately so we never consume browser WebGL slots
    const loseExt = gl.getExtension('WEBGL_lose_context');
    if (loseExt) loseExt.loseContext();

    cachedGpuDetection = {
      renderer: rawRenderer,
      isIntegratedOrSoftware: isIntegratedGpuRenderer(rawRenderer),
    };
    return cachedGpuDetection;
  } catch {
    cachedGpuDetection = { renderer: '', isIntegratedOrSoftware: true };
    return cachedGpuDetection;
  }
}

export function detectGpuProfile(rackCount = 1): GpuProfile {
  const probed = probeWebGlRenderer();
  const recommendedMode: GraphicsQualityMode =
    probed.isIntegratedOrSoftware || rackCount >= 20 ? 'eco' : 'high';
  return {
    renderer: probed.renderer,
    isIntegratedOrSoftware: probed.isIntegratedOrSoftware,
    recommendedMode,
  };
}

export function loadGraphicsPreference(): GraphicsPreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'eco' || raw === 'high' || raw === 'auto') return raw;
  } catch {
    // ignore storage restriction
  }
  return 'auto';
}

export function saveGraphicsPreference(pref: GraphicsPreference): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    // ignore storage restriction
  }
}

export function resolveRoomRenderBudget(
  mode: GraphicsQualityMode,
  rackCount: number,
): RoomRenderBudget {
  if (mode === 'eco') {
    return {
      mode: 'eco',
      dpr: [1, 1],
      shadows: false,
      // Keep lightweight PMREM IBL active so metallic cabinets/floors never turn black on iGPU!
      // Performance savings come from 1x DPR, shadows=false, instanced batching, and bounded DOM labels.
      useIbl: true,
      maxHtmlLabels: 12,
      airflowDefault: false,
      airflowFps: 18,
      maxAirflowRacks: 20,
      airflowParticlesPerRack: 1,
    };
  }
  return {
    mode: 'high',
    dpr: rackCount >= 30 ? [1, 1.25] : [1, 1.5],
    shadows: rackCount <= 48,
    useIbl: true,
    maxHtmlLabels: 24,
    airflowDefault: false,
    airflowFps: 30,
    maxAirflowRacks: 36,
    airflowParticlesPerRack: 2,
  };
}
