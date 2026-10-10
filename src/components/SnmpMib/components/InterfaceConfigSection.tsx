import React, { useState } from 'react';
import { ChevronDown, ChevronUp, RotateCcw, Search, ShieldCheck } from 'lucide-react';

export type InterfaceCounterMode = 'auto' | '32' | '64';

export interface InterfaceOidConfig {
  enabled: boolean;
  if_name_oid: string;
  if_descr_oid: string;
  if_alias_oid: string;
  if_oper_status_oid: string;
  if_high_speed_oid: string;
  if_speed_oid: string;
  if_last_change_oid: string;
  if_in_octets_oid: string;
  if_out_octets_oid: string;
  if_hc_in_octets_oid: string;
  if_hc_out_octets_oid: string;
  if_in_errors_oid: string;
  if_out_errors_oid: string;
  if_in_discards_oid: string;
  if_out_discards_oid: string;
  if_in_ucast_oid: string;
  if_out_ucast_oid: string;
  if_hc_in_ucast_pkts_oid: string;
  if_hc_in_multicast_pkts_oid: string;
  if_hc_in_broadcast_pkts_oid: string;
  if_hc_out_ucast_pkts_oid: string;
  if_hc_out_multicast_pkts_oid: string;
  if_hc_out_broadcast_pkts_oid: string;
  dot3_hc_fcs_errors_oid: string;
  dot3_hc_frame_too_long_oid: string;
  dot3_hc_internal_mac_rx_errors_oid: string;
  dot3_hc_symbol_errors_oid: string;
  dot3_fcs_errors_oid: string;
  counter_mode: InterfaceCounterMode;
}

export const DEFAULT_INTERFACE_CONFIG: InterfaceOidConfig = {
  enabled: false,
  if_name_oid: '1.3.6.1.2.1.31.1.1.1.1',
  if_descr_oid: '1.3.6.1.2.1.2.2.1.2',
  if_alias_oid: '1.3.6.1.2.1.31.1.1.1.18',
  if_oper_status_oid: '1.3.6.1.2.1.2.2.1.8',
  if_high_speed_oid: '1.3.6.1.2.1.31.1.1.1.15',
  if_speed_oid: '1.3.6.1.2.1.2.2.1.5',
  if_last_change_oid: '1.3.6.1.2.1.2.2.1.9',
  if_in_octets_oid: '1.3.6.1.2.1.2.2.1.10',
  if_out_octets_oid: '1.3.6.1.2.1.2.2.1.16',
  if_hc_in_octets_oid: '1.3.6.1.2.1.31.1.1.1.6',
  if_hc_out_octets_oid: '1.3.6.1.2.1.31.1.1.1.10',
  if_in_errors_oid: '1.3.6.1.2.1.2.2.1.14',
  if_out_errors_oid: '1.3.6.1.2.1.2.2.1.20',
  if_in_discards_oid: '1.3.6.1.2.1.2.2.1.13',
  if_out_discards_oid: '1.3.6.1.2.1.2.2.1.19',
  if_in_ucast_oid: '1.3.6.1.2.1.2.2.1.11',
  if_out_ucast_oid: '1.3.6.1.2.1.2.2.1.17',
  if_hc_in_ucast_pkts_oid: '1.3.6.1.2.1.31.1.1.1.7',
  if_hc_in_multicast_pkts_oid: '1.3.6.1.2.1.31.1.1.1.8',
  if_hc_in_broadcast_pkts_oid: '1.3.6.1.2.1.31.1.1.1.9',
  if_hc_out_ucast_pkts_oid: '1.3.6.1.2.1.31.1.1.1.11',
  if_hc_out_multicast_pkts_oid: '1.3.6.1.2.1.31.1.1.1.12',
  if_hc_out_broadcast_pkts_oid: '1.3.6.1.2.1.31.1.1.1.13',
  dot3_hc_fcs_errors_oid: '1.3.6.1.2.1.10.7.11.1.2',
  dot3_hc_frame_too_long_oid: '1.3.6.1.2.1.10.7.11.1.4',
  dot3_hc_internal_mac_rx_errors_oid: '1.3.6.1.2.1.10.7.11.1.5',
  dot3_hc_symbol_errors_oid: '1.3.6.1.2.1.10.7.11.1.6',
  dot3_fcs_errors_oid: '1.3.6.1.2.1.10.7.2.1.3',
  counter_mode: 'auto',
};

