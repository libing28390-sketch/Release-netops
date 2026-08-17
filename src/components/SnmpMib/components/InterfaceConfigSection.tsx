import React from 'react';
import { RotateCcw, Search } from 'lucide-react';

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
  { key: 'if_in_ucast_oid', labelZh: '入方向单播包', labelEn: 'ifInUcastPkts' },
  { key: 'if_out_ucast_oid', labelZh: '出方向单播包', labelEn: 'ifOutUcastPkts' },
];

const inputClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 font-mono text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[9px] text-black/45 dark:text-white/45';

interface InterfaceConfigSectionProps {
  config: InterfaceOidConfig;
  zh: boolean;
  onChange: (config: InterfaceOidConfig) => void;
  onPickOid: (metricKey: string, field: string) => void;
  showToast?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

export const InterfaceConfigSection: React.FC<InterfaceConfigSectionProps> = React.memo(
  ({ config, zh, onChange, onPickOid, showToast }) => {
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
      <section className="mt-4 rounded-xl border border-[#00bceb]/25 bg-[#00bceb]/[.035] p-3.5 dark:bg-[#00bceb]/[.06]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold text-black/75 dark:text-white/80">
                {zh ? '接口流量与状态模板（可选覆盖默认 IF-MIB）' : 'Interface Traffic & Status Template'}
              </span>
              <span className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] font-medium text-[#008aad] dark:text-[#00bceb]">
                RFC 2863 / IF-MIB
              </span>
            </div>
            <div className="mt-1 text-[9px] leading-4 text-black/45 dark:text-white/45">
              {zh
                ? '启用后，接口表、状态、速率、错包丢弃与流量计数器都从此处配置读取；不启用时自动使用内置标准 IF-MIB。'
                : 'When enabled, interface table, speed, errors, and traffic counters read from these OIDs.'}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleResetStandard}
              className="inline-flex items-center gap-1 rounded-md border border-[#00bceb]/30 bg-white/70 px-2 py-1 text-[9px] font-medium text-[#008aad] shadow-sm hover:bg-white dark:bg-white/[.08] dark:text-[#00bceb] dark:hover:bg-white/[.12]"
              title={zh ? '重置所有 17 个字段为标准 RFC 1213 / IF-MIB 默认值' : 'Reset all 17 fields to standard RFC values'}
            >
              <RotateCcw size={10} />
              {zh ? '恢复标准 IF-MIB' : 'Reset to Standard IF-MIB'}
            </button>
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[#00bceb]/30 bg-white/60 px-2.5 py-1 text-[10px] font-medium text-[#008aad] shadow-sm hover:bg-white dark:bg-white/[.06] dark:text-[#00bceb]">
              <input
                type="checkbox"
                checked={config.enabled}
                onChange={event => onChange({ ...config, enabled: event.target.checked })}
                className="rounded text-[#00a9ce] focus:ring-[#00bceb]"
              />
              {zh ? '启用接口模板' : 'Enable interface template'}
            </label>
          </div>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {INTERFACE_OID_FIELDS.map(field => (
            <label key={field.key} className="block">
              <div className="flex items-center justify-between">
                <span className={tinyLabelClass}>{zh ? field.labelZh : field.labelEn}</span>
                <button
                  type="button"
                  disabled={!config.enabled}
                  onClick={() => onPickOid('__interface', field.key)}
                  className="inline-flex items-center gap-0.5 text-[9px] font-medium text-[#008aad] hover:underline disabled:opacity-40 dark:text-[#00bceb]"
                >
                  <Search size={10} />
                  {zh ? '拾取' : 'Pick'}
                </button>
              </div>
              <input
                value={config[field.key]}
                onChange={event => onChange({ ...config, [field.key]: event.target.value })}
                disabled={!config.enabled}
                className={inputClass + ' disabled:cursor-not-allowed disabled:opacity-45'}
                placeholder="1.3.6.1.2.1..."
              />
            </label>
          ))}
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="block">
            <span className={tinyLabelClass}>{zh ? '流量计数器位宽策略' : 'Traffic counter width policy'}</span>
            <select
              value={config.counter_mode}
              onChange={event =>
                onChange({
                  ...config,
                  counter_mode: event.target.value as InterfaceCounterMode,
                })
              }
              disabled={!config.enabled}
              className={selectClass + ' disabled:cursor-not-allowed disabled:opacity-45'}
            >
              <option value="auto">
                {zh ? '自动选择：优先成对 64 位，缺失时自动回退 32 位' : 'Auto: prefer paired 64-bit, fall back to 32-bit'}
              </option>
              <option value="32">Counter32（仅使用 32 位）</option>
              <option value="64">Counter64（仅使用 64 位）</option>
            </select>
          </label>
          <div className="rounded-md bg-white/50 px-2.5 py-2 text-[9px] leading-4 text-black/50 dark:bg-white/[.04] dark:text-white/50">
            {zh
              ? '💡 提示：入方向与出方向必须使用同等位宽计算速率；采集引擎具备环绕补偿，不会跨位宽错算。'
              : 'Ingress and egress must use matching counter width.'}
          </div>
        </div>
      </section>
    );
  },
);

InterfaceConfigSection.displayName = 'InterfaceConfigSection';
