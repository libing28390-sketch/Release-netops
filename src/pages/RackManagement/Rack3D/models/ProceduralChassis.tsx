import React, { useMemo } from 'react';
import * as THREE from 'three';
import { Html } from '@react-three/drei';
import { DeviceHealthStatus, RackDisplayMode } from '../../types';

interface ProceduralChassisProps {
  width: number;
  height: number;
  depth: number;
  healthStatus: DeviceHealthStatus;
  role: string;
  ratedPowerWatts: number;
  displayMode?: RackDisplayMode;
  selected?: boolean;
  isPulledOut?: boolean;
  isAnySelected?: boolean;
}

export const ProceduralChassis: React.FC<ProceduralChassisProps> = ({
  width,
  height,
  depth,
  healthStatus,
  role,
  ratedPowerWatts,
  displayMode = 'physical',
  selected = false,
  isPulledOut = false,
  isAnySelected = false
}) => {
  const isOffline = healthStatus === 'offline';

  const { bodyColor, roughness, metalness, emissive, emissiveIntensity, thermalColor, displayWatts } = useMemo(() => {
    // When another device is selected, slightly dim unselected devices
    const dimFactor = isAnySelected && !selected ? 0.75 : 1.0;

    // Default: High-grade gunmetal cold-rolled industrial steel chassis
    const baseColor = isOffline ? '#334155' : (isAnySelected && !selected ? '#18202c' : '#283344');

    if (displayMode === 'health') {
      switch (healthStatus) {
        case 'healthy':
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#059669', emissiveIntensity: 0.08 * dimFactor };
        case 'warning':
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#d97706', emissiveIntensity: 0.12 * dimFactor };
        case 'critical':
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#dc2626', emissiveIntensity: 0.18 * dimFactor };
        default:
          return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: '#000000', emissiveIntensity: 0 };
      }
    }

    if (displayMode === 'role') {
      const r = (role || '').toLowerCase();
      let accent = '#0284c7';
      if (r.includes('router')) accent = '#7c3aed';
      else if (r.includes('server')) accent = '#059669';
      else if (r.includes('firewall')) accent = '#c026d3';
      else if (r.includes('storage')) accent = '#ea580c';

      return { bodyColor: baseColor, roughness: 0.4, metalness: 0.65, emissive: accent, emissiveIntensity: 0.08 * dimFactor };
    }

    if (displayMode === 'power') {
      const watts = ratedPowerWatts || 250;
      let tColor = '#06b6d4'; // < 200W cool cyan
      let intensity = 0.25;

      if (watts >= 800) {
        tColor = '#ef4444'; // > 800W hot red
        intensity = 0.65;
      } else if (watts >= 500) {
        tColor = '#f59e0b'; // 500-800W warm amber
        intensity = 0.45;
      } else if (watts >= 250) {
        tColor = '#10b981'; // 250-500W moderate green
        intensity = 0.35;
      }

      return {
        bodyColor: baseColor,
        roughness: 0.35,
        metalness: 0.6,
        emissive: tColor,
        emissiveIntensity: intensity * dimFactor,
        thermalColor: tColor,
        displayWatts: watts
      };
    }

    // Default 'physical' mode: Authentic dark gunmetal steel
    return {
      bodyColor: baseColor,
      roughness: isOffline ? 0.75 : 0.4,
      metalness: isOffline ? 0.3 : 0.7,
      emissive: '#000000',
      emissiveIntensity: 0,
    };
  }, [healthStatus, isOffline, selected, isAnySelected, displayMode, role, ratedPowerWatts]);

  const edgeGeo = useMemo(() => {
    const box = new THREE.BoxGeometry(width + 0.02, height + 0.02, depth + 0.02);
    const edges = new THREE.EdgesGeometry(box);
    box.dispose();
    return edges;
  }, [width, height, depth]);

  return (
    <group>
      {/* Main Metal Chassis Box */}
      <mesh castShadow receiveShadow>
        <boxGeometry args={[width, height, depth]} />
        <meshStandardMaterial
          color={bodyColor}
          roughness={roughness}
          metalness={metalness}
          emissive={emissive}
          emissiveIntensity={emissiveIntensity}
        />
      </mesh>

      {/* Selected Edge Highlight Box */}
      {selected && (
        <lineSegments geometry={edgeGeo}>
          <lineBasicMaterial color="#38bdf8" linewidth={2} />
        </lineSegments>
      )}

      {/* Thermal / Power Mode Floating HUD Badge */}
      {displayMode === 'power' && displayWatts && (
        <Html position={[0, height / 2 + 0.06, depth / 2 + 0.1]} center distanceFactor={20}>
          <div
            className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold text-white shadow-xl backdrop-blur-md border pointer-events-none whitespace-nowrap flex items-center gap-1"
            style={{ backgroundColor: `${thermalColor}33`, borderColor: thermalColor }}
          >
            <span>⚡</span>
            <span>{displayWatts} W</span>
          </div>
        </Html>
      )}

      {/* Slide Rails & Top Vent Detail (Shown when device is pulled out for maintenance) */}
      {isPulledOut && (
        <group>
          {/* Left Stainless Steel Slide Rail */}
          <mesh position={[-(width / 2) - 0.04, 0, -1.6]}>
            <boxGeometry args={[0.03, height * 0.7, 3.6]} />
            <meshStandardMaterial color="#94a3b8" roughness={0.2} metalness={0.9} />
          </mesh>
          {/* Right Stainless Steel Slide Rail */}
          <mesh position={[(width / 2) + 0.04, 0, -1.6]}>
            <boxGeometry args={[0.03, height * 0.7, 3.6]} />
            <meshStandardMaterial color="#94a3b8" roughness={0.2} metalness={0.9} />
          </mesh>
          {/* Top Chassis Service Label */}
          <mesh position={[0, height / 2 + 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={[width * 0.75, depth * 0.6]} />
            <meshStandardMaterial color="#1e293b" roughness={0.6} metalness={0.3} />
          </mesh>
        </group>
      )}
    </group>
  );
};
