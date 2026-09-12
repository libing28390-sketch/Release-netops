import React from 'react';
import { X } from 'lucide-react';
import { Subnet, IPAddress } from '../types';
import { DEVICE_TYPES } from '../constants';
import { isValidIP, detectIPVersion, ipInSubnet } from '../helpers';

interface IPModalProps {
  language: string;
  selectedSubnet: Subnet | null;
  editingIP: IPAddress | null;
  formIP: {
    address: string;
    hostname: string;
    interface_name: string;
    mac_address: string;
    device_type: string;
    description: string;
    status: string;
  };
  setFormIP: React.Dispatch<
    React.SetStateAction<{
      address: string;
      hostname: string;
      interface_name: string;
      mac_address: string;
      device_type: string;
      description: string;
      status: string;
    }>
  >;
  onClose: () => void;
  onSubmit: () => void;
}

const IPModal: React.FC<IPModalProps> = ({
  language,
  selectedSubnet,
  editingIP,
  formIP,
  setFormIP,
  onClose,
  onSubmit,
}) => {
  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[80]"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold text-[#00172D]">
            {editingIP
              ? language === 'zh'
                ? '编辑 IP 地址'
                : 'Edit IP Address'
              : language === 'zh'
              ? '分配 IP 地址'
              : 'Allocate IP Address'}
          </h3>
          <button onClick={onClose} className="p-1 text-black/30 hover:text-black/60" title="Close">
            <X size={18} />
          </button>
        </div>
        {(() => {
          const ipOk = !formIP.address || isValidIP(formIP.address);
          const ipVersionMatch =
            !selectedSubnet ||
            !formIP.address ||
            !ipOk ||
            detectIPVersion(formIP.address) === detectIPVersion(selectedSubnet.network);
          const ipInRange =
            !selectedSubnet ||
            !ipOk ||
            !ipVersionMatch ||
            !formIP.address ||
            ipInSubnet(formIP.address, selectedSubnet.network, selectedSubnet.prefix_len);
          return (
            <>
              <div className="space-y-4">
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? 'IP 地址' : 'IP Address'}*
                  </label>
                  <input
                    value={formIP.address}
                    disabled={!!editingIP}
                    onChange={(e) => setFormIP((f) => ({ ...f, address: e.target.value }))}
                    placeholder="192.168.1.10"
                    className={`w-full mt-1 px-3 py-2 border rounded-lg text-sm outline-none focus:border-[#00bceb]/50 ${
                      !ipOk
                        ? 'border-red-300 bg-red-50/30'
                        : !ipVersionMatch
                        ? 'border-red-300 bg-red-50/30'
                        : !ipInRange
                        ? 'border-amber-300 bg-amber-50/30'
                        : 'border-black/10'
                    }`}
                  />
                  {!ipOk && (
                    <p className="text-[11px] text-red-500 mt-0.5">
                      {language === 'zh' ? 'IP 地址格式无效' : 'Invalid IP format'}
                    </p>
                  )}
                  {ipOk && !ipVersionMatch && (
                    <p className="text-[11px] text-red-500 mt-0.5">
                      {language === 'zh'
                        ? 'IP 版本与当前子网不一致'
                        : 'IP version mismatch with subnet'}
                    </p>
                  )}
                  {ipOk && ipVersionMatch && !ipInRange && (
                    <p className="text-[11px] text-amber-600 mt-0.5">
                      {language === 'zh' ? 'IP 地址超出当前子网范围' : 'IP address out of subnet range'}
                    </p>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-semibold text-black/40 uppercase">
                      {language === 'zh' ? '设备类型' : 'Device Type'}
                    </label>
                    <select
                      value={formIP.device_type}
                      onChange={(e) => setFormIP((f) => ({ ...f, device_type: e.target.value }))}
                      className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none bg-white focus:border-[#00bceb]/50"
                    >
                      {DEVICE_TYPES.map((dt) => (
                        <option key={dt.value} value={dt.value}>
                          {dt.label[language === 'zh' ? 'zh' : 'en']}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold text-black/40 uppercase">
                      {language === 'zh' ? '分配状态' : 'Status'}
                    </label>
                    <select
                      value={formIP.status}
                      onChange={(e) => setFormIP((f) => ({ ...f, status: e.target.value }))}
                      className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none bg-white focus:border-[#00bceb]/50"
                    >
                      <option value="active">
                        {language === 'zh' ? '使用中 (Active)' : 'Active'}
                      </option>
                      <option value="reserved">
                        {language === 'zh' ? '已预留 (Reserved)' : 'Reserved'}
                      </option>
                      <option value="deprecated">
                        {language === 'zh' ? '停用 (Deprecated)' : 'Deprecated'}
                      </option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] font-semibold text-black/40 uppercase">
                      {language === 'zh' ? '绑定主机名' : 'Hostname'}
                    </label>
                    <input
                      value={formIP.hostname}
                      onChange={(e) => setFormIP((f) => ({ ...f, hostname: e.target.value }))}
                      placeholder="server-01"
                      className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] font-semibold text-black/40 uppercase">
                      {language === 'zh' ? '接口名称' : 'Interface'}
                    </label>
                    <input
                      value={formIP.interface_name}
                      onChange={(e) => setFormIP((f) => ({ ...f, interface_name: e.target.value }))}
                      placeholder="GigabitEthernet1"
                      className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">MAC 地址</label>
                  <input
                    value={formIP.mac_address}
                    onChange={(e) => setFormIP((f) => ({ ...f, mac_address: e.target.value }))}
                    placeholder="52:54:00:12:34:56"
                    className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? '描述说明' : 'Description'}
                  </label>
                  <input
                    value={formIP.description}
                    onChange={(e) => setFormIP((f) => ({ ...f, description: e.target.value }))}
                    placeholder=" Beijing Core Switch Interface IP"
                    className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 mt-6 border-t border-black/5 pt-4">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 border border-black/8 rounded-xl text-xs font-semibold text-black/50 hover:bg-black/5 transition-all"
                >
                  {language === 'zh' ? '取消' : 'Cancel'}
                </button>
                <button
                  type="button"
                  onClick={onSubmit}
                  disabled={!formIP.address || !ipOk || !ipVersionMatch || !ipInRange}
                  className="px-4 py-2 rounded-xl bg-[#00bceb] hover:bg-[#00a5d0] disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold transition-all shadow-md shadow-[#00bceb]/10"
                >
                  {editingIP
                    ? language === 'zh'
                      ? '保存修改'
                      : 'Save Changes'
                    : language === 'zh'
                    ? '确认分配'
                    : 'Allocate'}
                </button>
              </div>
            </>
          );
        })()}
      </div>
    </div>
  );
};

export default IPModal;
