import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ImagePlus, Loader2, Network, RotateCcw, Upload, X } from 'lucide-react';
import {
  getTopologyIconDataUrl,
  setTopologyDeviceIcon,
  setTopologyIconTypeDefault,
  uploadTopologyIcon,
  type TopologyIcon,
  type TopologyIconCatalog,
} from '../api/topologyIcons';
import { TOPOLOGY_ICON_TYPES, topologyIconTypeLabel, type TopologyIconType } from '../domain/topologyDeviceIcons';
import { useEscapeClose } from '../hooks/useEscapeClose';

type IconScope = 'type' | 'device';

interface TopologyIconLibraryProps {
  catalog: TopologyIconCatalog;
  device?: { id: string; hostname: string; deviceType: TopologyIconType };
  language?: string;
  builtinIconUrl: (type: TopologyIconType) => string | undefined;
  onChanged: () => Promise<void>;
  onClose: () => void;
}

interface IconPreviewProps {
  icon?: TopologyIcon;
  builtinUrl?: string;
  alt: string;
  size: 'tile' | 'canvas';
}

const IconPreview: React.FC<IconPreviewProps> = ({ icon, builtinUrl, alt, size }) => {
  const [source, setSource] = useState<string | undefined>(builtinUrl);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let active = true;
    setSource(icon ? undefined : builtinUrl);
    setLoadError(false);
    if (!icon) return () => { active = false; };

    void getTopologyIconDataUrl(icon)
      .then((dataUrl) => {
        if (active) setSource(dataUrl);
      })
      .catch(() => {
        if (active) setLoadError(true);
      });

    return () => { active = false; };
  }, [builtinUrl, icon]);

  if (loadError || (!source && icon)) {
    return <span className={`flex shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-400 ${size === 'canvas' ? 'h-[72px] w-[72px]' : 'h-[50px] w-[50px]'}`} aria-label={loadError ? '图标加载失败' : undefined}>
      {loadError ? <X size={18} /> : <Loader2 size={17} className="animate-spin" />}
    </span>;
  }

  if (!source) return <span className={`flex shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500 ${size === 'canvas' ? 'h-[72px] w-[72px]' : 'h-[50px] w-[50px]'}`}><Network size={size === 'canvas' ? 25 : 21} aria-hidden="true" /></span>;

  return <span className={`flex shrink-0 items-center justify-center rounded-lg bg-white ${size === 'canvas' ? 'h-[72px] w-[72px]' : 'h-[50px] w-[50px]'}`}>
    <img src={source} alt={alt} className={`${size === 'canvas' ? 'h-[58px] w-[58px]' : 'h-[42px] w-[42px]'} object-contain`} />
  </span>;
};

