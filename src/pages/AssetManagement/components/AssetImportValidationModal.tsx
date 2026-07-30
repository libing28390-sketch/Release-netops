import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { AlertTriangle, Shield, Check, ArrowRight, X } from 'lucide-react';

export interface MissingRackInfo {
  datacenter: string;
  rack: string;
  rowCount: number;
}

export type ResolutionAction = 'create' | 'skip' | 'map';

export interface RackResolution {
  action: ResolutionAction;
  targetRack?: string;
}

interface AssetImportValidationModalProps {
  isOpen: boolean;
  onClose: () => void;
  language: string;
  missingRacks: MissingRackInfo[];
  existingRacks: any[];
  onConfirm: (resolutions: Record<string, RackResolution>) => void;
  saving: boolean;
}

export const AssetImportValidationModal: React.FC<AssetImportValidationModalProps> = ({
  isOpen,
  onClose,
  language,
  missingRacks,
  existingRacks,
  onConfirm,
  saving,
}) => {
  const zh = language === 'zh';
  
  // Key format: "datacenter|rack"
  const [resolutions, setResolutions] = React.useState<Record<string, RackResolution>>({});

  React.useEffect(() => {
    if (isOpen) {
      const initial: Record<string, RackResolution> = {};
      missingRacks.forEach(mr => {
        const key = `${mr.datacenter}|${mr.rack}`;
        initial[key] = { action: 'create' };
      });
      setResolutions(initial);
    }
  }, [isOpen, missingRacks]);

  if (!isOpen) return null;

  const handleActionChange = (key: string, action: ResolutionAction) => {
    setResolutions(prev => ({
      ...prev,
      [key]: {
        ...prev[key],
        action,
        // Default targetRack to first match or empty if mapping
        targetRack: action === 'map' ? (prev[key].targetRack || '') : undefined
      }
    }));
  };

  const handleTargetChange = (key: string, val: string) => {
    setResolutions(prev => ({
      ...prev,
      [key]: {
        ...prev[key],
        targetRack: val
      }
    }));
  };

  const handleSubmit = () => {
    onConfirm(resolutions);
  };

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="bg-white rounded-2xl w-[680px] max-w-[95vw] h-[80vh] shadow-2xl flex flex-col relative overflow-hidden border border-black/5"
          onClick={e => e.stopPropagation()}
          initial={{ scale: 0.98, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.98, opacity: 0 }}
        >
          {/* Header */}
          <div className="shrink-0 px-5 py-4 border-b border-black/5 bg-amber-50 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertTriangle className="text-amber-500" size={18} />
              <h3 className="text-sm font-bold text-amber-900">
                {zh ? '导入数据校验：发现未注册机柜' : 'Import Verification: Missing Racks Found'}
              </h3>
            </div>
            <button onClick={onClose} className="p-1 rounded-md hover:bg-black/5 text-black/25">
              <X size={16} />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            <p className="text-xs leading-relaxed text-black/60">
              {zh
                ? '系统检测到 Excel 文件中有部分设备的机柜属性在 CMDB 中不存在。为了避免直接导入产生错误，请为以下缺失机柜选择处理方式：'
                : 'The system detected that some devices in the Excel refer to racks that do not exist in the CMDB. Please specify how to resolve each missing rack:'}
            </p>

            <div className="border border-black/8 rounded-xl overflow-hidden bg-black/[0.01]">
              <table className="nx-data-table nx-data-table--compact text-xs text-left">
                <thead>
                  <tr className="bg-black/[0.03] border-b border-black/8 font-bold text-black/50">
                    <th className="px-4 py-2.5">{zh ? '站点' : 'Site'}</th>
                    <th className="px-4 py-2.5">{zh ? '缺失机柜名称' : 'Missing Rack'}</th>
                    <th className="px-4 py-2.5 text-center">{zh ? '影响行数' : 'Rows Affected'}</th>
                    <th className="px-4 py-2.5 w-[280px]">{zh ? '处理策略' : 'Resolution Action'}</th>
                  </tr>
                </thead>
                <tbody>
                  {missingRacks.map(mr => {
                    const key = `${mr.datacenter}|${mr.rack}`;
                    const current = resolutions[key] || { action: 'create' };
                    // Filter existing racks in the same DC
        const dcRacks = existingRacks.filter(r => r.site_id ? r.site_id === mr.datacenter : r.datacenter === mr.datacenter);

                    return (
                      <tr key={key} className="border-b border-black/5 hover:bg-black/[0.01]">
                        <td className="px-4 py-3 font-mono font-medium">{mr.datacenter || '-'}</td>
                        <td className="px-4 py-3 font-semibold text-black/75">{mr.rack}</td>
                        <td className="px-4 py-3 text-center text-black/45">{mr.rowCount} {zh ? '台设备' : 'devices'}</td>
                        <td className="px-4 py-3 space-y-2">
                          <select
                            value={current.action}
                            title={zh ? '处理方式' : 'Action'}
                            onChange={e => handleActionChange(key, e.target.value as ResolutionAction)}
                            className="w-full bg-white border border-black/8 rounded-lg px-2 py-1 text-xs text-black/65 outline-none focus:border-[#00bceb]/25"
                          >
                            <option value="create">{zh ? '自动新建此机柜 (默认42U)' : 'Auto-Create Rack (42U)'}</option>
                            <option value="map" disabled={dcRacks.length === 0}>
                              {zh 
                                ? (dcRacks.length > 0 ? '映射替换为已有机柜' : '映射替换 (当前DC无可用机柜)') 
                                : 'Map to Existing Rack'}
                            </option>
                            <option value="skip">{zh ? '跳过导入这些设备' : 'Skip These Devices'}</option>
                          </select>

                          {current.action === 'map' && dcRacks.length > 0 && (
                            <select
                              value={current.targetRack || ''}
                              title={zh ? '映射的机柜' : 'Target Rack'}
                              onChange={e => handleTargetChange(key, e.target.value)}
                              className="w-full bg-white border border-amber-400 rounded-lg px-2 py-1 text-xs text-amber-800 outline-none"
                            >
                              <option value="">{zh ? '请选择目标机柜...' : 'Select target rack...'}</option>
                              {dcRacks.map(r => (
                                <option key={r.id} value={r.name}>{r.name} ({r.total_u}U)</option>
                              ))}
                            </select>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Footer */}
          <div className="shrink-0 border-t border-black/5 bg-white px-5 py-3 flex justify-end gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]"
            >
              {zh ? '取消' : 'Cancel'}
            </button>
            <button
              onClick={handleSubmit}
              disabled={saving || Object.values(resolutions).some(r => r.action === 'map' && !r.targetRack)}
              className="px-4 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50 shadow-sm shadow-[#00bceb]/20 flex items-center gap-1.5"
            >
              {saving ? (zh ? '导入中...' : 'Importing...') : (zh ? '确认并继续导入' : 'Confirm & Proceed')}
              <ArrowRight size={13} />
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
