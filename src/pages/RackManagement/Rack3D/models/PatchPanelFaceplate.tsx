import React from 'react';
import { DeviceHealthStatus } from '../../types';

interface PatchPanelFaceplateProps {
  width: number;
  height: number;
  depth: number;
  face: 'front' | 'rear';
  deviceName: string;
  vendor: string;
  model: string;
  heightU: number;
  healthStatus: DeviceHealthStatus;
  connectedPortNumbers?: number[];
}

/**
 * Physical fallback for a passive 1U copper patch panel.
 *
 * The approved CAT6 GLB is preferred by RackDeviceItem.  This lightweight
 * model is intentionally kept as a deterministic fallback so a patch panel
 * still reads as 24 real keystone sockets when a custom asset is unavailable
 * or while the asset is loading; it never invents link state or LEDs.
 */
export const PatchPanelFaceplate: React.FC<PatchPanelFaceplateProps> = ({
  width,
  height,
  depth,
  deviceName,
  vendor,
  model,
  connectedPortNumbers = [],
}) => {
  const portCount = 24;
  const columns = 12;
  const portWidth = Math.min(0.205, (width - 0.7) / (columns + 1));
  const portHeight = Math.min(0.075, Math.max(0.048, height * 0.18));
  const portGap = (width - 0.66 - portWidth * columns) / (columns - 1);
  const portStartX = -(width - 0.66) / 2;
  const connected = new Set(connectedPortNumbers);

  return (
    <group name={`patch-panel-${deviceName || model || '24p'}`} userData={{ vendor, model }}>
      <group position={[0, 0, depth / 2 + 0.012]}>
        <mesh position={[0, 0, 0]}>
          <boxGeometry args={[Math.max(0.2, width - 0.16), Math.max(0.08, height - 0.02), 0.06]} />
          <meshStandardMaterial color="#202b34" roughness={0.42} metalness={0.7} />
        </mesh>

        <mesh position={[0, 0, 0.035]}>
          <boxGeometry args={[Math.max(0.2, width - 0.27), Math.max(0.08, height - 0.11), 0.012]} />
          <meshStandardMaterial color="#0b1218" roughness={0.3} metalness={0.62} />
        </mesh>

        {/* Two rack ears with a subtle top rail, matching the other faceplates. */}
        <mesh position={[-(width / 2) + 0.05, 0, 0.04]}>
          <boxGeometry args={[0.1, height, 0.035]} />
          <meshStandardMaterial color="#475569" roughness={0.3} metalness={0.85} />
        </mesh>
        <mesh position={[(width / 2) - 0.05, 0, 0.04]}>
          <boxGeometry args={[0.1, height, 0.035]} />
          <meshStandardMaterial color="#475569" roughness={0.3} metalness={0.85} />
        </mesh>
        <mesh position={[0, height / 2 - 0.034, 0.051]}>
          <boxGeometry args={[Math.max(0.2, width - 0.34), 0.014, 0.012]} />
          <meshStandardMaterial color="#586875" roughness={0.36} metalness={0.72} />
        </mesh>

        {Array.from({ length: portCount }, (_, index) => {
          const row = index < columns ? 0 : 1;
          const column = index % columns;
          const x = portStartX + column * (portWidth + portGap);
          const y = row === 0 ? height * 0.16 : -height * 0.16;
          const isConnected = connected.has(index + 1);
          return (
            <group key={`patch-port-${index + 1}`} position={[x, y, 0.06]}>
              {/* Recess and metal keystone surround. */}
              <mesh position={[0, 0, -0.012]}>
                <boxGeometry args={[portWidth + 0.018, portHeight + 0.018, 0.012]} />
                <meshStandardMaterial color="#46535d" roughness={0.36} metalness={0.74} />
              </mesh>
              <mesh position={[0, 0, 0]}>
                <boxGeometry args={[portWidth, portHeight, 0.014]} />
                <meshStandardMaterial color="#02070b" roughness={0.2} metalness={0.4} />
              </mesh>
              {/* A tiny coloured insert is only shown for a verified patch link. */}
              {isConnected && (
                <mesh position={[0, portHeight * 0.32, 0.011]}>
                  <boxGeometry args={[portWidth * 0.38, 0.006, 0.004]} />
                  <meshStandardMaterial
                    color="#d1a021"
                    emissive="#8f6814"
                    emissiveIntensity={0.24}
                    roughness={0.24}
                    metalness={0.4}
                    toneMapped={false}
                  />
                </mesh>
              )}
              {/* Port-number tick; labels remain intentionally small at rack scale. */}
              <mesh position={[0, row === 0 ? portHeight * 0.7 : -portHeight * 0.7, 0.012]}>
                <boxGeometry args={[portWidth * 0.34, 0.003, 0.002]} />
                <meshStandardMaterial color="#91a0ab" roughness={0.5} metalness={0.25} />
              </mesh>
            </group>
          );
        })}

        {/* Passive panel identity strip; no fabricated health indicator. */}
        <mesh position={[0, -height * 0.39, 0.06]}>
          <boxGeometry args={[Math.min(1.65, width * 0.42), 0.018, 0.006]} />
          <meshStandardMaterial color="#70808b" roughness={0.42} metalness={0.55} />
        </mesh>
      </group>

      {/* The passive rear face remains visible during rear inspection without
          duplicating or pretending that the RJ45 keystones are bidirectional. */}
      <group position={[0, 0, -depth / 2 - 0.012]} rotation={[0, Math.PI, 0]}>
        <mesh>
          <boxGeometry args={[Math.max(0.2, width - 0.2), Math.max(0.08, height - 0.06), 0.04]} />
          <meshStandardMaterial color="#17232b" roughness={0.46} metalness={0.62} />
        </mesh>
      </group>
    </group>
  );
};
