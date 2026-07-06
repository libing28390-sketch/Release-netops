import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Sparkles, X, ArrowUpCircle, Info } from 'lucide-react';
import { useSystem } from '../hooks/useSystem';

interface UpdateInfo {
  update_available: boolean;
  latest_version: string;
  changelog: string[];
  severity: string;
  release_date: string;
}

const VersionUpdateNotifier: React.FC<{ language: string }> = ({ language }) => {
  const { systemInfo } = useSystem();
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const zh = language === 'zh';

  useEffect(() => {
    const checkUpdate = async () => {
      try {
        const res = await fetch('/api/system/check-update');
        if (res.ok) {
          const data = await res.json();
          if (data.update_available) {
            setUpdateInfo(data);
          }
        }
      } catch (err) {
        console.error('Failed to check for updates:', err);
      }
    };

    // Check once on load
    checkUpdate();
    
    // Then every 10 minutes
    const timer = setInterval(checkUpdate, 600000);
    return () => clearInterval(timer);
  }, []);

  if (!updateInfo || !updateInfo.update_available || dismissed) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ y: 50, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 50, opacity: 0 }}
        className="fixed bottom-6 right-6 z-[100] max-w-sm w-full"
      >
        <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl border border-cyan-500/30 overflow-hidden">
          <div className="bg-gradient-to-r from-cyan-500 to-blue-600 px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-white">
              <Sparkles size={18} className="animate-pulse" />
              <span className="text-sm font-bold tracking-tight">
                {zh ? '发现新版本' : 'New Update Available'}
              </span>
            </div>
            <button 
              onClick={() => setDismissed(true)}
              className="text-white/70 hover:text-white transition-colors"
            >
              <X size={16} />
            </button>
          </div>
          
          <div className="p-4">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-xl bg-cyan-50 dark:bg-cyan-900/30 text-cyan-600 dark:text-cyan-400">
                <ArrowUpCircle size={24} />
              </div>
              <div>
                <p className="text-sm font-bold text-slate-800 dark:text-white/90">
                  {systemInfo?.system_name || 'Nexora'} v{updateInfo.latest_version}
                </p>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  {zh ? '发布日期' : 'Released'}: {updateInfo.release_date}
                </p>
              </div>
            </div>
            
            <div className="mt-4 space-y-2">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                <Info size={10} />
                {zh ? '更新内容' : 'What\'s New'}
              </div>
              <ul className="space-y-1.5">
                {updateInfo.changelog.slice(0, 3).map((item, i) => (
                  <li key={i} className="text-[11px] text-slate-600 dark:text-white/60 flex items-start gap-2">
                    <span className="mt-1 w-1 h-1 rounded-full bg-cyan-400 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            
            <div className="mt-5 flex gap-2">
              <button 
                onClick={() => window.location.reload()}
                className="flex-1 px-4 py-2 bg-cyan-500 hover:bg-cyan-600 text-white text-[11px] font-bold rounded-lg transition-all shadow-lg shadow-cyan-500/20"
              >
                {zh ? '立即更新' : 'Update Now'}
              </button>
              <button 
                onClick={() => setDismissed(true)}
                className="px-4 py-2 border border-slate-200 dark:border-white/10 text-slate-400 text-[11px] font-bold rounded-lg hover:bg-slate-50 transition-all"
              >
                {zh ? '稍后' : 'Later'}
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
};

export default VersionUpdateNotifier;
