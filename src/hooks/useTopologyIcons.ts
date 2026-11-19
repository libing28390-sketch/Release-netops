import { useCallback, useEffect, useMemo, useState } from 'react';
import { getTopologyIconCatalog, getTopologyIconDataUrl, type TopologyIconCatalog } from '../api/topologyIcons';
import { getBuiltInTopologyIconUrl, getTopologyDeviceIconType } from '../domain/topologyDeviceIcons';

type IconDevice = Parameters<typeof getTopologyDeviceIconType>[0] & { id: string };

function iconChoices(device: IconDevice, catalog: TopologyIconCatalog | null) {
  const type = getTopologyDeviceIconType(device);
  const override = catalog?.device_overrides[device.id];
  return {
    type,
    overrideId: override?.device_type === type ? override.icon_id : undefined,
    defaultId: catalog?.type_defaults[type],
  };
}

export function useTopologyIcons(devices: IconDevice[], enabled = true) {
  const [catalog, setCatalog] = useState<TopologyIconCatalog | null>(null);
  const [images, setImages] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    const next = await getTopologyIconCatalog();
    setCatalog(next);
  }, []);

  useEffect(() => {
    if (!enabled || !window.localStorage.getItem('netops_token')) return;
    void reload().catch(() => {
      // The built-in icons remain usable on an older or unavailable server.
    });
  }, [enabled, reload]);

  const usedIcons = useMemo(() => {
    if (!enabled || !catalog) return [];
    const ids = new Set(devices.flatMap((device) => {
      const { overrideId, defaultId } = iconChoices(device, catalog);
      return [overrideId, defaultId];
    }));
    return catalog.icons.filter((icon) => ids.has(icon.id));
  }, [enabled, devices, catalog]);

  useEffect(() => {
    if (!usedIcons.length) return;
    let active = true;
    void Promise.all(usedIcons.map(async (icon): Promise<[string, string] | null> => {
      try {
        return [icon.id, await getTopologyIconDataUrl(icon)];
      } catch {
        return null;
      }
    })).then((items) => {
      if (active) setImages(Object.fromEntries(items.filter((item) => item !== null)));
    });
    return () => { active = false; };
  }, [usedIcons]);

  const customIconUrl = useCallback((device: IconDevice) => {
    const { overrideId, defaultId } = iconChoices(device, catalog);
    return (overrideId ? images[overrideId] : undefined) || (defaultId ? images[defaultId] : undefined);
  }, [catalog, images]);

  const iconUrl = useCallback((device: IconDevice) => (
    customIconUrl(device) || getBuiltInTopologyIconUrl(getTopologyDeviceIconType(device))
  ), [customIconUrl]);

  return { catalog, reload, customIconUrl, iconUrl };
}
