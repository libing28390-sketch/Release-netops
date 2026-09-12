import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { X } from 'lucide-react';
import { Asset } from '../types';
import { AssetReadonlyDetailInner } from '../../../components/AssetReadonlyDetail';

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
  const zh = language === 'zh';

  return (
    <AnimatePresence>
      {isOpen && drawerAsset && (
        <motion.div
          className="fixed inset-y-0 right-0 z-40 w-96 bg-white border-l border-black/5 shadow-2xl overflow-y-auto"
          initial={{ x: 384 }}
          animate={{ x: 0 }}
          exit={{ x: 384 }}
          transition={{ type: 'tween', duration: 0.2 }}
        >
          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-black/80">{drawerAsset.hostname || drawerAsset.asset_tag || '—'}</h3>
              <button onClick={onClose} title="Close" className="p-1 text-black/15 hover:text-black/35">
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
