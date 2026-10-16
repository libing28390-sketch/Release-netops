import { describe, expect, it } from 'vitest';
import { getPortConnectorOffset, getPortPhysicalCoordinates } from './RackCableLayer';

describe('rack cable physical port coordinates', () => {
  it('keeps native S6800 cascade suffixes on distinct QSFP ports', () => {
    const port49 = getPortPhysicalCoordinates('XGE1/0/49', true, true);
    const port53 = getPortPhysicalCoordinates('FortyGigE1/0/53', true, true);
    const port54 = getPortPhysicalCoordinates('FGE1/0/54', true, true);

    expect(new Set([port49.x, port53.x, port54.x]).size).toBe(3);
    expect(port49.x).not.toBe(getPortPhysicalCoordinates('XGE1/0/48', true, true).x);
  });

  it('expands compact QSFP notation without collapsing native port numbers', () => {
    expect(getPortPhysicalCoordinates('QSFP+1', true, true).x)
      .toBe(getPortPhysicalCoordinates('XGE1/0/49', true, true).x);
    expect(getPortPhysicalCoordinates('QSFP+6', true, true).x)
      .toBe(getPortPhysicalCoordinates('XGE1/0/54', true, true).x);
  });

  it('keeps SFP bank endpoints on the GLB bottom/top rows', () => {
    const bottomRow = getPortPhysicalCoordinates('GE1/0/1', true, true);
    const topRow = getPortPhysicalCoordinates('GE1/0/9', true, true);

    expect(bottomRow.yOffset).toBeLessThan(0);
    expect(topRow.yOffset).toBeGreaterThan(0);
    expect(Math.abs(bottomRow.yOffset)).toBeCloseTo(Math.abs(topRow.yOffset), 3);
  });

  it('maps passive patch-panel sockets across the full 12x2 field', () => {
    const port1 = getPortPhysicalCoordinates('Port1', true, false, 'patch_panel');
    const port12 = getPortPhysicalCoordinates('Port12', true, false, 'patch_panel');
    const port13 = getPortPhysicalCoordinates('Port13', true, false, 'patch_panel');

    expect(port1.x).toBeLessThan(port12.x);
    expect(port1.yOffset).toBeGreaterThan(0);
    expect(port13.yOffset).toBeLessThan(0);
    expect(port1.x).not.toBe(getPortPhysicalCoordinates('Port2', true, false, 'patch_panel').x);
  });

  it('starts cable geometry at the receptacle face for SFP and QSFP', () => {
    expect(getPortConnectorOffset('GE1/0/1', true)).toBeCloseTo(0.218, 3);
    expect(getPortConnectorOffset('XGE1/0/49', true)).toBeCloseTo(0.24, 3);
    expect(getPortConnectorOffset('SFP+1', false)).toBeCloseTo(0.218, 3);
  });
});
