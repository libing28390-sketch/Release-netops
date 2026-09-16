import React from 'react';
import { IPAddress } from '../types';

export interface BlockMapItem {
  ip: string;
  ipNum: number;
  addr: IPAddress | null;
  type: 'network' | 'broadcast' | 'gateway' | 'active' | 'reserved' | 'deprecated' | 'free';
}

interface IPBlockMapProps {
  language: string;
  blockMapData: BlockMapItem[];
  onSelectAddress: (addr: IPAddress) => void;
}

const IPBlockMap: React.FC<IPBlockMapProps> = ({
  language,
  blockMapData,
  onSelectAddress,
}) => {
  return (
    <div className="p-3">
      <div className="flex items-center gap-3 mb-2 flex-wrap">
        <span className="text-[10px] text-black/35 font-semibold uppercase tracking-wide">
          {language === 'zh' ? '地址色块图' : 'Address Block Map'}
        </span>
        <div className="flex items-center gap-2 text-[9px] text-black/40">
          <span className="inline-flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-emerald-400" />
            {language === 'zh' ? '在用' : 'Active'}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-amber-400" />
            {language === 'zh' ? '预留' : 'Reserved'}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-red-400" />
            {language === 'zh' ? '停用' : 'Deprecated'}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-cyan-400" />
            {language === 'zh' ? '网关' : 'Gateway'}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-black/10" />
            {language === 'zh' ? '空闲' : 'Free'}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-sm bg-black/[0.03] border border-dashed border-black/15" />
            {language === 'zh' ? '网络/广播' : 'Net/Bcast'}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap gap-[3px]">
        {blockMapData.map((block, idx) => {
          const bgColor =
            block.type === 'active'
              ? 'bg-emerald-400 hover:bg-emerald-500'
              : block.type === 'reserved'
              ? 'bg-amber-400 hover:bg-amber-500'
              : block.type === 'deprecated'
              ? 'bg-red-400 hover:bg-red-500'
              : block.type === 'gateway'
              ? 'bg-cyan-400 hover:bg-cyan-500'
              : block.type === 'network' || block.type === 'broadcast'
              ? 'bg-black/[0.03] border border-dashed border-black/15'
              : 'bg-black/[0.06] hover:bg-black/10';
          const cursor =
            block.addr ? 'cursor-pointer' : block.type === 'free' ? 'cursor-pointer' : 'cursor-default';
          return (
            <div
              key={idx}
              className={`w-[14px] h-[14px] rounded-[2px] transition-all ${bgColor} ${cursor} group/block relative`}
              title={`${block.ip}${
                block.addr
                  ? ` — ${block.addr.hostname || block.addr.status}`
                  : block.type === 'gateway'
                  ? ' (GW)'
                  : block.type === 'network'
                  ? ' (Network)'
                  : block.type === 'broadcast'
                  ? ' (Broadcast)'
                  : ''
              }`}
              onClick={() => {
                if (block.addr) onSelectAddress(block.addr);
              }}
            />
          );
        })}
      </div>
      <p className="text-[10px] text-black/25 mt-2">
        {language === 'zh'
          ? `共 ${blockMapData.length} 个地址 · 悬停查看详情 · 点击已分配地址可编辑`
          : `${blockMapData.length} addresses · hover for details · click allocated to edit`}
      </p>
    </div>
  );
};

export default IPBlockMap;
