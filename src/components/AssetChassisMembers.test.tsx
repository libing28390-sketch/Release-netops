import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AssetChassisMembers, type AssetChassisMember } from './AssetChassisMembers';
import { AssetReadonlyDetailInner, normalizeAssetApiRow } from './AssetReadonlyDetail';

const makeMember = (overrides: Partial<AssetChassisMember> = {}): AssetChassisMember => ({
  entity_index: 1,
  entity_name: 'Control board',
  entity_description: 'Main controller',
  model: 'CTRL-1',
  serial_number: 'CHASSIS-SN-1',
  collected_at: '2026-10-30T08:00:00Z',
  ...overrides,
});

describe('AssetChassisMembers', () => {
  it('keeps multiple serial numbers associated with their entities and labels unknown ownership', () => {
    render(<AssetChassisMembers members={[
      makeMember(),
      makeMember({
        entity_index: 7,
        entity_name: '',
        entity_description: '48-port line card',
        model: 'LC-48',
        serial_number: 'CHASSIS-SN-7',
      }),
    ]} zh />);

    expect(screen.getByRole('heading', { name: '堆叠/机箱序列号' })).toBeTruthy();
    const controlBoard = screen.getByRole('heading', { name: 'Control board' }).closest('article') as HTMLElement;
    const unknownEntity = screen.getByRole('heading', { name: '实体 7 · 成员归属待确认' }).closest('article') as HTMLElement;
    expect(within(controlBoard).getByText('CHASSIS-SN-1')).toBeTruthy();
    expect(within(controlBoard).getByText('CTRL-1')).toBeTruthy();
    expect(within(controlBoard).queryByText('CHASSIS-SN-7')).toBeNull();
    expect(within(unknownEntity).getByText('CHASSIS-SN-7')).toBeTruthy();
    expect(within(unknownEntity).getByText('LC-48')).toBeTruthy();
    expect(screen.queryByText(/master|standby/i)).toBeNull();
  });

  it('renders nothing for an empty member list', () => {
    const { container } = render(<AssetChassisMembers members={[]} zh={false} />);
    expect(container.firstChild).toBeNull();
  });

  it('normalizes valid member rows and displays them through the shared readonly detail', () => {
    const validMember = makeMember({ entity_name: '', entity_index: 3, serial_number: 'NORMALIZED-SN' });
    const asset = normalizeAssetApiRow({
      asset_type: 'network_device',
      asset_tag: 'NET-01',
      chassis_members: [validMember, { ...validMember, entity_index: '4' }, null],
    });

    expect(asset.chassis_members).toEqual([validMember]);
    render(<AssetReadonlyDetailInner asset={asset} zh={false} />);
    expect(screen.getByRole('heading', { name: 'Chassis serial number' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Entity 3 · membership unconfirmed' })).toBeTruthy();
    expect(screen.getByText('NORMALIZED-SN')).toBeTruthy();
  });
});
