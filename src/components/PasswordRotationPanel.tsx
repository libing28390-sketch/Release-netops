import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'motion/react';
import { RefreshCw, Shield, AlertTriangle, CheckCircle2, Clock, Loader2, RotateCcw } from 'lucide-react';

interface RotationDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  password_last_rotated: string;
  password_expires_at: string;
  days_remaining: number | null;
  expired: boolean;
}

interface PasswordRotationPanelProps {
  language: string;
}

const API_BASE = import.meta.env.VITE_API_BASE || '';

export default function PasswordRotationPanel({ language }: PasswordRotationPanelProps) {
  const zh = language === 'zh';
  const [devices, setDevices] = useState<RotationDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [rotating, setRotating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/rotation/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (data.success) {
        setDevices(data.data || []);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const handleRotate = async (deviceId: string) => {
    setRotating(deviceId);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/${deviceId}/rotate-password`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (!data.success) throw new Error(data.data?.message || 'Rotation failed');
      await fetchStatus();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRotating(null);
    }
  };

  const statusBadge = (dev: RotationDevice) => {
    if (!dev.password_expires_at) {
      return <span className="px-2 py-0.5 rounded-full text-xs bg-gray-700 text-gray-400">{zh ? '未配置' : 'Not set'}</span>;
    }
    if (dev.expired) {
      return <span className="px-2 py-0.5 rounded-full text-xs bg-red-900/40 text-red-300">{zh ? '已过期' : 'Expired'}</span>;
    }
    if (dev.days_remaining !== null && dev.days_remaining <= 14) {
      return <span className="px-2 py-0.5 rounded-full text-xs bg-yellow-900/40 text-yellow-300">{zh ? '即将过期' : 'Expiring'}</span>;
    }
    return <span className="px-2 py-0.5 rounded-full text-xs bg-cyan-900/40 text-cyan-300">{zh ? '正常' : 'OK'}</span>;
  };

  return (
    <div className="bg-gray-800/60 rounded-xl border border-gray-700/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700/40">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-cyan-400" />
          <h3 className="text-sm font-semibold text-cyan-100">{zh ? '密码轮换管理' : 'Password Rotation'}</h3>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loading}
          className="p-1.5 rounded hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="mx-5 mt-3 flex items-center gap-2 bg-red-900/30 border border-red-700/50 rounded px-3 py-2">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <span className="text-xs text-red-300">{error}</span>
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-gray-700/30">
              <th className="px-5 py-2">{zh ? '设备' : 'Device'}</th>
              <th className="px-3 py-2">IP</th>
              <th className="px-3 py-2">{zh ? '上次轮换' : 'Last Rotated'}</th>
              <th className="px-3 py-2">{zh ? '过期时间' : 'Expires'}</th>
              <th className="px-3 py-2">{zh ? '剩余天数' : 'Days Left'}</th>
              <th className="px-3 py-2">{zh ? '状态' : 'Status'}</th>
              <th className="px-3 py-2">{zh ? '操作' : 'Action'}</th>
            </tr>
          </thead>
          <tbody>
            {loading && !devices.length ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-500"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></td></tr>
            ) : devices.length === 0 ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-500">{zh ? '暂无设备' : 'No devices'}</td></tr>
            ) : (
              devices.map(dev => (
                <motion.tr key={dev.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="border-b border-gray-700/20 hover:bg-gray-700/20">
                  <td className="px-5 py-2.5 text-gray-200">{dev.hostname || '-'}</td>
                  <td className="px-3 py-2.5 text-gray-400 font-mono text-xs">{dev.ip_address}</td>
                  <td className="px-3 py-2.5 text-gray-400 text-xs">
                    {dev.password_last_rotated ? new Date(dev.password_last_rotated).toLocaleDateString() : '-'}
                  </td>
                  <td className="px-3 py-2.5 text-gray-400 text-xs">
                    {dev.password_expires_at ? new Date(dev.password_expires_at).toLocaleDateString() : '-'}
                  </td>
                  <td className="px-3 py-2.5">
                    {dev.days_remaining !== null ? (
                      <span className={dev.days_remaining < 0 ? 'text-red-400' : dev.days_remaining <= 14 ? 'text-yellow-400' : 'text-gray-300'}>
                        {dev.days_remaining}
                      </span>
                    ) : '-'}
                  </td>
                  <td className="px-3 py-2.5">{statusBadge(dev)}</td>
                  <td className="px-3 py-2.5">
                    <button
                      onClick={() => handleRotate(dev.id)}
                      disabled={rotating === dev.id}
                      className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-cyan-700/30 text-cyan-300 hover:bg-cyan-600/40 transition-colors disabled:opacity-50"
                    >
                      {rotating === dev.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                      {zh ? '轮换' : 'Rotate'}
                    </button>
                  </td>
                </motion.tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
