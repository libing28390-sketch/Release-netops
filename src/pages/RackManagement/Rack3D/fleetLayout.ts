import { RackSummary } from '../types';

export interface RackFleetPlacement {
  rack: RackSummary;
  instanceIndex: number;
  groupKey: string;
  groupLabel: string;
  inferred: true;
  position: [number, number, number];
}

const compareText = (left: string | undefined, right: string | undefined) =>
  (left || '').localeCompare(right || '', undefined, { numeric: true, sensitivity: 'base' });

export function buildRackFleetLayout(racks: RackSummary[]): RackFleetPlacement[] {
  const ordered = [...racks].sort((left, right) =>
    compareText(left.site_label, right.site_label) ||
    compareText(left.floor, right.floor) ||
    compareText(left.room, right.room) ||
    compareText(left.row, right.row) ||
    compareText(left.name, right.name)
  );
  const groups = new Map<string, RackSummary[]>();
  ordered.forEach(rack => {
    const groupKey = [rack.site_label, rack.floor, rack.room, rack.row].map(value => value || '—').join(' / ');
    const group = groups.get(groupKey) || [];
    group.push(rack);
    groups.set(groupKey, group);
  });

  const placements: RackFleetPlacement[] = [];
  let zCursor = 0;
  const maxColumns = 20;
  groups.forEach((groupRacks, groupKey) => {
    const columns = Math.min(maxColumns, groupRacks.length);
    const rows = Math.ceil(groupRacks.length / maxColumns);
    groupRacks.forEach((rack, index) => {
      const column = index % maxColumns;
      const rowIndex = Math.floor(index / maxColumns);
      placements.push({
        rack,
        instanceIndex: placements.length,
        groupKey,
        groupLabel: groupKey,
        inferred: true,
        position: [
          (column - (columns - 1) / 2) * 1.25,
          0.9,
          zCursor + rowIndex * 1.7,
        ],
      });
    });
    zCursor += rows * 1.7 + 1.8;
  });
  return placements;
}
