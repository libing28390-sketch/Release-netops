import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Sparkles, ArrowRight, X, Info, Zap, ShieldCheck } from 'lucide-react';
import { useI18n } from '../i18n.tsx';

interface UpdateInfo {
  current_version: string;
  latest_version: string;
  update_available: boolean;
  changelog: string[];
  severity: 'normal' | 'important' | 'critical';
  release_date: string;
}

const VersionBanner: React.FC = () => {
  const { language } = useI18n();
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [isVisible, setIsVisible] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    const checkUpdate = async () => {
      try {
        const token = localStorage.getItem('netops_token');
        const resp = await fetch('/api/system/check-update', {
          headers: token ? { Authorization: `Bearer ${token}` } : {}
        });
        if (resp.ok) {
          const data = await resp.json();
          setUpdate(data);
          if (data.update_available) {
            // Delay visibility for better UX
            setTimeout(() => setIsVisible(true), 2000);
          }
        }
      } catch (e) {
        console.error('Failed to check for updates:', e);
      }
    };

    checkUpdate();
  }, []);

  const handleUpgrade = async () => {
    if (!window.confirm('确定要开始系统升级吗？升级过程中系统将暂时不可用。')) return;
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/system/upgrade', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      const data = await resp.json();
      if (data.success) {
        alert(data.message);
        setIsVisible(false);
      } else {
        alert(language === 'zh' ? `升级失败: ${data.message}` : `Upgrade failed: ${data.message}`);
      }
    } catch (e) {
      alert(language === 'zh' ? '网络错误，请稍后重试' : 'Network error, please try again later');
    }
  };

  if (!update || !update.update_available || !isVisible) return null;

  const severityColors = {
    normal: 'from-blue-600 to-indigo-600',
    important: 'from-indigo-600 to-violet-600',
    critical: 'from-red-600 to-orange-600'
  };

  const bgGradient = severityColors[update.severity] || severityColors.normal;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ height: 0, opacity: 0 }}
        animate={{ height: isExpanded ? 'auto' : '40px', opacity: 1 }}
        exit={{ height: 0, opacity: 0 }}
        className={`relative w-full bg-gradient-to-r ${bgGradient} text-white overflow-hidden shadow-lg z-[100]`}
      >
        <div className="max-w-[1600px] mx-auto px-4 h-10 flex items-center justify-between">
          <div className="flex items-center gap-3 overflow-hidden">
            <motion.div
              animate={{ rotate: [0, 15, -15, 0] }}
              transition={{ repeat: Infinity, duration: 4 }}
            >
              <Sparkles size={16} className="text-amber-300" />
            </motion.div>
            <p className="text-sm font-medium whitespace-nowrap">
              <span className="opacity-90">新版本发布:</span>
              <span className="ml-2 font-bold bg-white/20 px-2 py-0.5 rounded text-xs">v{update.latest_version}</span>
              <span className="ml-3 hidden sm:inline opacity-90">体验更强大的自动化能力与更优的系统稳定性</span>
            </p>
            {!isExpanded && (
              <button 
                onClick={() => setIsExpanded(true)}
                className="text-xs bg-white/10 hover:bg-white/20 px-2 py-0.5 rounded transition-colors ml-2 hidden md:block"
              >
                查看更新日志
              </button>
            )}
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={handleUpgrade}
              className="flex items-center gap-1.5 px-3 py-1 bg-white text-indigo-600 rounded-full text-xs font-bold hover:bg-opacity-90 transition-all shadow-sm hover:scale-105 active:scale-95"
            >
              立即升级 <ArrowRight size={14} />
            </button>
            <button 
              onClick={() => setIsVisible(false)}
              className="p-1 hover:bg-white/10 rounded-full transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {isExpanded && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="max-w-[1600px] mx-auto px-4 pb-6 pt-2 border-t border-white/10"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-white/70 mb-3 flex items-center gap-2">
                  <Zap size={14} /> 主要更新内容
                </h4>
                <ul className="space-y-2">
                  {update.changelog.map((item, i) => (
                    <li key={i} className="text-sm flex items-start gap-2">
                      <div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
                      <span className="opacity-90">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="bg-white/5 rounded-xl p-4 border border-white/10">
                <h4 className="text-xs font-bold uppercase tracking-wider text-white/70 mb-3 flex items-center gap-2">
                  <ShieldCheck size={14} /> 系统摘要
                </h4>
                <div className="space-y-3">
                  <div className="flex justify-between text-sm">
                    <span className="opacity-60">当前版本</span>
                    <span className="font-mono">v{update.current_version}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="opacity-60">发布日期</span>
                    <span>{update.release_date}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="opacity-60">更新性质</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      update.severity === 'critical' ? 'bg-red-500' : 'bg-indigo-500'
                    }`}>
                      {update.severity === 'critical' ? '紧急修复' : '功能迭代'}
                    </span>
                  </div>
                </div>
                <button 
                  onClick={() => setIsExpanded(false)}
                  className="w-full mt-4 py-2 text-xs font-bold text-center border border-white/20 rounded-lg hover:bg-white/5 transition-colors"
                >
                  收起面板
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </motion.div>
    </AnimatePresence>
  );
};

export default VersionBanner;
