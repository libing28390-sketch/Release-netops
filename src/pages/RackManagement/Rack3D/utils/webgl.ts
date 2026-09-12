/**
 * Detect WebGL support in current browser context without leaking contexts.
 */
export function isWebGLAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    const gl =
      canvas.getContext('webgl2') ||
      canvas.getContext('webgl') ||
      (canvas.getContext('experimental-webgl') as WebGLRenderingContext | null);

    const available = !!(window.WebGLRenderingContext && gl);
    if (gl) {
      const ext = gl.getExtension('WEBGL_lose_context');
      if (ext) ext.loseContext();
    }
    return available;
  } catch {
    return false;
  }
}

/**
 * Get basic GPU renderer info if available.
 */
export function getGPUSummary(): { supported: boolean; renderer?: string; vendor?: string } {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
    if (!gl) return { supported: false };

    let vendor: string | undefined;
    let renderer: string | undefined;

    const debugInfo = (gl as any).getExtension('WEBGL_debug_renderer_info');
    if (debugInfo) {
      vendor = (gl as any).getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
      renderer = (gl as any).getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
    }

    const ext = gl.getExtension('WEBGL_lose_context');
    if (ext) ext.loseContext();

    return { supported: true, vendor, renderer };
  } catch {
    return { supported: false };
  }
}
