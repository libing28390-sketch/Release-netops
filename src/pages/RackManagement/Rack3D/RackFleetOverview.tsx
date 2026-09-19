import React, { useEffect, useMemo, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { AlertTriangle, Box, Database, ExternalLink, MousePointer2 } from 'lucide-react';
import { RackSummary } from '../types';
import { buildRackFleetLayout, RackFleetPlacement } from './fleetLayout';
import { isWebGLAvailable } from './utils/webgl';

interface RackFleetOverviewProps {
  racks: RackSummary[];
  selectedRackId: string;
  onSelectRack: (rackId: string) => void;
  onOpenRack: (rackId: string) => void;
  zh: boolean;
}

const healthColor = (rack: RackSummary) => {
  if (rack.data_quality_status === 'invalid') return '#ef4444';
  if (rack.health_status === 'offline') return '#f97316';
  if (rack.health_status === 'healthy') return '#10b981';
  if (rack.health_status === 'partial') return '#eab308';
  if (rack.health_status === 'empty') return '#64748b';
  return '#94a3b8';
};

const RackInstances: React.FC<{
  placements: RackFleetPlacement[];
  selectedRackId: string;
  onSelectRack: (rackId: string) => void;
  onOpenRack: (rackId: string) => void;
}> = ({ placements, selectedRackId, onSelectRack, onOpenRack }) => {
  const meshRef = useRef<THREE.InstancedMesh>(null);

  useEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const object = new THREE.Object3D();
    const color = new THREE.Color();
    placements.forEach((placement, index) => {
      object.position.set(...placement.position);
      const selected = placement.rack.id === selectedRackId;
      object.scale.set(selected ? 1.12 : 1, selected ? 1.08 : 1, selected ? 1.12 : 1);
      object.updateMatrix();
      mesh.setMatrixAt(index, object.matrix);
      mesh.setColorAt(index, color.set(selected ? '#22d3ee' : healthColor(placement.rack)));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [placements, selectedRackId]);

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, placements.length]}
      onClick={event => {
        event.stopPropagation();
        if (event.instanceId == null) return;
        const placement = placements[event.instanceId];
        if (placement) onSelectRack(placement.rack.id);
      }}
      onDoubleClick={event => {
        event.stopPropagation();
        if (event.instanceId == null) return;
        const placement = placements[event.instanceId];
        if (placement) onOpenRack(placement.rack.id);
      }}
    >
      <boxGeometry args={[0.9, 1.8, 0.9]} />
      <meshStandardMaterial vertexColors roughness={0.5} metalness={0.2} />
    </instancedMesh>
  );
};

