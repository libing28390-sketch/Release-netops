import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { X } from 'lucide-react';
import { Asset } from '../types';
import { AssetReadonlyDetailInner } from '../../../components/AssetReadonlyDetail';
import { useEscapeClose } from '../../../hooks/useEscapeClose';

interface AssetDetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  drawerAsset: Asset | null;
  language: string;
}

export const AssetDetailDrawer: React.FC<AssetDetailDrawerProps> = ({
  isOpen,
  onClose,
  drawerAsset,
  language,
}) => {
  useEscapeClose(isOpen && Boolean(drawerAsset), onClose);
  const zh = language === 'zh';

  return (
    <AnimatePresence>
      {isOpen && drawerAsset && (
        <motion.div
          role="complementary"
          aria-label={zh ? '资产详情' : 'Asset details'}
          className="fixed inset-y-0 right-0 z-40 w-[min(24rem,100vw)] overflow-y-auto border-l border-black/5 bg-white shadow-2xl"
          initial={{ x: 384 }}
          animate={{ x: 0 }}
          exit={{ x: 384 }}
          transition={{ type: 'tween', duration: 0.2 }}
        >
          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-black/80">{drawerAsset.hostname || drawerAsset.asset_tag || '—'}</h3>
              <button type="button" onClick={onClose} aria-label={zh ? '关闭资产详情' : 'Close asset details'} className="min-h-10 min-w-10 rounded-lg p-1 text-black/50 hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
                <X size={16} />
              </button>
            </div>
            <AssetReadonlyDetailInner asset={drawerAsset} zh={zh} />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