export const INTERFACE_OID_FIELDS: Array<{
  key: Exclude<keyof InterfaceOidConfig, 'enabled' | 'counter_mode'>;
  labelZh: string;
  labelEn: string;
}> = [
  { key: 'if_name_oid', labelZh: '接口名称 (ifName)', labelEn: 'ifName' },
  { key: 'if_descr_oid', labelZh: '接口描述 (ifDescr)', labelEn: 'ifDescr' },
  { key: 'if_alias_oid', labelZh: '接口别名 (ifAlias)', labelEn: 'ifAlias' },
  { key: 'if_oper_status_oid', labelZh: '运行状态 (ifOperStatus)', labelEn: 'ifOperStatus' },
  { key: 'if_high_speed_oid', labelZh: '高速速率 (ifHighSpeed)', labelEn: 'ifHighSpeed' },
  { key: 'if_speed_oid', labelZh: '接口速率 (ifSpeed)', labelEn: 'ifSpeed' },
  { key: 'if_last_change_oid', labelZh: '最后变更 (ifLastChange)', labelEn: 'ifLastChange' },
  { key: 'if_in_octets_oid', labelZh: '入方向 32 位字节', labelEn: 'ifInOctets (32)' },
  { key: 'if_out_octets_oid', labelZh: '出方向 32 位字节', labelEn: 'ifOutOctets (32)' },
  { key: 'if_hc_in_octets_oid', labelZh: '入方向 64 位字节', labelEn: 'ifHCInOctets (64)' },
  { key: 'if_hc_out_octets_oid', labelZh: '出方向 64 位字节', labelEn: 'ifHCOutOctets (64)' },
  { key: 'if_in_errors_oid', labelZh: '入方向错包', labelEn: 'ifInErrors' },
  { key: 'if_out_errors_oid', labelZh: '出方向错包', labelEn: 'ifOutErrors' },
  { key: 'if_in_discards_oid', labelZh: '入方向丢弃', labelEn: 'ifInDiscards' },
  { key: 'if_out_discards_oid', labelZh: '出方向丢弃', labelEn: 'ifOutDiscards' },
  { key: 'if_in_ucast_oid', labelZh: '入方向单播包（32位回退）', labelEn: 'ifInUcastPkts (32 fallback)' },
  { key: 'if_out_ucast_oid', labelZh: '出方向单播包（32位回退）', labelEn: 'ifOutUcastPkts (32 fallback)' },
  { key: 'if_hc_in_ucast_pkts_oid', labelZh: '入单播包（64位）', labelEn: 'ifHCInUcastPkts (64)' },
  { key: 'if_hc_in_multicast_pkts_oid', labelZh: '入组播包（64位）', labelEn: 'ifHCInMulticastPkts (64)' },
  { key: 'if_hc_in_broadcast_pkts_oid', labelZh: '入广播包（64位）', labelEn: 'ifHCInBroadcastPkts (64)' },
  { key: 'if_hc_out_ucast_pkts_oid', labelZh: '出单播包（64位）', labelEn: 'ifHCOutUcastPkts (64)' },
  { key: 'if_hc_out_multicast_pkts_oid', labelZh: '出组播包（64位）', labelEn: 'ifHCOutMulticastPkts (64)' },
  { key: 'if_hc_out_broadcast_pkts_oid', labelZh: '出广播包（64位）', labelEn: 'ifHCOutBroadcastPkts (64)' },
  { key: 'dot3_hc_fcs_errors_oid', labelZh: 'CRC/FCS（64位）', labelEn: 'dot3HCStatsFCSErrors (64)' },
  { key: 'dot3_hc_frame_too_long_oid', labelZh: '超长帧错误（64位）', labelEn: 'dot3HCStatsFrameTooLongs (64)' },
  { key: 'dot3_hc_internal_mac_rx_errors_oid', labelZh: 'MAC接收错误（64位）', labelEn: 'dot3HCStatsInternalMacReceiveErrors (64)' },
  { key: 'dot3_hc_symbol_errors_oid', labelZh: '符号错误（64位）', labelEn: 'dot3HCStatsSymbolErrors (64)' },
  { key: 'dot3_fcs_errors_oid', labelZh: 'CRC/FCS（32位回退）', labelEn: 'dot3StatsFCSErrors (32 fallback)' },
];

const inputClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 font-mono text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10';

