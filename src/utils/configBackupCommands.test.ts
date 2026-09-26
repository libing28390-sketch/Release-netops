import { describe, expect, it } from 'vitest';
import { getDefaultConfigBackupCommands } from './configBackupCommands';

describe('getDefaultConfigBackupCommands', () => {
  it.each([
    ['Cisco', 'show running-config'],
    ['Huawei', 'display current-configuration'],
    ['H3C', 'display current-configuration'],
    ['Juniper', 'show configuration'],
    ['Arista', 'show running-config'],
    ['Ruijie', 'show running-config'],
    ['ZTE', 'show running-config'],
    ['Raisecom', 'show running-config'],
    ['DPtech', 'display current-configuration'],
    ['Maipu', 'show running-config'],
    ['Fortinet', 'show full-configuration'],
  ])('returns the default running command for %s', (vendor, command) => {
    expect(getDefaultConfigBackupCommands(vendor)?.running).toBe(command);
  });

  it('prefers an explicit vendor over a mismatched platform value', () => {
    expect(getDefaultConfigBackupCommands('H3C', 'cisco_ios')).toEqual({
      running: 'display current-configuration',
      startup: 'display saved-configuration',
    });
  });

  it('uses a platform only when the vendor is not specified', () => {
    expect(getDefaultConfigBackupCommands('', 'zte_zxros')?.running).toBe('show running-config');
    expect(getDefaultConfigBackupCommands('Other', 'fortinet_fortios')?.running).toBe('show full-configuration');
  });

  it('does not silently guess a command for an unknown vendor', () => {
    expect(getDefaultConfigBackupCommands('UnknownVendor', 'cisco_ios')).toBeNull();
    expect(getDefaultConfigBackupCommands('NotCisco', 'linux')).toBeNull();
  });
});
