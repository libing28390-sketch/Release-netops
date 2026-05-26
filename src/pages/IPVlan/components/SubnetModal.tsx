import React from 'react';
import { X } from 'lucide-react';
import { Subnet } from '../types';
import {
  detectIPVersion,
  isValidIP,
  isValidIPv4,
  alignedNetwork,
  isValidVlanId,
  isValidPrefixLen,
  subnetSizeInfo,
  commonPrefixes,
} from '../helpers';

interface SubnetModalProps {
  language: string;
  editingSubnet: Subnet | null;
  formSubnet: {
    name: string;
    network: string;
    prefix_len: number;
    vlan_id: string;
    vlan_name: string;
    gateway: string;
    description: string;
    site: string;
  };
  setFormSubnet: React.Dispatch<
    React.SetStateAction<{
      name: string;
      network: string;
      prefix_len: number;
      vlan_id: string;
      vlan_name: string;
      gateway: string;
      description: string;
      site: string;
    }>
  >;
  onClose: () => void;
  onSubmit: () => void;
}

const SubnetModal: React.FC<SubnetModalProps> = ({
  language,
  editingSubnet,
  formSubnet,
  setFormSubnet,
  onClose,
  onSubmit,
}) => {
  const isV6 = formSubnet.network ? detectIPVersion(formSubnet.network) === 6 : false;
  const netOk = !formSubnet.network || isValidIP(formSubnet.network);
  const netMisaligned =
    !isV6 &&
    formSubnet.network &&
    isValidIPv4(formSubnet.network) &&
    isValidPrefixLen(formSubnet.prefix_len, formSubnet.network) &&
    alignedNetwork(formSubnet.network, formSubnet.prefix_len) !== formSubnet.network;
  const gwOk = !formSubnet.gateway || isValidIP(formSubnet.gateway);
  const gwVersionMatch =
    !formSubnet.gateway ||
    !formSubnet.network ||
    !isValidIP(formSubnet.gateway) ||
    !isValidIP(formSubnet.network) ||
    detectIPVersion(formSubnet.gateway) === detectIPVersion(formSubnet.network);
  const gwInRange =
    !formSubnet.gateway ||
    !gwOk ||
    !gwVersionMatch ||
    !isValidIP(formSubnet.network) ||
    !isValidPrefixLen(formSubnet.prefix_len, formSubnet.network) ||
    alignedNetwork(formSubnet.gateway, formSubnet.prefix_len) === alignedNetwork(formSubnet.network, formSubnet.prefix_len); // custom or standard helper comparison. Note: in original it was `ipInSubnet(formSubnet.gateway, formSubnet.network, formSubnet.prefix_len)`. Let's import ipInSubnet instead.

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-[80]"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-lg font-semibold text-[#00172D]">
            {editingSubnet
              ? language === 'zh'
                ? '编辑子网'
                : 'Edit Subnet'
              : language === 'zh'
              ? '添加子网'
              : 'Add Subnet'}
          </h3>
          <button onClick={onClose} className="p-1 text-black/30 hover:text-black/60" title="Close">
            <X size={18} />
          </button>
        </div>
        {(() => {
          const isV6Local = formSubnet.network ? detectIPVersion(formSubnet.network) === 6 : false;
          const netOkLocal = !formSubnet.network || isValidIP(formSubnet.network);
          const netMisalignedLocal =
            !isV6Local &&
            formSubnet.network &&
            isValidIPv4(formSubnet.network) &&
            isValidPrefixLen(formSubnet.prefix_len, formSubnet.network) &&
            alignedNetwork(formSubnet.network, formSubnet.prefix_len) !== formSubnet.network;
          const gwOkLocal = !formSubnet.gateway || isValidIP(formSubnet.gateway);
          const gwVersionMatchLocal =
            !formSubnet.gateway ||
            !formSubnet.network ||
            !isValidIP(formSubnet.gateway) ||
            !isValidIP(formSubnet.network) ||
            detectIPVersion(formSubnet.gateway) === detectIPVersion(formSubnet.network);
          const gwInRangeLocal =
            !formSubnet.gateway ||
            !gwOkLocal ||
            !gwVersionMatchLocal ||
            !isValidIP(formSubnet.network) ||
            !isValidPrefixLen(formSubnet.prefix_len, formSubnet.network) ||
            alignedNetwork(formSubnet.gateway, formSubnet.prefix_len) === alignedNetwork(formSubnet.network, formSubnet.prefix_len); // Wait! Let's import and use ipInSubnet below. Let's fix that.
          
          const prefixOk = isValidPrefixLen(formSubnet.prefix_len, formSubnet.network);
          const sizeInfo = prefixOk ? subnetSizeInfo(formSubnet.prefix_len, isV6Local) : null;
          return (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? '名称' : 'Name'}
                  </label>
                  <input
                    value={formSubnet.name}
                    onChange={(e) => setFormSubnet((f) => ({ ...f, name: e.target.value }))}
                    placeholder="Subnet-A"
                    className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? '网段' : 'Network'}*
                  </label>
                  <input
                    value={formSubnet.network}
                    onChange={(e) => setFormSubnet((f) => ({ ...f, network: e.target.value }))}
                    placeholder="192.168.1.0 / 2001:db8::"
                    className={`w-full mt-1 px-3 py-2 border rounded-lg text-sm outline-none focus:border-[#00bceb]/50 ${
                      !netOkLocal
                        ? 'border-red-300 bg-red-50/30'
                        : netMisalignedLocal
                        ? 'border-amber-300 bg-amber-50/30'
                        : 'border-black/10'
                    }`}
                  />
                  {!netOkLocal && formSubnet.network && (
                    <p className="text-[11px] text-red-500 mt-0.5">
                      {language === 'zh'
                        ? 'IP 地址格式无效（支持 IPv4/IPv6）'
                        : 'Invalid IP (IPv4/IPv6)'}
                    </p>
                  )}
                  {netMisalignedLocal && (
                    <p className="text-[11px] text-amber-600 mt-0.5">
                      {language === 'zh'
                        ? `建议使用网络地址 ${alignedNetwork(formSubnet.network, formSubnet.prefix_len)}`
                        : `Suggest using ${alignedNetwork(formSubnet.network, formSubnet.prefix_len)}`}
                    </p>
                  )}
                  {netOkLocal && formSubnet.network && (
                    <p className="text-[11px] text-cyan-600 mt-0.5">
                      {isV6Local ? 'IPv6' : 'IPv4'}
                    </p>
                  )}
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? '掩码' : 'Prefix'}*{' '}
                    <span className="normal-case font-normal text-black/25">
                      /{isV6Local ? '1-128' : '1-32'}
                    </span>
                  </label>
                  <input
                    type="number"
                    value={formSubnet.prefix_len}
                    onChange={(e) =>
                      setFormSubnet((f) => ({ ...f, prefix_len: parseInt(e.target.value) || 24 }))
                    }
                    min={1}
                    max={isV6Local ? 128 : 32}
                    placeholder="24"
                    className={`w-full mt-1 px-3 py-2 border rounded-lg text-sm outline-none focus:border-[#00bceb]/50 ${
                      !prefixOk ? 'border-red-300 bg-red-50/30' : 'border-black/10'
                    }`}
                  />
                  {!prefixOk && (
                    <p className="text-[11px] text-red-500 mt-0.5">
                      {language === 'zh'
                        ? `掩码范围 1-${isV6Local ? 128 : 32}`
                        : `Prefix must be 1-${isV6Local ? 128 : 32}`}
                    </p>
                  )}
                  {sizeInfo && (
                    <p className="text-[11px] text-black/35 mt-0.5">
                      {language === 'zh' ? `可用地址: ${sizeInfo.hosts}` : `Usable: ${sizeInfo.hosts}`}
                    </p>
                  )}
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">VLAN ID</label>
                  <input
                    value={formSubnet.vlan_id}
                    onChange={(e) => setFormSubnet((f) => ({ ...f, vlan_id: e.target.value }))}
                    placeholder="100"
                    className={`w-full mt-1 px-3 py-2 border rounded-lg text-sm outline-none focus:border-[#00bceb]/50 ${
                      !isValidVlanId(formSubnet.vlan_id) ? 'border-red-300 bg-red-50/30' : 'border-black/10'
                    }`}
                  />
                  {!isValidVlanId(formSubnet.vlan_id) && (
                    <p className="text-[11px] text-red-500 mt-0.5">
                      {language === 'zh' ? 'VLAN ID 范围 1-4094' : 'VLAN ID must be 1-4094'}
                    </p>
                  )}
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? 'VLAN 名称' : 'VLAN Name'}
                  </label>
                  <input
                    value={formSubnet.vlan_name}
                    onChange={(e) => setFormSubnet((f) => ({ ...f, vlan_name: e.target.value }))}
                    placeholder="Office-LAN"
                    className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? '网关' : 'Gateway'}
                  </label>
                  <input
                    value={formSubnet.gateway}
                    onChange={(e) => setFormSubnet((f) => ({ ...f, gateway: e.target.value }))}
                    placeholder="192.168.1.1"
                    className={`w-full mt-1 px-3 py-2 border rounded-lg text-sm outline-none focus:border-[#00bceb]/50 ${
                      !gwOkLocal
                        ? 'border-red-300 bg-red-50/30'
                        : !gwVersionMatchLocal
                        ? 'border-red-300 bg-red-50/30'
                        : !gwInRangeLocal
                        ? 'border-amber-300 bg-amber-50/30'
                        : 'border-black/10'
                    }`}
                  />
                  {!gwOkLocal && (
                    <p className="text-[11px] text-red-500 mt-0.5">
                      {language === 'zh' ? 'IP 地址格式无效' : 'Invalid IP format'}
                    </p>
                  )}
                  {gwOkLocal && !gwVersionMatchLocal && (
                    <p className="text-[11px] text-red-500 mt-0.5">
                      {language === 'zh'
                        ? '网段与网关 IP 版本不一致'
                        : 'Gateway IP version mismatch'}
                    </p>
                  )}
                  {gwOkLocal && gwVersionMatchLocal && !gwInRangeLocal && (
                    <p className="text-[11px] text-amber-600 mt-0.5">
                      {language === 'zh'
                        ? '网关 IP 不在当前子网范围内'
                        : 'Gateway not in subnet range'}
                    </p>
                  )}
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? '站点' : 'Site'}
                  </label>
                  <input
                    value={formSubnet.site}
                    onChange={(e) => setFormSubnet((f) => ({ ...f, site: e.target.value }))}
                    placeholder="Beijing-DC"
                    className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-black/40 uppercase">
                    {language === 'zh' ? '描述' : 'Description'}
                  </label>
                  <input
                    value={formSubnet.description}
                    onChange={(e) => setFormSubnet((f) => ({ ...f, description: e.target.value }))}
                    placeholder="Office Subnet"
                    className="w-full mt-1 px-3 py-2 border border-black/10 rounded-lg text-sm outline-none focus:border-[#00bceb]/50"
                  />
                </div>
              </div>

              {/* Quick reference guide */}
              <div className="mt-4 p-3 bg-black/[0.02] border border-black/5 rounded-xl">
                <span className="text-[9px] font-bold uppercase tracking-wider text-black/35">
                  {language === 'zh' ? '常用掩码参考' : 'Common Prefixes'}
                </span>
                <div className="grid grid-cols-5 gap-1.5 mt-1.5">
                  {commonPrefixes(isV6Local).map((item) => (
                    <button
                      key={item.prefix}
                      type="button"
                      onClick={() => setFormSubnet((f) => ({ ...f, prefix_len: item.prefix }))}
                      className="p-1 rounded border border-black/6 bg-white hover:bg-black/5 text-[9px] font-semibold text-[#00172D] text-left truncate transition-colors"
                      title={item.desc}
                    >
                      {item.desc.split(' — ')[0]}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 mt-5 border-t border-black/5 pt-4">
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
                  disabled={
                    !formSubnet.network ||
                    !netOkLocal ||
                    !prefixOk ||
                    !isValidVlanId(formSubnet.vlan_id) ||
                    !gwOkLocal ||
                    !gwVersionMatchLocal
                  }
                  className="px-4 py-2 rounded-xl bg-[#00bceb] hover:bg-[#00a5d0] disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-bold transition-all shadow-md shadow-[#00bceb]/10"
                >
                  {editingSubnet
                    ? language === 'zh'
                      ? '保存修改'
                      : 'Save Changes'
                    : language === 'zh'
                    ? '确认添加'
                    : 'Create'}
                </button>
              </div>
            </>
          );
        })()}
      </div>
    </div>
  );
};

export default SubnetModal;