interface InterfaceConfigSectionProps {
  config: InterfaceOidConfig;
  zh: boolean;
  onChange: (config: InterfaceOidConfig) => void;
  onPickOid: (metricKey: string, field: string) => void;
  showToast?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const InterfaceConfigSection: React.FC<InterfaceConfigSectionProps> = React.memo(
  ({ config, zh, onChange, onPickOid, showToast }) => {
    const [customOpen, setCustomOpen] = useState(false);

    const handleToggleEnabled = (enabled: boolean) => {
      onChange({
        ...config,
        enabled,
      });
    };

    const handleResetStandard = () => {
      onChange({
        ...DEFAULT_INTERFACE_CONFIG,
        enabled: true,
      });
      showToast?.(
        zh ? '已恢复标准 IF-MIB (RFC 1213 / 2863) 默认 OID' : 'Reset to standard IF-MIB default OIDs',
        'success',
      );
    };

    return (
      <div className="mt-3.5 rounded-xl border border-black/8 bg-white/40 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.02]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <label className="inline-flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                aria-label={zh ? '启用接口模板' : 'Enable interface template'}
                checked={config.enabled}
                onChange={e => handleToggleEnabled(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-[#00a9ce] focus:ring-[#00a9ce]"
              />
              <span className="text-xs font-semibold text-black/80 dark:text-white/85">
                {zh ? '启用接口流量与状态采集' : 'Enable Interface Traffic & Status Monitoring'}
              </span>
            </label>

            {config.enabled && (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
                <ShieldCheck size={12} />
                {zh ? '标准 IF-MIB (RFC 2863 / Counter64)' : 'Standard IF-MIB / 64-bit'}
              </span>
            )}
          </div>

          {config.enabled && (
            <div className="flex items-center gap-2">
              <label className="inline-flex items-center gap-1.5 text-[10px] font-medium text-black/50 dark:text-white/50">
                <span>{zh ? '流量计数器位宽' : 'Traffic counter width'}</span>
                <select
                  aria-label={zh ? '流量计数器位宽' : 'Traffic counter width'}
                  value={config.counter_mode}
                  onChange={e => onChange({ ...config, counter_mode: e.target.value as InterfaceCounterMode })}
                  className="rounded-md border border-black/8 bg-transparent px-1.5 py-1 text-[10px] text-black/70 outline-none dark:border-white/10 dark:text-white/70"
                >
                  <option value="auto">{zh ? '自动' : 'Auto'}</option>
                  <option value="64">64-bit</option>
                  <option value="32">32-bit</option>
                </select>
              </label>
              <button
                type="button"
                onClick={() => setCustomOpen(prev => !prev)}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-[#008aad] hover:underline dark:text-[#00bceb]"
              >
                {customOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {zh ? '自定义私有接口 OID (极少数特殊机型)' : 'Custom Interface OIDs (rare)'}
              </button>

              {customOpen && (
                <button
                  type="button"
                  onClick={handleResetStandard}
                  className="inline-flex items-center gap-1 rounded border border-black/8 px-2 py-0.5 text-[10px] text-black/60 hover:bg-black/5 dark:border-white/10 dark:text-white/60"
                  title={zh ? '恢复标准 IF-MIB 默认值' : 'Reset to standard IF-MIB'}
                >
                  <RotateCcw size={10} />
                  {zh ? '重置' : 'Reset'}
                </button>
              )}
            </div>
          )}
        </div>

        {/* Collapsible custom interface OID grid */}
        {config.enabled && customOpen && (
          <div className="mt-3 grid gap-2.5 border-t border-black/6 pt-3 sm:grid-cols-2 lg:grid-cols-3 dark:border-white/8">
            {INTERFACE_OID_FIELDS.map(item => (
              <div key={item.key} className="relative">
                <label className="block text-[10px] font-medium text-black/50 dark:text-white/50">
                  {zh ? item.labelZh : item.labelEn}
                </label>
                <div className="relative mt-1">
                  <input
                    value={String(config[item.key] || '')}
                    onChange={e => onChange({ ...config, [item.key]: e.target.value })}
                    className={`${inputClass} pr-6`}
                    placeholder="1.3.6.1.2.1..."
                  />
                  <button
                    type="button"
                    onClick={() => onPickOid('__interface', item.key)}
                    className="absolute right-1.5 top-2 text-[#008aad] hover:text-[#00bceb] dark:text-[#00bceb]"
                    title={zh ? '从 MIB 拾取' : 'Pick OID'}
                  >
                    <Search size={11} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  },
);

export default InterfaceConfigSection;
