import React from 'react';
import { ChevronRight, Eye, Pencil } from 'lucide-react';
import { ActionIconButton } from '../ui/ActionIconButton';
import { TableActionCell, TableActionHeader } from '../ui/TableActionColumn';
import { DataTable, DataTableFrame } from '../DataTable';
import { auditStatusBadgeClass, severityBadgeClass } from '../shared';
import type { WanCircuitItem } from '../../types/wan-circuits';

interface Props {
  items: WanCircuitItem[];
  selectedId?: string;
  language: 'zh' | 'en';
  onSelect: (item: WanCircuitItem) => void;
  onEdit: (item: WanCircuitItem) => void;
}

const statusLabel = (status: string | undefined, zh: boolean) => {
  const labels: Record<string, string> = {
    healthy: zh ? '正常' : 'Healthy',
    degraded: zh ? '关注' : 'Degraded',
    critical: zh ? '严重' : 'Critical',
    unavailable: zh ? '不可用' : 'Unavailable',
    unknown: zh ? '无数据' : 'No data',
  };
  return labels[status || 'unknown'] || status || labels.unknown;
};

const formatMbps = (value: number | null | undefined) => {
  if (value == null) return '--';
  const mbps = Number(value) / 1_000_000;
  return `${mbps >= 10 ? mbps.toFixed(0) : mbps.toFixed(1)} Mbps`;
};

const statusBadgeClass = (status: string | undefined) => auditStatusBadgeClass(status === 'healthy' ? 'success' : status === 'degraded' ? 'warning' : status === 'critical' || status === 'unavailable' ? 'failed' : 'unknown');

export const WanCircuitTable: React.FC<Props> = ({ items, selectedId, language, onSelect, onEdit }) => {
  const zh = language === 'zh';
  return (
    <DataTableFrame className="overflow-hidden rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm" density="compact">
      <div className="overflow-x-auto">
        <DataTable className="min-w-[760px] w-full text-left text-xs">
          <thead>
            <tr>
              <th scope="col">{zh ? '线路' : 'Circuit'}</th>
              <th scope="col">{zh ? '站点 / 运营商' : 'Site / provider'}</th>
              <th scope="col">{zh ? '端点' : 'Endpoints'}</th>
              <th scope="col">{zh ? '状态' : 'Status'}</th>
              <th scope="col">{zh ? '带宽' : 'Bandwidth'}</th>
              <TableActionHeader>{zh ? '操作' : 'Actions'}</TableActionHeader>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const status = item.health_status || 'unknown';
              const hasSharedInterface = item.endpoints?.some((endpoint) => endpoint.measurement_scope === 'shared_interface');
              return (
                <tr key={item.id} className={selectedId === item.id ? 'bg-[var(--ui-surface-muted)]' : undefined}>
                  <td>
                    <button type="button" className="group text-left" onClick={() => onSelect(item)}>
                      <span className="block max-w-[220px] truncate font-semibold text-[var(--heading-text)] group-hover:text-[var(--ui-accent)]">{item.link_name || item.id}</span>
                      <span className="mt-0.5 block text-[10px] text-[var(--muted-text)]">{item.circuit_number || item.interface_name || '--'}</span>
                    </button>
                  </td>
                  <td>
                    <span className="block max-w-[190px] truncate text-[var(--ui-fg)]">{item.site_name || item.site_id || '--'}</span>
                    <span className="mt-0.5 block max-w-[190px] truncate text-[10px] text-[var(--muted-text)]">{item.provider || '--'}</span>
                  </td>
                  <td><span className="block">{item.endpoints?.length ?? '--'}</span>{hasSharedInterface && <span className={`mt-1 inline-flex rounded-full px-2 py-1 text-[10px] font-semibold ${auditStatusBadgeClass('warning')}`}>{zh ? '共享接口' : 'Shared interface'}</span>}</td>
                  <td><span className={`inline-flex rounded-full px-2 py-1 text-[10px] font-semibold ${statusBadgeClass(status)}`}>{statusLabel(status, zh)}</span></td>
                  <td><span className="block">↓ {formatMbps(item.contracted_download_bps)}</span><span className="mt-0.5 block text-[10px] text-[var(--muted-text)]">↑ {formatMbps(item.contracted_upload_bps)}</span></td>
                  <TableActionCell label={`${item.link_name} ${zh ? '操作' : 'actions'}`}>
                    <ActionIconButton icon={Eye} label={zh ? '查看详情' : 'View details'} variant="accent" onClick={() => onSelect(item)} />
                    <ActionIconButton icon={Pencil} label={zh ? '编辑线路' : 'Edit circuit'} onClick={() => onEdit(item)} />
                    <ActionIconButton icon={ChevronRight} label={zh ? '打开线路' : 'Open circuit'} onClick={() => onSelect(item)} />
                  </TableActionCell>
                </tr>
              );
            })}
          </tbody>
        </DataTable>
      </div>
    </DataTableFrame>
  );
};

export const circuitStatusBadgeClass = statusBadgeClass;
export const circuitStatusLabel = statusLabel;
export const circuitSeverityClass = severityBadgeClass;
