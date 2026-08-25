import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, Settings2, ShieldAlert, Unlink, X } from 'lucide-react';
import type { Device } from '../types';
import { apiRequest } from '../api/http';
import PlatformProfileSelector, { type PlatformProfileOption } from './PlatformProfileSelector';
import { inferPlatformVendor, platformVendorLabel } from '../utils/platformVendor';

type BatchPlatformOperation = 'add' | 'modify' | 'remove';

interface BatchPlatformBindingModalProps {
  deviceIds: string[];
  devices: Device[];
  language: string;
  onClose: () => void;
  onCompleted: () => Promise<void> | void;
}

const BatchPlatformBindingModal: React.FC<BatchPlatformBindingModalProps> = ({
  deviceIds,
  devices,
  language,
  onClose,
  onCompleted,
}) => {
  const zh = language === 'zh';
  const [operation, setOperation] = useState<BatchPlatformOperation>('add');
  const [profiles, setProfiles] = useState<PlatformProfileOption[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(true);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const selectedDevices = useMemo(
    () => devices.filter((device) => deviceIds.includes(device.id)),
    [deviceIds, devices],
  );
  const vendorValues = useMemo(
    () => Array.from(new Set(selectedDevices.map((device) => inferPlatformVendor(device.vendor, device.platform)))),
    [selectedDevices],
  );
  const unknownVendorCount = selectedDevices.filter((device) => !inferPlatformVendor(device.vendor, device.platform)).length
    + Math.max(0, deviceIds.length - selectedDevices.length);
  const sameVendor = vendorValues.length === 1 && unknownVendorCount === 0;
  const allowedVendor = sameVendor ? vendorValues[0] : '';
  const hasExistingBinding = selectedDevices.some((device) => Boolean(device.platform_profile_id));
  const existingDeviceCount = selectedDevices.filter((device) => Boolean(device.platform_profile_id)).length;

  useEffect(() => {
    let active = true;
    setProfilesLoading(true);
    void apiRequest<{ data: PlatformProfileOption[] }>('/api/platform-registry/profiles')
      .then((response) => {
        if (active) setProfiles(response.data || []);
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : (zh ? '平台列表加载失败' : 'Failed to load platform profiles'));
      })
      .finally(() => {
        if (active) setProfilesLoading(false);
      });
    return () => { active = false; };
  }, [zh]);

  useEffect(() => {
    setOperation(hasExistingBinding ? 'modify' : 'add');
    setSelectedProfileId('');
    setError('');
    setMessage('');
  }, [deviceIds.join(','), hasExistingBinding]);

  const canBind = sameVendor && selectedProfileId && !profilesLoading && (operation === 'modify' || !hasExistingBinding);
  const canSubmit = operation === 'remove' ? !submitting : Boolean(canBind) && !submitting;

  const submit = async () => {
    setError('');
    setMessage('');
    if (operation !== 'remove' && !sameVendor) {
      setError(zh ? '批量绑定要求所选设备属于同一厂商，且每台设备都能确认厂商。' : 'Batch binding requires all selected devices to belong to the same known vendor.');
      return;
    }
    if (operation !== 'remove' && !selectedProfileId) {
      setError(zh ? '请选择目标平台。' : 'Select a target platform.');
      return;
    }
    const force = (operation === 'modify' || operation === 'remove') && hasExistingBinding;
    if (force) {
      const confirmed = window.confirm(zh
        ? `${operation === 'remove' ? '解除' : '修改'} ${deviceIds.length} 台设备的平台绑定？已有绑定会被覆盖/清除，且会影响后续自动化驱动、命令和解析模板。`
        : `${operation === 'remove' ? 'Remove' : 'Change'} platform bindings for ${deviceIds.length} devices? Existing bindings will be changed and can affect automation drivers, commands, and parsers.`);
      if (!confirmed) return;
    }

    setSubmitting(true);
    try {
      if (operation === 'remove') {
        await apiRequest('/api/devices/platform-binding/batch/unbind', {
          method: 'POST',
          body: JSON.stringify({ device_ids: deviceIds, force }),
        });
        setMessage(zh ? `已解除 ${deviceIds.length} 台设备的平台绑定。` : `Removed platform bindings from ${deviceIds.length} devices.`);
      } else {
        await apiRequest('/api/devices/platform-binding/batch', {
          method: 'POST',
          body: JSON.stringify({
            device_ids: deviceIds,
            platform_profile_id: selectedProfileId,
            lock: true,
            force,
          }),
        });
        setMessage(zh ? `已为 ${deviceIds.length} 台设备保存平台绑定。` : `Saved platform bindings for ${deviceIds.length} devices.`);
      }
      await onCompleted();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '批量平台操作失败' : 'Batch platform operation failed'));
    } finally {
      setSubmitting(false);
    }
  };

  const operationLabel = (value: BatchPlatformOperation) => {
    if (value === 'add') return zh ? '新增绑定' : 'Add binding';
    if (value === 'modify') return zh ? '修改绑定' : 'Modify binding';
    return zh ? '解除绑定' : 'Remove binding';
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-zinc-900">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-zinc-800">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-cyan-50 p-2 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-300"><Settings2 size={18} /></div>
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">{zh ? '批量管理平台绑定' : 'Batch platform bindings'}</h2>
              <p className="mt-0.5 text-xs text-slate-500">{zh ? `已选择 ${deviceIds.length} 台设备` : `${deviceIds.length} devices selected`}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-zinc-800" title={zh ? '关闭' : 'Close'}><X size={18} /></button>
        </div>

        <div className="space-y-4 p-5">
          <div className="grid grid-cols-3 gap-2 rounded-xl bg-slate-50 p-1 dark:bg-zinc-800/70">
            {(['add', 'modify', 'remove'] as BatchPlatformOperation[]).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => { setOperation(value); setError(''); setMessage(''); }}
                className={`rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${operation === value ? 'bg-white text-cyan-700 shadow-sm dark:bg-zinc-700 dark:text-cyan-300' : 'text-slate-500 hover:text-slate-800 dark:text-zinc-400 dark:hover:text-zinc-200'}`}
              >
                {value === 'remove' && <Unlink size={13} className="mr-1 inline" />}
                {operationLabel(value)}
              </button>
            ))}
          </div>

          <div className={`rounded-xl border p-3 text-xs ${sameVendor ? 'border-emerald-200 bg-emerald-50/70 text-emerald-800' : 'border-amber-200 bg-amber-50/80 text-amber-800'}`}>
            <div className="flex items-start gap-2">
              {!sameVendor && <ShieldAlert size={15} className="mt-0.5 shrink-0" />}
              <div>
                {sameVendor
                  ? (zh ? `厂商范围：${platformVendorLabel(allowedVendor, language)}，批量绑定只展示该厂商的平台。` : `Vendor scope: ${platformVendorLabel(allowedVendor, language)}. Only this vendor's platforms are available.`)
                  : (zh ? '当前选择包含多个厂商或存在未知厂商，不能批量新增/修改平台；请按同厂商重新选择。解除绑定仍可执行。' : 'The selection contains multiple or unknown vendors. Add/modify is disabled; select devices from one vendor. Remove remains available.')}
                {hasExistingBinding && <span className="ml-1">{zh ? `已有 ${existingDeviceCount} 台存在绑定，修改/解除需要管理员权限。` : `${existingDeviceCount} devices already have bindings; modifying/removing them requires Administrator permission.`}</span>}
              </div>
            </div>
          </div>

          {operation !== 'remove' && (
            <div>
              <label className="mb-1.5 block text-xs font-semibold text-slate-700 dark:text-zinc-200">{zh ? '目标平台（厂商 / 平台 / 版本）' : 'Target platform (vendor / platform / version)'}</label>
              <PlatformProfileSelector
                profiles={profiles}
                value={selectedProfileId}
                language={language}
                allowedVendor={allowedVendor}
                disabled={!sameVendor || profilesLoading || submitting}
                onChange={(profile) => setSelectedProfileId(profile?.id || '')}
              />
              {profilesLoading && <p className="mt-2 flex items-center gap-1 text-[11px] text-slate-500"><Loader2 size={12} className="animate-spin" />{zh ? '正在加载平台目录…' : 'Loading platform catalog…'}</p>}
            </div>
          )}

          {error && <div className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div>}
          {message && <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700">{message}</div>}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-200 bg-slate-50/70 px-5 py-3 dark:border-zinc-800 dark:bg-zinc-900">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-200 dark:text-zinc-300 dark:hover:bg-zinc-800">{zh ? '取消' : 'Cancel'}</button>
          <button type="button" onClick={() => void submit()} disabled={!canSubmit} className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-xs font-bold text-white hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-40">
            {submitting && <Loader2 size={13} className="animate-spin" />}
            {submitting ? (zh ? '处理中…' : 'Applying…') : operationLabel(operation)}
          </button>
        </div>
      </div>
    </div>
  );
};

export default BatchPlatformBindingModal;
