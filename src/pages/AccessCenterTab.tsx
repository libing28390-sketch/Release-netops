import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Search, Server, ChevronRight, ChevronDown, Terminal, 
  X, Maximize2, Minimize2, Split, Monitor, Shield, User,
  LayoutGrid, List, Activity, Settings, Plus, Info, MonitorSpeaker
} from 'lucide-react';
import { useAccessStore } from '../store/useAccessStore';
import TerminalWindow from '../components/access/TerminalWindow';
import { useI18n } from '../i18n.tsx';

// --- Mock/Logic for Tree ---
interface TreeItem {
  id: string;
  label: string;
  type: 'folder' | 'device';
  icon?: any;
  children?: TreeItem[];
  ip?: string;
  platform?: string;
}

export default function AccessCenterTab({ devices: globalDevices = [], showToast }: { devices?: any[], showToast: (msg: string, type?: any) => void }) {
  const { t, language } = useI18n();
  const isZh = language === 'zh';
  const { 
    sessions, activeSessionId, addSession, removeSession, 
    setActiveSession, sidebarCollapsed, toggleSidebar 
  } = useAccessStore();

  const [search, setSearch] = useState('');
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [devices, setDevices] = useState<any[]>(globalDevices);

  // Sync internal devices if globalDevices changes
  useEffect(() => {
    if (globalDevices.length > 0) {
      setDevices(globalDevices);
    }
  }, [globalDevices]);

  const isLinux = (platform: string = '') => {
    const p = platform.toLowerCase();
    return ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'rocky', 'alma', 'oracle', 'server'].some(k => p.includes(k));
  };


  const filteredDevices = useMemo(() => {
    return devices.filter(d => 
      d.hostname?.toLowerCase().includes(search.toLowerCase()) ||
      d.ip_address?.includes(search)
    );
  }, [devices, search]);

  const selectedDevice = useMemo(() => 
    devices.find(d => d.id === selectedDeviceId), 
  [devices, selectedDeviceId]);

  return (
    <div className="flex h-[calc(100vh-64px)] bg-[#0d1117] text-[#c9d1d9] overflow-hidden font-sans">
      {/* ── Left Sidebar: Device Tree ── */}
      <aside className={`flex flex-col border-r border-white/5 transition-all ${sidebarCollapsed ? 'w-12' : 'w-64'}`}>
        <div className="p-3 border-b border-white/5 flex items-center justify-between">
          {!sidebarCollapsed && <span className="text-[11px] font-bold uppercase tracking-widest text-white/40">Explorer</span>}
          <button onClick={toggleSidebar} className="p-1 hover:bg-white/5 rounded text-white/40">
             {sidebarCollapsed ? <LayoutGrid size={14} /> : <Minimize2 size={14} />}
          </button>
        </div>
        
        {!sidebarCollapsed && (
          <div className="flex-1 overflow-y-auto p-2">
            {/* Tree Mockup */}
            <div className="space-y-1">
              <TreeFolder label="Servers" count={devices.filter(d => isLinux(d.platform)).length}>
                {devices.filter(d => isLinux(d.platform)).map(d => (
                  <TreeDevice key={d.id} label={d.hostname} onClick={() => setSelectedDeviceId(d.id)} isActive={selectedDeviceId === d.id} />
                ))}
              </TreeFolder>
              <TreeFolder label="Network Devices" count={devices.filter(d => !isLinux(d.platform)).length}>
                {devices.filter(d => !isLinux(d.platform)).map(d => (
                  <TreeDevice key={d.id} label={d.hostname} onClick={() => setSelectedDeviceId(d.id)} isActive={selectedDeviceId === d.id} />
                ))}
              </TreeFolder>
            </div>
          </div>
        )}
      </aside>

      {/* ── Main Content Area ── */}
      <main className="flex-1 flex flex-col min-w-0 bg-[#0d1117]">
        {/* Top Header: Tabs or Search */}
        <header className="h-10 border-b border-white/5 flex items-center px-2 gap-1 bg-[#161b22]">
          {sessions.length > 0 ? (
            <div className="flex-1 flex items-center gap-px overflow-x-auto no-scrollbar">
              {sessions.map(s => (
                <button
                  key={s.id}
                  onClick={() => setActiveSession(s.id)}
                  className={`h-full px-3 flex items-center gap-2 text-[11px] transition-all border-r border-white/5 relative group ${
                    activeSessionId === s.id ? 'bg-[#0d1117] text-cyan-400 font-bold' : 'text-white/40 hover:bg-white/5'
                  }`}
                >
                  <Terminal size={12} />
                  <span>{s.hostname}</span>
                  <X size={10} className="opacity-0 group-hover:opacity-100 hover:bg-white/10 rounded" onClick={(e) => { e.stopPropagation(); removeSession(s.id); }} />
                  {activeSessionId === s.id && <div className="absolute top-0 left-0 right-0 h-[2px] bg-cyan-500" />}
                </button>
              ))}
              <button className="px-3 text-white/20 hover:text-white/40 transition-colors" onClick={() => setActiveSession(null)}>
                <Plus size={14} />
              </button>
            </div>
          ) : (
            <div className="flex-1 flex items-center gap-2 px-2">
              <Search size={14} className="text-white/20" />
              <input 
                type="text" 
                placeholder="Search device by hostname or IP..." 
                className="bg-transparent border-none text-[11px] w-full focus:ring-0 placeholder:text-white/10"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
          )}
        </header>

        {/* Content Body: Gallery or Terminal */}
        <div className="flex-1 relative overflow-hidden p-4">
          <AnimatePresence mode="wait">
            {!activeSessionId ? (
              <motion.div 
                key="gallery"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
              >
                {filteredDevices.map(d => (
                  <DeviceCard 
                    key={d.id} 
                    device={d} 
                    onClick={() => setSelectedDeviceId(d.id)}
                    isActive={selectedDeviceId === d.id}
                  />
                ))}
              </motion.div>
            ) : (
              <motion.div 
                key="terminal"
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                className="w-full h-full bg-black rounded-lg overflow-hidden border border-white/5 flex flex-col"
              >
                 {(() => {
                    const session = sessions.find(s => s.id === activeSessionId);
                    if (!session) return null;
                    return (
                      <TerminalWindow 
                        deviceId={session.id} 
                        role={session.role} 
                        hostname={session.hostname} 
                      />
                    );
                 })()}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        
        {/* Bottom Bar: Active Sessions Metadata */}
        <footer className="h-7 bg-[#161b22] border-t border-white/5 flex items-center px-3 justify-between text-[10px] text-white/40">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span>Ready</span>
            </div>
            {sessions.length > 0 && (
              <div className="flex items-center gap-1 border-l border-white/10 pl-4">
                <Terminal size={10} />
                <span>{sessions.length} Active Sessions</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 uppercase font-bold tracking-tighter">
             <span>UTF-8</span>
             <span>SSH / XTERM-256</span>
          </div>
        </footer>
      </main>

      {/* ── Right Panel: Identity & Details ── */}
      <aside className={`w-80 border-l border-white/5 bg-[#161b22] p-4 flex flex-col transition-all overflow-y-auto ${!selectedDeviceId && 'hidden'}`}>
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-xs font-bold uppercase tracking-widest text-white/60">Device Details</h3>
          <button onClick={() => setSelectedDeviceId(null)} className="text-white/20 hover:text-white/60"><X size={14} /></button>
        </div>

        {selectedDevice && (
          <div className="space-y-6">
            <div className="p-4 rounded-xl bg-white/5 border border-white/5">
              <div className="flex items-center gap-3 mb-4">
                <div className="h-10 w-10 rounded-lg bg-cyan-500/10 flex items-center justify-center text-cyan-400">
                  <Server size={20} />
                </div>
                <div>
                  <div className="text-sm font-bold text-white">{selectedDevice.hostname}</div>
                  <div className="text-[10px] font-mono text-white/40">{selectedDevice.ip_address}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <InfoItem label="Vendor" value={selectedDevice.vendor || 'Unknown'} />
                <InfoItem label="Platform" value={selectedDevice.platform || 'SSH'} />
              </div>
            </div>

            <div className="space-y-3">
               <h4 className="text-[10px] font-bold uppercase tracking-widest text-white/40">Login Identities</h4>
               <IdentityButton 
                  icon={User} 
                  role="Normal" 
                  desc="Web Terminal Access" 
                  onClick={() => {
                    const url = `/terminal/${selectedDevice.id}?role=normal&hostname=${encodeURIComponent(selectedDevice.hostname)}`;
                    window.open(url, '_blank');
                  }}
               />
               
               {/* Native Client Support */}
               <div className="pt-2 border-t border-white/5 mt-2">
                 <button 
                   onClick={() => {
                     const path = localStorage.getItem('local_terminal_path');
                     if (!path) {
                       showToast(isZh ? '请前往 [个人中心] 配置本地终端路径' : 'Please configure terminal path in [Profile Settings]', 'warning');
                       return;
                     }
                     const dev = selectedDevice;
                     const user = dev.normal_username || 'user';
                     const url = `nexora://${dev.ip_address}?user=${encodeURIComponent(user)}&role=normal&client=xshell`;
                     window.location.href = url;
                     showToast(isZh ? '正在拉起 Xshell...' : 'Launching Xshell...', 'info');
                   }}
                   className="w-full p-3 rounded-xl bg-emerald-500/5 border border-emerald-500/10 hover:bg-emerald-500/10 transition-all flex items-center gap-3 group text-left"
                 >
                   <div className="h-8 w-8 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400 group-hover:scale-110 transition-transform">
                     <MonitorSpeaker size={16} />
                   </div>
                   <div>
                     <div className="text-[11px] font-bold text-white">{isZh ? '本地 Xshell' : 'Native Xshell'}</div>
                     <div className="text-[9px] text-white/30">{isZh ? '使用本地客户端连接' : 'Connect via local client'}</div>
                   </div>
                 </button>
               </div>
            </div>
            
            <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/10 text-[10px] text-blue-400/80 leading-relaxed">
               <Info size={12} className="mb-1" />
               {isZh ? '点击身份进入 Web 终端，或点击绿色按钮调起本地 Xshell。' : 'Click identity for Web Terminal, or the green button for local Xshell.'}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

// --- Sub-components ---

function TreeFolder({ label, count, children }: { label: string, count: number, children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button 
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 p-1.5 hover:bg-white/5 rounded text-white/60 text-[11px]"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span className="flex-1 text-left">{label}</span>
        <span className="text-[10px] bg-white/5 px-1 rounded">{count}</span>
      </button>
      {open && <div className="pl-4 mt-1 border-l border-white/5 ml-2.5 space-y-0.5">{children}</div>}
    </div>
  );
}

function TreeDevice({ label, onClick, isActive }: { label: string, onClick: () => void, isActive: boolean }) {
  return (
    <button 
      onClick={onClick}
      className={`w-full flex items-center gap-2 p-1.5 rounded text-[11px] transition-all ${
        isActive ? 'bg-cyan-500/10 text-cyan-400' : 'text-white/30 hover:bg-white/5'
      }`}
    >
      <Monitor size={10} />
      <span className="truncate">{label}</span>
    </button>
  );
}

function DeviceCard({ device, onClick, isActive }: { device: any, onClick: () => void, isActive: boolean }) {
  return (
    <motion.button
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className={`p-4 rounded-xl border text-left transition-all ${
        isActive 
          ? 'bg-white/5 border-cyan-500/50 shadow-[0_0_20px_rgba(6,182,212,0.1)]' 
          : 'bg-[#161b22] border-white/5 hover:border-white/10'
      }`}
    >
      <div className="flex items-center gap-3 mb-3">
        <div className={`h-8 w-8 rounded-lg flex items-center justify-center ${isActive ? 'bg-cyan-500 text-white' : 'bg-white/5 text-white/20'}`}>
          <Server size={16} />
        </div>
        <div className="min-w-0">
          <div className="text-xs font-bold truncate">{device.hostname}</div>
          <div className="text-[10px] font-mono opacity-40">{device.ip_address}</div>
        </div>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
         <span className="px-1.5 py-0.5 rounded bg-white/5 text-[9px] font-bold text-white/40 uppercase">{device.platform}</span>
         <span className="px-1.5 py-0.5 rounded bg-white/5 text-[9px] font-bold text-white/40 uppercase">{device.vendor}</span>
      </div>
    </motion.button>
  );
}

function InfoItem({ label, value }: { label: string, value: string }) {
  return (
    <div>
      <div className="text-[9px] font-bold uppercase tracking-wider text-white/20">{label}</div>
      <div className="text-[11px] text-white/80">{value}</div>
    </div>
  );
}

function IdentityButton({ icon: Icon, role, desc, color, onClick }: any) {
  return (
    <button 
      onClick={onClick}
      className="w-full p-3 rounded-xl bg-white/[0.02] border border-white/5 hover:bg-white/5 transition-all flex items-center gap-3 group text-left"
    >
      <div className={`h-8 w-8 rounded-lg bg-white/5 flex items-center justify-center ${color || 'text-cyan-400'} group-hover:scale-110 transition-transform`}>
        <Icon size={16} />
      </div>
      <div>
        <div className="text-[11px] font-bold text-white">{role} Identity</div>
        <div className="text-[9px] text-white/30">{desc}</div>
      </div>
    </button>
  );
}
