import { describe, expect, it } from 'vitest';
import { calculateDeviceFocusPose, calculateRackFitDistance } from './CameraController';

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

  it('supports macro spot focus with exact X/Y targeting, front/rear face, and close standoff', () => {
    const leftFront = calculateDeviceFocusPose(
      {
        centerX: -1.72,
        centerY: 4.0,
        centerZ: 0,
        width: 4.78,
        height: 0.44,
        depth: 7.5,
        face: 'front',
        distance: 1.18,
        spotLabel: '左侧灯/铭牌',
        timestamp: 100,
      },
      6.0,
      10.0,
      42,
      16 / 9,
    );
    expect(leftFront.lookAt[0]).toBeCloseTo(-1.72, 2);
    expect(leftFront.position[0]).toBeCloseTo(-1.72, 2);
    expect(leftFront.distance).toBeCloseTo(1.18, 2);
    expect(leftFront.position[2]).toBeGreaterThan(leftFront.lookAt[2]);

    const rearPsu = calculateDeviceFocusPose(
      {
        centerX: 0,
        centerY: 4.0,
        centerZ: 0,
        width: 4.78,
        height: 0.44,
        depth: 7.5,
        face: 'rear',
        distance: 2.15,
        timestamp: 200,
      },
      6.0,
      10.0,
      42,
      16 / 9,
    );
    expect(rearPsu.position[2]).toBeLessThan(rearPsu.lookAt[2]);
    expect(rearPsu.distance).toBeCloseTo(2.15, 2);
  });
});
