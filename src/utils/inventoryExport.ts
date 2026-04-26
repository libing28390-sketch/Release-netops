import * as XLSX from 'xlsx';
import type { Device } from '../types';

export const exportInventoryToExcel = (devices: Device[]) => {
  const exportData = devices.map(({ current_config, config_history, ...rest }) => rest);
  const worksheet = XLSX.utils.json_to_sheet(exportData);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, 'Inventory');
  const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
  XLSX.writeFile(workbook, `network_inventory_${ts}.xlsx`);
};
