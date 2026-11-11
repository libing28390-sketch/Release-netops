import type { TableExportData } from '../../components/ui/TableExportMenu';
import {
  LIFECYCLE_STATUSES,
  SSH_ALGORITHM_PROFILE_OPTIONS,
  TYPES,
} from './constants';
import type { Asset } from './types';
import { deviceCategoryLabel, deviceRoleLabel } from '../../domain/deviceLabels';

export type AssetExportColumnKey =
  | 'hostname'
  | 'asset_tag'
  | 'asset_type'
  | 'device_category'
  | 'device_role'
  | 'site'
  | 'rack'
  | 'rack_unit'
  | 'status'
  | 'tags'
  | 'vendor'
  | 'model'
  | 'serial_number'
  | 'management_ip'
  | 'ssh_algorithm_profile'
  | 'lifecycle'
  | 'created_at'
  | 'updated_at';

export interface AssetExportColumn {
  key: AssetExportColumnKey;
  zh: string;
  en: string;
}

export function assetCategoryLabel(category: string | undefined, language: 'zh' | 'en'): string {
  return deviceCategoryLabel(category, language);
}

const formatDate = (value: string | undefined) =>
  value ? value.replace('T', ' ').slice(0, 19) : '—';

export function formatAssetExportValue(
  asset: Asset,
  column: AssetExportColumnKey,
  language: 'zh' | 'en',
): string {
  const zh = language === 'zh';
  switch (column) {
    case 'hostname': {
      return asset.hostname || '—';
    }
    case 'asset_tag': return asset.asset_tag || '—';
    case 'asset_type':
      return TYPES.find((item) => item.value === asset.asset_type)?.label[language] || asset.asset_type || '—';
    case 'device_category':
      return assetCategoryLabel(asset.device_category, language);
    case 'device_role': return deviceRoleLabel(asset.device_role, language);
    case 'site': {
      // site_id is an internal identifier. Keep the business site label only;
      // rack and unit have their own visible columns.
      const site = asset.site_name || asset.site_code || '';
      return site || '—';
    }
    case 'rack': return asset.rack || '—';
    case 'rack_unit': {
      const rackUnit = String(asset.rack_unit || '').trim().replace(/^u+/i, '');
      return rackUnit ? `U${rackUnit}` : '—';
    }
    case 'status': {
      const status = asset.online_status
        || (asset.status === 'active' ? 'online' : asset.status === 'inactive' ? 'offline' : 'pending');
      if (status === 'online') return zh ? '在线' : 'Online';
      if (status === 'offline') return zh ? '离线' : 'Offline';
      return zh ? '待确认' : 'Pending';
    }
    case 'tags':
      return asset.tags?.length
        ? asset.tags.map((tag) => zh ? tag.label_zh || tag.label : tag.label).filter(Boolean).join(' · ')
        : '—';
    case 'vendor': return asset.vendor || '—';
    case 'model': return asset.model || '—';
    case 'serial_number': return asset.serial_number || '—';
    case 'management_ip': return asset.management_ip || '—';
    case 'ssh_algorithm_profile': {
      const profile = asset.ssh_algorithm_profile || 'auto';
      return SSH_ALGORITHM_PROFILE_OPTIONS.find((item) => item.value === profile)?.label[language] || profile;
    }
    case 'lifecycle': {
      const lifecycle = asset.lifecycle_status || 'staging';
      return LIFECYCLE_STATUSES.find((item) => item.value === lifecycle)?.label[language]
        || (zh ? '待投产' : 'Staging');
    }
    case 'created_at': return formatDate(asset.created_at);
    case 'updated_at': return formatDate(asset.updated_at);
  }
}

export function buildAssetExportData(
  assets: Asset[],
  columns: AssetExportColumn[],
  language: 'zh' | 'en',
): TableExportData {
  return {
    headers: columns.map((column) => column[language]),
    rows: assets.map((asset) => columns.map((column) => formatAssetExportValue(asset, column.key, language))),
  };
}

export async function fetchAllAssetPages(
  loadPage: (page: number, pageSize: number) => Promise<{ items: Asset[]; total: number }>,
  pageSize = 1000,
  concurrency = 4,
): Promise<Asset[]> {
  const firstPage = await loadPage(1, pageSize);
  const allAssets = [...firstPage.items];
  const pageCount = Math.max(1, Math.ceil(firstPage.total / pageSize));
  const safeConcurrency = Math.max(1, Math.floor(concurrency));

  for (let firstPageInBatch = 2; firstPageInBatch <= pageCount; firstPageInBatch += safeConcurrency) {
    const pages = Array.from(
      { length: Math.min(safeConcurrency, pageCount - firstPageInBatch + 1) },
      (_unused, index) => firstPageInBatch + index,
    );
    const results = await Promise.all(pages.map((page) => loadPage(page, pageSize)));
    results.forEach((result) => allAssets.push(...result.items));
  }

  return allAssets;
}
