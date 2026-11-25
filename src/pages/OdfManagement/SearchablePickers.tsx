import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Loader2, Search, X } from 'lucide-react';

export interface DeviceOption {
  id: string;
  hostname: string;
  ip_address: string;
  vendor?: string;
  model?: string;
  rack_name?: string;
}

export interface InterfaceOption {
  interface_name: string;
  oper_status?: string;
  speed?: string;
  description?: string;
}

function mergeDeviceLists(primary: DeviceOption[], secondary: DeviceOption[]): DeviceOption[] {
  const map = new Map<string, DeviceOption>();
  for (const item of primary) {
    if (item?.id) map.set(item.id, item);
  }
  for (const item of secondary) {
    if (item?.id && !map.has(item.id)) map.set(item.id, item);
  }
  return Array.from(map.values());
}

function matchesDeviceQuery(device: DeviceOption, q: string): boolean {
  if (!q) return true;
  const hay = [
    device.hostname,
    device.ip_address,
    device.vendor,
    device.model,
    device.rack_name,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return hay.includes(q);
}

interface SearchableDevicePickerProps {
  valueId: string;
  valueName: string;
  initialDevices: DeviceOption[];
  onSearchRemote?: (q: string) => Promise<DeviceOption[]>;
  onSelect: (device: DeviceOption | null) => void;
  placeholder?: string;
  zh: boolean;
}

export const SearchableDevicePicker: React.FC<SearchableDevicePickerProps> = ({
  valueId,
  valueName,
  initialDevices,
  onSearchRemote,
  onSelect,
  placeholder,
  zh,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const selectedDevice = useMemo(
    () => (valueId ? initialDevices.find(d => d.id === valueId) || null : null),
    [valueId, initialDevices],
  );
  const formattedSelected = selectedDevice
    ? `${selectedDevice.hostname} (${selectedDevice.ip_address})`
    : valueId && valueName
      ? valueName
      : '';

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(formattedSelected);
  const [remoteItems, setRemoteItems] = useState<DeviceOption[]>([]);
  const [loadingRemote, setLoadingRemote] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  // Sync display value when editing a different port
  useEffect(() => {
    if (!open) {
      setQuery(formattedSelected);
    }
  }, [formattedSelected, open]);

  // Close popover on click outside
  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onMouseDown);
    return () => document.removeEventListener('mousedown', onMouseDown);
  }, []);

  // Debounced backend CMDB search so large fleets (100+ devices) are fully searchable
  useEffect(() => {
    if (!open || !onSearchRemote) return;
    const trimmed = query.trim();
    if (!trimmed || trimmed === formattedSelected) {
      setRemoteItems([]);
      setLoadingRemote(false);
      return;
    }
    let cancelled = false;
    setLoadingRemote(true);
    const timer = window.setTimeout(async () => {
      try {
        const res = await onSearchRemote(trimmed);
        if (!cancelled) setRemoteItems(Array.isArray(res) ? res : []);
      } catch {
        if (!cancelled) setRemoteItems([]);
      } finally {
        if (!cancelled) setLoadingRemote(false);
      }
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, query, formattedSelected, onSearchRemote]);

  const effectiveFilter = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    if (formattedSelected && trimmed === formattedSelected.toLowerCase()) return '';
    return trimmed;
  }, [query, formattedSelected]);

  const options = useMemo(() => {
    const combined = mergeDeviceLists(remoteItems, initialDevices);
    return combined.filter(d => matchesDeviceQuery(d, effectiveFilter)).slice(0, 50);
  }, [remoteItems, initialDevices, effectiveFilter]);

  useEffect(() => {
    setActiveIndex(0);
  }, [options.length, open]);

  const pickOption = (dev: DeviceOption) => {
    onSelect(dev);
    setQuery(`${dev.hostname} (${dev.ip_address})`);
    setOpen(false);
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation();
    setQuery('');
    setRemoteItems([]);
    onSelect(null);
    setOpen(true);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) {
      setOpen(true);
      return;
    }
    if (!open || options.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex(prev => (prev + 1) % options.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex(prev => (prev - 1 + options.length) % options.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const target = options[activeIndex] || options[0];
      if (target) pickOption(target);
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <div
        className="flex items-center gap-1.5 rounded-lg border px-2 py-1.5"
        style={{ background: 'var(--input-bg)', borderColor: open ? '#06b6d4' : 'var(--card-border)' }}
      >
        <Search size={12} className="shrink-0 text-slate-400" />
        <input
          value={query}
          onFocus={() => setOpen(true)}
          onChange={e => {
            setQuery(e.target.value);
            if (!open) setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || (zh ? '搜索设备名 / IP / 型号 / 机柜…' : 'Search device, IP, model, rack…')}
          className="min-w-0 flex-1 bg-transparent text-xs outline-none"
          style={{ color: 'var(--body-text)' }}
          aria-label={zh ? '搜索 CMDB 网络设备' : 'Search CMDB device'}
        />
        {loadingRemote && <Loader2 size={12} className="shrink-0 animate-spin text-cyan-500" />}
        {(valueId || query) && (
          <button
            type="button"
            onClick={handleClear}
            className="rounded p-0.5 text-slate-400 hover:bg-slate-500/15 hover:text-slate-200"
            title={zh ? '清除已选设备' : 'Clear selected device'}
          >
            <X size={12} />
          </button>
        )}
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className="rounded p-0.5 text-slate-400 hover:text-slate-200"
          aria-label="Toggle device list"
        >
          <ChevronDown size={12} className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
        </button>
      </div>

      {open && (
        <div
          className="absolute left-0 right-0 z-40 mt-1 max-h-56 overflow-y-auto rounded-xl border shadow-2xl"
          style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
        >
          {options.length === 0 ? (
            <div className="px-3 py-3 text-center text-[11px]" style={{ color: 'var(--muted-text)' }}>
              {loadingRemote
                ? (zh ? '正在检索 CMDB 设备…' : 'Searching CMDB devices…')
                : (zh ? '未找到匹配的 CMDB 设备，可在下方手填' : 'No matching CMDB device')}
            </div>
          ) : (
            options.map((dev, idx) => {
              const isSelected = dev.id === valueId;
              const isActive = idx === activeIndex;
              return (
                <button
                  key={dev.id}
                  type="button"
                  onMouseEnter={() => setActiveIndex(idx)}
                  onMouseDown={e => {
                    e.preventDefault();
                    pickOption(dev);
                  }}
                  className={`flex w-full flex-col gap-0.5 border-b px-2.5 py-1.5 text-left last:border-b-0 ${
                    isSelected
                      ? 'bg-cyan-500/15 text-cyan-400'
                      : isActive
                        ? 'bg-slate-500/10'
                        : 'hover:bg-slate-500/10'
                  }`}
                  style={{ borderColor: 'var(--card-border)' }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-semibold" style={{ color: isSelected ? undefined : 'var(--heading-text)' }}>
                      {dev.hostname}
                    </span>
                    {dev.rack_name && (
                      <span className="shrink-0 rounded border border-cyan-500/35 bg-cyan-500/10 px-1.5 py-0.5 font-mono text-[9px] text-cyan-500">
                        {dev.rack_name}
                      </span>
                    )}
                  </div>
                  <div className="truncate font-mono text-[10px]" style={{ color: 'var(--muted-text)' }}>
                    {dev.ip_address}
                    {(dev.vendor || dev.model) ? ` · ${[dev.vendor, dev.model].filter(Boolean).join(' ')}` : ''}
                  </div>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
};

interface SearchableInterfacePickerProps {
  value: string;
  options: InterfaceOption[];
  loading?: boolean;
  onChange: (value: string) => void;
  placeholder?: string;
  zh: boolean;
}

export const SearchableInterfacePicker: React.FC<SearchableInterfacePickerProps> = ({
  value,
  options,
  loading = false,
  onChange,
  placeholder,
  zh,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onMouseDown);
    return () => document.removeEventListener('mousedown', onMouseDown);
  }, []);

  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return options.slice(0, 60);
    return options
      .filter(itf =>
        itf.interface_name.toLowerCase().includes(q)
        || (itf.description || '').toLowerCase().includes(q),
      )
      .slice(0, 60);
  }, [options, value]);

  useEffect(() => {
    setActiveIndex(0);
  }, [filtered.length, open]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      setOpen(false);
      return;
    }
    if (!open && e.key === 'ArrowDown' && filtered.length > 0) {
      setOpen(true);
      return;
    }
    if (!open || filtered.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex(prev => (prev + 1) % filtered.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex(prev => (prev - 1 + filtered.length) % filtered.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const target = filtered[activeIndex] || filtered[0];
      if (target) {
        onChange(target.interface_name);
        setOpen(false);
      }
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <div
        className="flex items-center gap-1.5 rounded-lg border px-2 py-1.5"
        style={{ background: 'var(--input-bg)', borderColor: open ? '#06b6d4' : 'var(--card-border)' }}
      >
        <input
          value={value}
          onFocus={() => setOpen(true)}
          onChange={e => {
            onChange(e.target.value);
            if (!open) setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || (zh ? '搜索或手填物理接口（如 GE1/0/49）' : 'Search or type interface…')}
          className="min-w-0 flex-1 bg-transparent font-mono text-xs outline-none"
          style={{ color: 'var(--body-text)' }}
          aria-label={zh ? '搜索物理接口' : 'Search interface'}
        />
        {loading && <Loader2 size={12} className="shrink-0 animate-spin text-cyan-500" />}
        {value && (
          <button
            type="button"
            onClick={() => {
              onChange('');
              setOpen(true);
            }}
            className="rounded p-0.5 text-slate-400 hover:bg-slate-500/15"
            title={zh ? '清空接口' : 'Clear interface'}
          >
            <X size={11} />
          </button>
        )}
        {options.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen(o => !o)}
            className="rounded p-0.5 text-slate-400 hover:text-slate-200"
            aria-label="Toggle interface list"
          >
            <ChevronDown size={12} className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
          </button>
        )}
      </div>

      {open && options.length > 0 && (
        <div
          className="absolute left-0 right-0 z-40 mt-1 max-h-48 overflow-y-auto rounded-xl border shadow-2xl"
          style={{ background: 'var(--card-bg)', borderColor: 'var(--card-border)' }}
        >
          {filtered.length === 0 ? (
            <div className="px-2.5 py-2 text-[11px]" style={{ color: 'var(--muted-text)' }}>
              {zh ? '无匹配已采集端口，将按手动输入保存' : 'No matching interface; custom value will be kept'}
            </div>
          ) : (
            filtered.map((itf, idx) => {
              const isUp = String(itf.oper_status || '').toLowerCase() === 'up';
              const isActive = idx === activeIndex;
              return (
                <button
                  key={itf.interface_name}
                  type="button"
                  onMouseEnter={() => setActiveIndex(idx)}
                  onMouseDown={e => {
                    e.preventDefault();
                    onChange(itf.interface_name);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center justify-between gap-2 border-b px-2.5 py-1.5 text-left last:border-b-0 ${
                    isActive ? 'bg-slate-500/10' : 'hover:bg-slate-500/10'
                  }`}
                  style={{ borderColor: 'var(--card-border)' }}
                >
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${isUp ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                    <span className="truncate font-mono text-[11px] font-medium" style={{ color: 'var(--heading-text)' }}>
                      {itf.interface_name}
                    </span>
                  </div>
                  {itf.description && (
                    <span className="max-w-[96px] truncate text-[10px]" style={{ color: 'var(--muted-text)' }}>
                      {itf.description}
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
};