export const RackFleetOverview: React.FC<RackFleetOverviewProps> = ({
  racks,
  selectedRackId,
  onSelectRack,
  onOpenRack,
  zh,
}) => {
  const placements = useMemo(() => buildRackFleetLayout(racks), [racks]);
  const selected = racks.find(rack => rack.id === selectedRackId) || null;
  const webglSupported = useMemo(() => isWebGLAvailable(), []);
  const extent = useMemo(() => {
    if (!placements.length) return 10;
    const zValues = placements.map(item => item.position[2]);
    return Math.max(10, Math.max(...zValues) - Math.min(...zValues) + 6);
  }, [placements]);

  if (!racks.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm" style={{ color: 'var(--muted-text)' }}>
        {zh ? '当前筛选没有可展示的机柜摘要' : 'No rack summaries match the current filters.'}
      </div>
    );
  }

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-[#090d16] text-slate-200">
      {webglSupported ? (
        <Canvas
          camera={{ position: [0, Math.min(60, Math.max(14, extent * 0.75)), Math.min(80, Math.max(20, extent))], fov: 45 }}
          dpr={[1, 1.5]}
          gl={{ antialias: true, alpha: false, preserveDrawingBuffer: false }}
        >
          <color attach="background" args={['#090d16']} />
          <ambientLight intensity={1.15} />
          <directionalLight position={[8, 16, 10]} intensity={1.8} />
          <gridHelper args={[Math.max(30, extent * 2), Math.max(20, Math.ceil(extent)), '#1e3a5f', '#162033']} position={[0, 0, extent / 2 - 3]} />
          <RackInstances
            placements={placements}
            selectedRackId={selectedRackId}
            onSelectRack={onSelectRack}
            onOpenRack={onOpenRack}
          />
          <OrbitControls makeDefault enableDamping dampingFactor={0.08} minDistance={5} maxDistance={140} />
        </Canvas>
      ) : (
        <div className="grid h-full content-start grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-2 overflow-auto p-4">
          {racks.map(rack => (
            <button
              key={rack.id}
              type="button"
              onClick={() => onSelectRack(rack.id)}
              onDoubleClick={() => onOpenRack(rack.id)}
              className={`rounded-lg border p-3 text-left ${rack.id === selectedRackId ? 'border-cyan-400 bg-cyan-500/10' : 'border-slate-700 bg-slate-900'}`}
            >
              <div className="font-semibold">{rack.name}</div>
              <div className="mt-1 text-[10px] text-slate-400">{rack.site_label} / {rack.floor || '—'} / {rack.room || '—'} / {rack.row || '—'}</div>
            </button>
          ))}
        </div>
      )}

      <div className="absolute left-3 top-3 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2 rounded-xl border border-slate-700/70 bg-slate-950/90 px-3 py-2 text-[10px] shadow-xl backdrop-blur-xl">
        <span className="flex items-center gap-1 font-bold text-cyan-300"><Box size={12} /> {zh ? '多机柜逻辑总览' : 'Multi-rack logical overview'}</span>
        <span className="flex items-center gap-1 text-amber-300"><AlertTriangle size={11} /> {zh ? '位置为 CMDB 字段推断，非现场坐标' : 'Positions are inferred from CMDB fields, not surveyed coordinates'}</span>
        <span className="flex items-center gap-1 text-slate-400"><Database size={11} /> {racks.length} {zh ? '个摘要实例' : 'summary instances'}</span>
      </div>

      <div className="absolute bottom-3 left-3 flex items-center gap-3 rounded-xl border border-slate-700/70 bg-slate-950/90 px-3 py-2 text-[10px] shadow-xl backdrop-blur-xl">
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-emerald-500" />{zh ? '健康' : 'Healthy'}</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-orange-500" />{zh ? '离线' : 'Offline'}</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-yellow-500" />{zh ? '部分数据' : 'Partial'}</span>
        <span className="flex items-center gap-1"><span className="h-2 w-2 rounded bg-slate-500" />{zh ? '未知/空' : 'Unknown/empty'}</span>
      </div>

      {selected && (
        <div className="absolute bottom-3 right-3 w-72 rounded-xl border border-cyan-500/30 bg-slate-950/95 p-3 text-xs shadow-2xl backdrop-blur-xl">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-bold text-white">{selected.name}</div>
              <div className="mt-0.5 truncate text-[10px] text-slate-400">{selected.site_label} / {selected.floor || '—'} / {selected.room || '—'} / {selected.row || '—'}</div>
            </div>
            <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-300">inferred</span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[10px]">
            <div className="rounded bg-slate-900 p-1.5"><strong className="block text-white">{selected.device_count}</strong>{zh ? '设备' : 'Devices'}</div>
            <div className="rounded bg-slate-900 p-1.5"><strong className="block text-white">{selected.used_u}/{selected.total_u}U</strong>{zh ? '占用' : 'Used'}</div>
            <div className="rounded bg-slate-900 p-1.5"><strong className="block text-white">{selected.power_used_watts}W</strong>{zh ? '功率' : 'Power'}</div>
          </div>
          <button
            type="button"
            onClick={() => onOpenRack(selected.id)}
            className="mt-2 flex w-full items-center justify-center gap-1 rounded-lg bg-cyan-600 px-3 py-2 text-[11px] font-semibold text-white hover:bg-cyan-700"
          >
            <ExternalLink size={12} /> {zh ? '打开单机柜工作台' : 'Open single-rack workbench'}
          </button>
          <div className="mt-1.5 flex items-center justify-center gap-1 text-[9px] text-slate-500"><MousePointer2 size={9} />{zh ? '单击定位，双击下钻' : 'Click to select, double-click to drill down'}</div>
        </div>
      )}
    </div>
  );
};
