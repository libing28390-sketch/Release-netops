import { useCallback } from 'react';
import * as XLSX from 'xlsx';
import type { Device } from '../types';
import { exportInventoryToExcel } from '../utils/inventoryExport';
import { useInventoryStore } from '../store/inventoryStore';

interface UseInventoryImportExportArgs {
  devices: Device[];
  setDevices: React.Dispatch<React.SetStateAction<Device[]>>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  t: (key: string) => string;
}

export const useInventoryImportExport = ({
  devices,
  setDevices,
  showToast,
  t,
}: UseInventoryImportExportArgs) => {
  const setInventoryRefreshTick = useInventoryStore((s) => s.setInventoryRefreshTick);
  const setInventoryPage = useInventoryStore((s) => s.setInventoryPage);

  const handleExport = useCallback(() => {
    exportInventoryToExcel(devices);
  }, [devices]);

  const handleImport = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (loadEvent) => {
      try {
        const data = new Uint8Array(loadEvent.target?.result as ArrayBuffer);
        const workbook = XLSX.read(data, { type: 'array' });
        const firstSheetName = workbook.SheetNames[0];
        const worksheet = workbook.Sheets[firstSheetName];
        const jsonData = XLSX.utils.sheet_to_json<any>(worksheet);

        if (jsonData && jsonData.length > 0) {
          const existingHostnames = new Set(devices.map((d) => d.hostname));
          const existingIps = new Set(devices.map((d) => d.ip_address));

          const newDevices: Device[] = [];
          let skippedCount = 0;

          jsonData.forEach((item, index) => {
            const hostname = item.hostname || item['Device Info'] || item['主机名'] || `Unknown-${index}`;
            const ip_address = item.ip_address || item['IP Address'] || item['IP地址'] || '0.0.0.0';

            if (existingHostnames.has(hostname) || existingIps.has(ip_address)) {
              skippedCount++;
              return;
            }

            newDevices.push({
              id: String(Date.now() + index),
              hostname,
              ip_address,
              platform: item.platform || item['Platform'] || item['平台'] || 'unknown',
              status: item.status || item['Status'] || item['状态'] || 'pending',
              compliance: item.compliance || item['Compliance'] || item['合规性'] || 'unknown',
              sn: item.sn || item['SN'] || item['序列号'] || '',
              model: item.model || item['Model'] || item['型号'] || '',
              version: item.version || item['Version'] || item['版本'] || '',
              role: item.role || item['Role'] || item['角色'] || '',
              site: item.site || item['Site'] || item['站点'] || '',
              uptime: item.uptime || item['Uptime'] || item['运行时间'] || '0d 0h',
              connection_method: item.connection_method || item['Method'] || item['连接方式'] || 'ssh',
              config_history: [],
            });

            existingHostnames.add(hostname);
            existingIps.add(ip_address);
          });

          if (newDevices.length > 0) {
            fetch('/api/devices/import', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ devices: newDevices }),
            })
              .then((res) => res.json())
              .then((response) => {
                if (response.status === 'success') {
                  setDevices((prev) => [...prev, ...newDevices]);
                  setInventoryRefreshTick((v) => v + 1);
                  setInventoryPage(1);
                  const msg = t('importSuccess').replace('{{count}}', newDevices.length.toString())
                    + (skippedCount > 0 ? t('importSkipped').replace('{{count}}', skippedCount.toString()) : '');
                  showToast(msg, 'success');
                } else {
                  showToast(`Import failed: ${response.error}`, 'error');
                }
              })
              .catch((err) => {
                showToast(`Import error: ${err}`, 'error');
              });
          } else if (skippedCount > 0) {
            showToast(t('importNoNew').replace('{{count}}', skippedCount.toString()), 'info');
          }
        }
      } catch {
        showToast(t('importError'), 'error');
      }
    };
    reader.readAsArrayBuffer(file);
    event.target.value = '';
  }, [devices, setDevices, setInventoryRefreshTick, setInventoryPage, showToast, t]);

  return { handleImport, handleExport };
};