const TopologyIconLibrary: React.FC<TopologyIconLibraryProps> = ({
  catalog,
  device,
  language = 'zh',
  builtinIconUrl,
  onChanged,
  onClose,
}) => {
  const isEnglish = language === 'en';
  const [deviceType, setDeviceType] = useState<TopologyIconType>(device?.deviceType || TOPOLOGY_ICON_TYPES[0]);
  const [scope, setScope] = useState<IconScope>(device ? 'device' : 'type');
  const [selectedIconId, setSelectedIconId] = useState<string | null>(null);
  const [icons, setIcons] = useState(catalog.icons);
  const uploadFileInputRef = useRef<HTMLInputElement>(null);
  const [uploadName, setUploadName] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<'upload' | 'apply' | null>(null);
  const deviceOverride = device ? catalog.device_overrides[device.id] : undefined;
  const matchingDeviceOverride = deviceOverride?.device_type === deviceType ? deviceOverride : undefined;

  useEscapeClose(true, onClose);

  const currentIconId = scope === 'device' && device
    ? matchingDeviceOverride?.icon_id ?? null
    : catalog.type_defaults[deviceType] ?? null;
  const typeIcons = useMemo(
    () => icons.filter((icon) => icon.device_type === deviceType),
    [deviceType, icons],
  );
  const previewIconId = scope === 'device' && selectedIconId === null
    ? catalog.type_defaults[deviceType] ?? null
    : selectedIconId;
  const previewIcon = typeIcons.find((icon) => icon.id === previewIconId);
  const selectionIsCurrent = selectedIconId === currentIconId;
  const hasDeviceOverride = Boolean(matchingDeviceOverride?.icon_id);

  useEffect(() => setIcons(catalog.icons), [catalog.icons]);

  useEffect(() => {
    setSelectedIconId(currentIconId);
    setError('');
    setNotice('');
  }, [currentIconId, deviceType, scope]);

  const selectDeviceType = (nextType: TopologyIconType) => {
    setDeviceType(nextType);
    setUploadName('');
    setUploadFile(null);
    setUploadError('');
    if (uploadFileInputRef.current) uploadFileInputRef.current.value = '';
    setSelectedIconId(scope === 'device' && device
      ? (deviceOverride?.device_type === nextType ? deviceOverride.icon_id : null)
      : catalog.type_defaults[nextType] ?? null);
    setError('');
    setNotice('');
  };

  const selectScope = (nextScope: IconScope) => {
    setScope(nextScope);
    setSelectedIconId(nextScope === 'device' && device
      ? matchingDeviceOverride?.icon_id ?? null
      : catalog.type_defaults[deviceType] ?? null);
    setError('');
    setNotice('');
  };

  const applySelection = async () => {
    if (!catalog.can_manage || busy) return;
    setBusy('apply');
    setError('');
    setNotice('');
    try {
      if (scope === 'device' && device) {
        await setTopologyDeviceIcon(device.id, deviceType, selectedIconId);
      } else {
        await setTopologyIconTypeDefault(deviceType, selectedIconId);
      }
      await onChanged();
      setNotice(isEnglish ? 'Icon setting saved.' : '图标设置已保存。');
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : (isEnglish ? 'Could not save the icon setting.' : '保存图标设置失败。'));
    } finally {
      setBusy(null);
    }
  };

  const restoreDeviceDefault = async () => {
    if (!device || busy || !catalog.can_manage) return;
    setBusy('apply');
    setError('');
    setNotice('');
    try {
      await setTopologyDeviceIcon(device.id, deviceType, null);
      setSelectedIconId(null);
      await onChanged();
      setNotice(isEnglish ? 'Device now follows its type default.' : '当前设备已恢复跟随类型默认图标。');
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : (isEnglish ? 'Could not restore the device default.' : '恢复类型默认图标失败。'));
    } finally {
      setBusy(null);
    }
  };

  const uploadVariant = async () => {
    if (!catalog.can_manage || !uploadFile || !uploadName.trim() || busy) {
      setUploadError(isEnglish ? 'Choose a PNG or SVG file and enter a name.' : '请选择 PNG 或 SVG 文件，并填写图标名称。');
      return;
    }
    const normalizedType = uploadFile.type.toLowerCase();
    const validMime = normalizedType === 'image/png' || normalizedType === 'image/svg+xml';
    const validExtension = /\.(png|svg)$/i.test(uploadFile.name);
    if (!validMime || !validExtension) {
      setUploadError(isEnglish ? 'Only PNG and SVG files are supported.' : '目前只支持 PNG 和 SVG 图片。');
      return;
    }
    if (uploadFile.size > 4 * 1024 * 1024) {
      setUploadError(isEnglish ? 'The file must be 4 MiB or smaller.' : '图标文件不能超过 4 MiB。');
      return;
    }

    setBusy('upload');
    setUploadError('');
    setError('');
    setNotice('');
    try {
      const created = await uploadTopologyIcon({ deviceType, name: uploadName, file: uploadFile });
      setIcons((current) => [...current.filter((icon) => icon.id !== created.id), created]);
      setSelectedIconId(created.id);
      setUploadName('');
      setUploadFile(null);
      if (uploadFileInputRef.current) uploadFileInputRef.current.value = '';
      await onChanged();
      setNotice(isEnglish ? 'Uploaded. Review the preview and apply it when ready.' : '上传完成。请检查预览，再手动应用图标。');
    } catch (uploadFailure) {
      setUploadError(uploadFailure instanceof Error ? uploadFailure.message : (isEnglish ? 'The icon upload failed.' : '图标上传失败。'));
    } finally {
      setBusy(null);
    }
  };

  const selectedLabel = previewIcon?.name || (scope === 'device' ? (isEnglish ? 'Follow type default' : '跟随类型默认') : (isEnglish ? 'System default' : '系统默认'));
  const canChooseDeviceScope = Boolean(device);

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/45 p-3 backdrop-blur-[2px] sm:p-6" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onClose();
    }}>
      <section role="dialog" aria-modal="true" aria-labelledby="topology-icon-library-title" className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_26px_80px_rgba(10,26,50,0.28)]">
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 bg-slate-50/80 px-5 py-4 sm:px-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">{isEnglish ? 'Topology icon library' : '拓扑设备图标'}</p>
            <h2 id="topology-icon-library-title" className="mt-1 text-xl font-bold tracking-tight text-slate-900">{isEnglish ? 'Choose a device icon' : '选择设备图标'}</h2>
            {device && <p className="mt-1 text-sm text-slate-600">{device.hostname}</p>}
          </div>
          <button type="button" aria-label={isEnglish ? 'Close icon library' : '关闭图标库'} onClick={onClose} disabled={Boolean(busy)} className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-200/70 hover:text-slate-900 disabled:opacity-50"><X size={19} /></button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_285px]">
            <div className="space-y-5">
              <label className="block max-w-sm text-sm font-semibold text-slate-700">
                {isEnglish ? 'Device type' : '设备类型'}
                <select value={deviceType} disabled={Boolean(device) || Boolean(busy)} onChange={(event) => selectDeviceType(event.target.value as TopologyIconType)} className="mt-2 block h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-800 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100">
                  {TOPOLOGY_ICON_TYPES.map((type) => <option key={type} value={type}>{topologyIconTypeLabel(type, language)}</option>)}
                </select>
              </label>

              <div>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-bold text-slate-800">{isEnglish ? 'Available variants' : '可选图标'}</h3>
                    <p className="mt-0.5 text-xs text-slate-500">{isEnglish ? 'Variants are independent for each device type.' : '每种设备类型分别维护多款图标。'}</p>
                  </div>
                  <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold tabular-nums text-slate-600">{typeIcons.length + 1}</span>
                </div>
                <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  <button type="button" aria-pressed={selectedIconId === null} disabled={Boolean(busy)} onClick={() => setSelectedIconId(null)} className={`group relative flex min-h-[108px] flex-col items-center justify-center gap-2 rounded-xl border p-3 text-center transition ${selectedIconId === null ? 'border-blue-500 bg-blue-50/70 ring-2 ring-blue-100' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'}`}>
                    {selectedIconId === null && <span className="absolute right-2 top-2 grid h-5 w-5 place-items-center rounded-full bg-blue-600 text-white"><Check size={12} /></span>}
                    <IconPreview icon={scope === 'device' ? typeIcons.find((icon) => icon.id === catalog.type_defaults[deviceType]) : undefined} builtinUrl={builtinIconUrl(deviceType)} alt={scope === 'device' ? (isEnglish ? 'Follows the type default' : '跟随类型默认') : (isEnglish ? 'System default icon' : '系统默认图标')} size="tile" />
                    <span className="text-xs font-semibold text-slate-700">{scope === 'device' ? (isEnglish ? 'Follow type default' : '跟随类型默认') : (isEnglish ? 'System default' : '系统默认')}</span>
                    {((scope === 'type' && catalog.type_defaults[deviceType] == null)
                      || (scope === 'device' && !hasDeviceOverride))
                      && <span className="text-[10px] text-slate-500">{isEnglish ? 'Currently active' : '当前生效'}</span>}
                  </button>

                  {typeIcons.map((icon) => {
                    const isSelected = selectedIconId === icon.id;
                    const isTypeDefault = catalog.type_defaults[deviceType] === icon.id;
                    const isDeviceOverride = Boolean(matchingDeviceOverride?.icon_id === icon.id);
                    return <button type="button" key={icon.id} aria-pressed={isSelected} disabled={Boolean(busy)} onClick={() => setSelectedIconId(icon.id)} className={`group relative flex min-h-[108px] flex-col items-center justify-center gap-2 rounded-xl border p-3 text-center transition ${isSelected ? 'border-blue-500 bg-blue-50/70 ring-2 ring-blue-100' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'}`}>
                      {isSelected && <span className="absolute right-2 top-2 grid h-5 w-5 place-items-center rounded-full bg-blue-600 text-white"><Check size={12} /></span>}
                      <IconPreview icon={icon} alt={icon.name} size="tile" />
                      <span className="max-w-full truncate text-xs font-semibold text-slate-700" title={icon.name}>{icon.name}</span>
                      {(isTypeDefault || isDeviceOverride) && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">{isDeviceOverride ? (isEnglish ? 'Device override' : '单台使用') : (isEnglish ? 'Type default' : '类型默认')}</span>}
                    </button>;
                  })}
                </div>
              </div>

              {catalog.can_manage ? <section className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 p-4">
                <div className="flex items-center gap-2 text-sm font-bold text-slate-800"><ImagePlus size={17} className="text-blue-600" />{isEnglish ? 'Add a variant' : '上传新图标'}</div>
                <p className="mt-1 text-xs leading-5 text-slate-500">{isEnglish ? 'PNG or SVG, up to 4 MiB. Uploading adds a variant without changing the current assignment.' : '支持 PNG 或 SVG，文件不超过 4 MiB。上传只加入图标库，不会更改当前使用项。'}</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] sm:items-end">
                  <label className="block text-xs font-semibold text-slate-600">{isEnglish ? 'Variant name' : '图标名称'}
                    <input value={uploadName} onChange={(event) => setUploadName(event.target.value)} maxLength={80} placeholder={isEnglish ? 'e.g. Model A' : '例如：型号 A'} className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                  </label>
                  <label className="block text-xs font-semibold text-slate-600">{isEnglish ? 'PNG or SVG file' : 'PNG 或 SVG 文件'}
                    <input ref={uploadFileInputRef} type="file" accept="image/png,image/svg+xml,.png,.svg" onChange={(event) => {
                      setUploadFile(event.target.files?.[0] || null);
                      setUploadError('');
                    }} className="mt-1.5 block h-10 w-full cursor-pointer rounded-lg border border-slate-300 bg-white text-xs text-slate-600 file:mr-2 file:h-full file:border-0 file:bg-slate-100 file:px-3 file:font-semibold file:text-slate-700 hover:file:bg-slate-200" />
                  </label>
                  <button type="button" onClick={() => void uploadVariant()} disabled={busy !== null} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50">
                    {busy === 'upload' ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}{isEnglish ? 'Upload' : '上传'}
                  </button>
                </div>
                {uploadError && <p role="alert" className="mt-2 text-xs font-medium text-rose-700">{uploadError}</p>}
              </section> : <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs leading-5 text-slate-600">{isEnglish ? 'You can browse available icons. Ask an operator or administrator to add variants or change assignments.' : '当前为只读浏览。可由操作员或管理员上传图标并修改使用设置。'}</p>}
            </div>

            <aside className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4 lg:sticky lg:top-0 lg:self-start">
              {canChooseDeviceScope && <fieldset>
                <legend className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">{isEnglish ? 'Apply to' : '应用范围'}</legend>
                <div className="mt-2 grid grid-cols-2 rounded-lg bg-slate-200/75 p-1">
                  <button type="button" aria-pressed={scope === 'device'} onClick={() => selectScope('device')} className={`rounded-md px-2 py-2 text-xs font-semibold transition ${scope === 'device' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}>{isEnglish ? 'This device' : '仅此设备'}</button>
                  <button type="button" aria-pressed={scope === 'type'} onClick={() => selectScope('type')} className={`rounded-md px-2 py-2 text-xs font-semibold transition ${scope === 'type' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'}`}>{isEnglish ? 'Device type' : '设为类型默认'}</button>
                </div>
              </fieldset>}

              <div>
                <p className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">{isEnglish ? 'Canvas preview' : '画布效果预览'}</p>
                <div className="mt-2 flex min-h-[151px] flex-col items-center justify-center rounded-xl border border-slate-200 bg-[radial-gradient(circle,#aab8ca35_.7px,transparent_.8px)] bg-[length:13px_13px] p-4">
                  <IconPreview icon={previewIcon} builtinUrl={previewIcon ? undefined : builtinIconUrl(deviceType)} alt={selectedLabel} size="canvas" />
                  <span className="mt-1 max-w-full truncate rounded border border-slate-200 bg-white px-2 py-1 text-[11px] font-bold text-slate-700" title={device?.hostname || topologyIconTypeLabel(deviceType, language)}>{device?.hostname || topologyIconTypeLabel(deviceType, language)}</span>
                </div>
                <p className="mt-2 truncate text-xs text-slate-600" title={selectedLabel}>{isEnglish ? 'Selected' : '准备应用'} · {selectedLabel}</p>
                {scope === 'device' && device && !hasDeviceOverride && <p className="mt-1 text-[11px] leading-4 text-slate-500">{isEnglish ? 'This device follows the device-type default.' : '当前设备沿用类型默认图标。'}</p>}
                {scope === 'device' && hasDeviceOverride && <p className="mt-1 text-[11px] leading-4 text-slate-500">{isEnglish ? 'A device-specific icon is active.' : '当前设备已有单独图标设置。'}</p>}
              </div>

              {catalog.can_manage && scope === 'device' && device && <button type="button" disabled={busy !== null || !hasDeviceOverride} onClick={() => void restoreDeviceDefault()} className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"><RotateCcw size={14} />{isEnglish ? 'Follow type default' : '恢复类型默认'}</button>}

              {error && <p role="alert" className="break-words text-xs font-medium text-rose-700">{error}</p>}
              {notice && <p role="status" className="text-xs font-medium text-emerald-700">{notice}</p>}
            </aside>
          </div>
        </div>

        <footer className="flex flex-col-reverse gap-2 border-t border-slate-200 bg-white px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="text-xs text-slate-500">{selectionIsCurrent ? (isEnglish ? 'This choice is currently active.' : '当前选择已生效。') : (isEnglish ? 'Preview only until you apply this selection.' : '仅预览，确认后才会应用。')}</p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} disabled={Boolean(busy)} className="h-10 rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">{isEnglish ? 'Done' : '关闭'}</button>
            {catalog.can_manage && <button type="button" onClick={() => void applySelection()} disabled={Boolean(busy) || selectionIsCurrent} className="inline-flex h-10 min-w-[130px] items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none">
              {busy === 'apply' && <Loader2 size={15} className="animate-spin" />}
              {scope === 'device' ? (isEnglish ? 'Apply to device' : '应用到此设备') : (isEnglish ? 'Set type default' : '设为类型默认')}
            </button>}
          </div>
        </footer>
      </section>
    </div>
  );
};

export default TopologyIconLibrary;
