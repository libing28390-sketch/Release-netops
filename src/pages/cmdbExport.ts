import type { TableExportData, TableExportMarker } from '../components/ui/TableExportMenu';

export interface CmdbExportColumn<Row> {
  key: string;
  header: string;
  value: (row: Row) => unknown;
  marker?: TableExportMarker;
}

/** Build an explicit export using the same ordered columns rendered by a CMDB table. */
export function buildCmdbExportData<Row>(rows: Row[], columns: CmdbExportColumn<Row>[]): TableExportData {
  return {
    headers: columns.map((column) => column.header),
    rows: rows.map((row) => columns.map((column) => column.value(row))),
    columnMarkers: columns.map((column) => column.marker),
  };
}

export interface CmdbVlanInventoryRow {
  vlan_id?: string | number;
  name?: string;
  device_hostname?: string;
  device_ip?: string;
  site_name?: string;
  vrf_name?: string;
  description?: string;
  prefixes?: string | string[];
  gateway?: string;
  gateway_device?: string;
  svi_interfaces?: string | string[];
  port_details?: string | string[];
  endpoint_details?: Array<Record<string, unknown>>;
  port_count?: number;
  device_count?: number;
  undocumented_port_count?: number;
  business_systems?: string | string[];
  business_owners?: string;
  owner?: string;
  business_departments?: string;
  department?: string;
  highest_business_level?: string;
}

const splitCmdbValues = (value: unknown, separator = /[,;\n]+/) => {
  if (Array.isArray(value)) return value.flatMap(item => splitCmdbValues(item, separator));
  return String(value ?? '').split(separator).map(item => item.trim()).filter(Boolean);
};

function joinedCmdbValues(values: unknown[]): string {
  const normalized = values.map(value => String(value ?? '').trim()).filter(Boolean);
  return normalized.length ? Array.from(new Set(normalized)).join(' · ') : '—';
}

/** One visible field per header in the CMDB VLAN inventory; only IDs meaningful to operators are retained. */
export function buildCmdbVlanExportData(rows: CmdbVlanInventoryRow[], zh: boolean): TableExportData {
  const headers = zh
    ? ['VLAN ID', '名称', '设备名称', '设备 IP', '站点', 'VRF', '描述', '网段', '网关 IP', '网关设备', 'SVI 接口', '接入接口', '端口数', '设备数', '缺少描述数', '终端 IP', '终端 MAC', '业务系统', '部门', '负责人', '业务等级']
    : ['VLAN ID', 'Name', 'Device', 'Device IP', 'Site', 'VRF', 'Description', 'Prefixes', 'Gateway IP', 'Gateway device', 'SVI interfaces', 'Access interfaces', 'Ports', 'Devices', 'Missing descriptions', 'Endpoint IPs', 'Endpoint MACs', 'Business systems', 'Department', 'Owner', 'Business level'];

  return {
    headers,
    rows: rows.map(row => {
      const endpoints = Array.isArray(row.endpoint_details) ? row.endpoint_details : [];
      const arpEndpoints = endpoints.filter(item => String(item.source || '').toLowerCase() === 'arp' && item.ip_address);
      const gateway = String(row.gateway || '').trim();
      const gatewayMacs = new Set(arpEndpoints.filter(item => String(item.ip_address) === gateway).map(item => String(item.mac_address || '')));
      const nonGatewayArp = arpEndpoints.filter(item => String(item.ip_address) !== gateway);
      const macEndpoints = endpoints.filter(item => item.mac_address && !gatewayMacs.has(String(item.mac_address)));
      const terminalRecords = nonGatewayArp.length ? nonGatewayArp : macEndpoints;
      const ports = splitCmdbValues(row.port_details);
      const accessInterfaces = [
        ...ports.map(value => value.match(/^[^:]+:([^ ]+)/)?.[1] || '').filter(Boolean),
        ...macEndpoints.map(item => String(item.interface_name || '')).filter(value => value && !/^vlan/i.test(value)),
      ];

      return [
        row.vlan_id ?? '—',
        row.name || '—',
        row.device_hostname || '—',
        row.device_ip || '—',
        row.site_name || '—',
        row.vrf_name || '—',
        row.description || '—',
        joinedCmdbValues(splitCmdbValues(row.prefixes)),
        row.gateway || '—',
        row.gateway_device || '—',
        joinedCmdbValues(splitCmdbValues(row.svi_interfaces)),
        joinedCmdbValues(accessInterfaces),
        Number(row.port_count || 0),
        Number(row.device_count || 0),
        Number(row.undocumented_port_count || 0),
        joinedCmdbValues(terminalRecords.map(item => item.ip_address)),
        joinedCmdbValues(terminalRecords.map(item => item.mac_address)),
        joinedCmdbValues(splitCmdbValues(row.business_systems)),
        row.business_departments || row.department || '—',
        row.business_owners || row.owner || '—',
        row.highest_business_level || '—',
      ];
    }),
  };
}
