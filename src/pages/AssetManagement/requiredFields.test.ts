import { describe, expect, it } from 'vitest';
import { getMissingAssetRequiredFields } from './requiredFields';

describe('new asset required fields', () => {
  it('allows missing SNMP identity when the asset tag and management IP exist', () => {
    expect(getMissingAssetRequiredFields({ asset_tag: 'NET-TEST-01', management_ip: '192.0.2.10' })).toEqual([]);
  });
  it('rejects whitespace identifiers and does not substitute hostname for asset tag', () => {
    expect(getMissingAssetRequiredFields({ asset_tag: '  ', management_ip: '  ' })).toEqual(['asset_tag', 'management_ip']);
    expect(getMissingAssetRequiredFields({ management_ip: '192.0.2.10' })).toEqual(['asset_tag']);
    expect(getMissingAssetRequiredFields({ asset_tag: 'NET-TEST-01' })).toEqual(['management_ip']);
  });
});
