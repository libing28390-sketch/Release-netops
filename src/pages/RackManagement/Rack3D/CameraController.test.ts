import { describe, expect, it } from 'vitest';
import { calculateRackFitDistance } from './CameraController';

const U_HEIGHT_3D = 0.4445;

describe('rack camera framing', () => {
  it.each([24, 42, 48])('keeps a %iU rack inside desktop and narrow viewports', totalU => {
    const framedHeight = totalU * U_HEIGHT_3D + 1.2;

    for (const aspect of [16 / 9, 4 / 3, 9 / 16]) {
      const distance = calculateRackFitDistance(framedHeight, 6.3, 45, aspect);
      const visibleHeight = 2 * distance * Math.tan((45 * Math.PI / 180) / 2);
      const visibleWidth = visibleHeight * aspect;

      expect(visibleHeight).toBeGreaterThanOrEqual(framedHeight);
      expect(visibleWidth).toBeGreaterThanOrEqual(6.3);
    }
  });
});
