import React, { useState, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { Html } from '@react-three/drei';
import {
  U_HEIGHT_3D,
  RACK_OUTER_WIDTH_DEFAULT,
  RACK_INNER_WIDTH,
  RACK_TOTAL_DEPTH_DEFAULT
} from '../adapters/rackViewModel';
import {
  getHoneycombDoorTexture,
  getRackRailTexture,
  getNameplateTexture
} from './utils/textures';

export interface RackFrameProps {
  name: string;
  totalU: number;
  widthMm?: number;
  depthMm?: number;
  showDoor?: boolean;
  isDoorOpen?: boolean;
  showULabels?: boolean;
  occupiedUs?: Set<number>;
  onHoverEmptyU?: (u: number | null) => void;
  zh?: boolean;
  /** Render the structural fallback mesh, or only the interactive overlays. */
  renderStructure?: boolean;
}

interface RackCasterAssemblyProps {
  x: number;
  y: number;
  z: number;
  front: boolean;
}

/**
 * Mobile rack base detail.  The production cabinet GLB contains the shell,
 * but its caster geometry is deliberately kept lightweight here so the same
 * wheels remain visible when the procedural fallback or the GLB is used.
 */
const RackCasterAssembly: React.FC<RackCasterAssemblyProps> = ({ x, y, z, front }) => (
  <group position={[x, y, z]} renderOrder={24}>
    <mesh position={[0, 0.11, 0]} castShadow renderOrder={24}>
      <boxGeometry args={[0.11, 0.18, 0.11]} />
      <meshStandardMaterial color="#4b5563" roughness={0.32} metalness={0.82} />
    </mesh>
    {/* Wheel plane faces the viewer (+Z); the dark hub keeps the silver ring
        readable without looking like a glowing UI marker. */}
    <mesh rotation={[0, 0, 0]} castShadow renderOrder={40}>
      <torusGeometry args={[0.105, 0.032, 10, 18]} />
      <meshStandardMaterial
        color="#d6dde2"
        emissive="#64748b"
        emissiveIntensity={0.16}
        roughness={0.24}
        metalness={0.78}
        depthTest={false}
        depthWrite={false}
      />
    </mesh>
    <mesh rotation={[Math.PI / 2, 0, 0]} renderOrder={41}>
      <cylinderGeometry args={[0.035, 0.035, 0.07, 12]} />
      <meshStandardMaterial color="#1b242c" roughness={0.3} metalness={0.75} depthTest={false} depthWrite={false} />
    </mesh>
    {front && (
      <mesh position={[0.07, 0.15, 0.025]} rotation={[0, 0, -Math.PI / 7]} renderOrder={27}>
        <boxGeometry args={[0.018, 0.08, 0.018]} />
        <meshStandardMaterial color="#d4d9dd" roughness={0.25} metalness={0.8} />
      </mesh>
    )}
  </group>
);

export const RackFrame: React.FC<RackFrameProps> = ({
  name,
  totalU,
  widthMm = 600,
  depthMm = 1000,
  showDoor = true,
  isDoorOpen = true,
  showULabels = true,
  occupiedUs = new Set(),
  onHoverEmptyU,
  zh = true,
  renderStructure = true
}) => {
  const [hoveredEmptyU, setHoveredEmptyU] = useState<number | null>(null);
  const frontDoorRef = useRef<THREE.Group>(null);
  const rearLeftDoorRef = useRef<THREE.Group>(null);
  const rearRightDoorRef = useRef<THREE.Group>(null);

  // Smooth spring-damped hinge animation for front & rear split perforated doors
  useFrame((_, delta) => {
    const dt = Math.min(delta, 0.05);
    if (frontDoorRef.current) {
      const targetAngle = isDoorOpen ? -Math.PI * 0.58 : 0;
      frontDoorRef.current.rotation.y = THREE.MathUtils.damp(frontDoorRef.current.rotation.y, targetAngle, 7, dt);
    }
    if (rearLeftDoorRef.current) {
      const targetL = isDoorOpen ? Math.PI * 0.52 : 0;
      rearLeftDoorRef.current.rotation.y = THREE.MathUtils.damp(rearLeftDoorRef.current.rotation.y, targetL, 7, dt);
    }
    if (rearRightDoorRef.current) {
      const targetR = isDoorOpen ? -Math.PI * 0.52 : 0;
      rearRightDoorRef.current.rotation.y = THREE.MathUtils.damp(rearRightDoorRef.current.rotation.y, targetR, 7, dt);
    }
  });
  const rackHeight = totalU * U_HEIGHT_3D;
  const rackWidth = (widthMm / 600) * RACK_OUTER_WIDTH_DEFAULT;
  const rackDepth = (depthMm / 1000) * RACK_TOTAL_DEPTH_DEFAULT;

  const postThickness = 0.28;
  const postOffsetW = (rackWidth - postThickness) / 2;
  const postOffsetD = (rackDepth - postThickness) / 2;

  const doorTexture = useMemo(() => getHoneycombDoorTexture(), []);
  const railTexture = useMemo(() => getRackRailTexture(totalU), [totalU]);
  const nameplateTexture = useMemo(() => getNameplateTexture(name), [name]);

  // 4 Vertical Corner Steel Posts
  const postPositions: [number, number, number][] = useMemo(() => [
    [-postOffsetW, rackHeight / 2, postOffsetD],
    [postOffsetW, rackHeight / 2, postOffsetD],
    [-postOffsetW, rackHeight / 2, -postOffsetD],
    [postOffsetW, rackHeight / 2, -postOffsetD],
  ], [postOffsetW, postOffsetD, rackHeight]);

  const railWidth = 0.22;
  const railXOffset = (rackWidth * (RACK_INNER_WIDTH / RACK_OUTER_WIDTH_DEFAULT)) / 2;
  const railZOffset = rackDepth * 0.42;

  // Geometry for edge highlights
  const postEdgeGeo = useMemo(() => {
    const box = new THREE.BoxGeometry(postThickness, rackHeight, postThickness);
    const edges = new THREE.EdgesGeometry(box);
    box.dispose();
    return edges;
  }, [postThickness, rackHeight]);

  const topCapEdgeGeo = useMemo(() => {
    const box = new THREE.BoxGeometry(rackWidth + 0.1, 0.3, rackDepth + 0.1);
    const edges = new THREE.EdgesGeometry(box);
    box.dispose();
    return edges;
  }, [rackWidth, rackDepth]);

  const plinthEdgeGeo = useMemo(() => {
    const box = new THREE.BoxGeometry(rackWidth + 0.1, 0.4, rackDepth + 0.1);
    const edges = new THREE.EdgesGeometry(box);
    box.dispose();
    return edges;
  }, [rackWidth, rackDepth]);

  return (
    <group>
      {renderStructure && (
        <>
      {/* 4 Vertical Corner Structural Posts */}
      {postPositions.map((pos, i) => (
        <group key={`post-${i}`} position={pos}>
          <mesh castShadow receiveShadow>
            <boxGeometry args={[postThickness, rackHeight, postThickness]} />
            <meshStandardMaterial color="#2d3748" roughness={0.55} metalness={0.25} />
          </mesh>
          <lineSegments geometry={postEdgeGeo}>
            <lineBasicMaterial color="#4a5568" transparent opacity={0.6} />
          </lineSegments>
        </group>
      ))}

      {/* Top Cap */}
      <group position={[0, rackHeight + 0.15, 0]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[rackWidth + 0.1, 0.3, rackDepth + 0.1]} />
          <meshStandardMaterial color="#2d3748" roughness={0.5} metalness={0.25} />
        </mesh>
        <lineSegments geometry={topCapEdgeGeo}>
          <lineBasicMaterial color="#0ea5e9" transparent opacity={0.5} />
        </lineSegments>
      </group>

      {/* Top Nameplate with High-Res Texture */}
      <mesh position={[0, rackHeight + 0.15, (rackDepth / 2) + 0.06]}>
        <planeGeometry args={[rackWidth * 0.75, 0.24]} />
        <meshBasicMaterial map={nameplateTexture} />
      </mesh>

      {/* Bottom Plinth Base */}
      <group position={[0, -0.2, 0]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[rackWidth + 0.1, 0.4, rackDepth + 0.1]} />
          <meshStandardMaterial color="#2d3748" roughness={0.55} metalness={0.25} />
        </mesh>
        <lineSegments geometry={plinthEdgeGeo}>
          <lineBasicMaterial color="#4a5568" transparent opacity={0.6} />
        </lineSegments>
      </group>

      {/* 4 Leveling Feet */}
      {postPositions.map((pos, i) => (
        <mesh key={`foot-${i}`} position={[pos[0], -0.45, pos[2]]}>
          <cylinderGeometry args={[0.12, 0.16, 0.1, 16]} />
          <meshStandardMaterial color="#64748b" roughness={0.4} metalness={0.5} />
        </mesh>
      ))}

      {/* Front Left & Right Vertical Mounting Rails with U Markings */}
      {showULabels && (
        <>
          <mesh position={[-railXOffset, rackHeight / 2, railZOffset]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshStandardMaterial map={railTexture} roughness={0.5} metalness={0.25} />
          </mesh>
          <mesh position={[railXOffset, rackHeight / 2, railZOffset]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshStandardMaterial map={railTexture} roughness={0.5} metalness={0.25} />
          </mesh>
        </>
      )}

      {/* Rear Vertical Mounting Rails */}
      <mesh position={[-railXOffset, rackHeight / 2, -railZOffset]} rotation={[0, Math.PI, 0]}>
        <planeGeometry args={[railWidth, rackHeight]} />
        <meshStandardMaterial map={railTexture} roughness={0.5} metalness={0.25} />
      </mesh>
      <mesh position={[railXOffset, rackHeight / 2, -railZOffset]} rotation={[0, Math.PI, 0]}>
        <planeGeometry args={[railWidth, rackHeight]} />
        <meshStandardMaterial map={railTexture} roughness={0.5} metalness={0.25} />
      </mesh>

      {/* Interior Ceiling LED Light Bar */}
      <group position={[0, rackHeight - 0.05, 0]}>
        <mesh>
          <boxGeometry args={[rackWidth * 0.7, 0.03, 0.08]} />
          <meshStandardMaterial color="#38bdf8" emissive="#38bdf8" emissiveIntensity={2.5} roughness={0.2} />
        </mesh>
        <pointLight position={[0, -0.15, 0]} intensity={1.5} color="#bae6fd" distance={18} />
      </group>
        </>
      )}

      {/* U-number ruler overlays aligned flush with the EIA-310 rails with proper depth testing. */}
      {showULabels && !renderStructure && (
        <>
          <mesh position={[-railXOffset - 0.14, rackHeight / 2, railZOffset + 0.025]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial map={railTexture} transparent opacity={0.95} />
          </mesh>
          <mesh position={[railXOffset + 0.14, rackHeight / 2, railZOffset + 0.025]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial map={railTexture} transparent opacity={0.95} />
          </mesh>
          <mesh position={[-railXOffset - 0.14, rackHeight / 2, -railZOffset - 0.025]} rotation={[0, Math.PI, 0]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial map={railTexture} transparent opacity={0.95} />
          </mesh>
          <mesh position={[railXOffset + 0.14, rackHeight / 2, -railZOffset - 0.025]} rotation={[0, Math.PI, 0]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial map={railTexture} transparent opacity={0.95} />
          </mesh>
        </>
      )}

      {/* Informative Empty U Slots (Read-only Spatial Indicators) */}
      <group>
        {Array.from({ length: totalU }, (_, i) => {
          const u = i + 1;
          const isOccupied = occupiedUs.has(u);
          if (isOccupied) return null;

          const slotCenterY = (u - 0.5) * U_HEIGHT_3D;
          const isHovered = hoveredEmptyU === u;

          return (
            <group key={u} position={[0, slotCenterY, 0]}>
              {/* Raycasting Target Mesh */}
              <mesh
                onPointerOver={(e) => {
                  e.stopPropagation();
                  setHoveredEmptyU(u);
                  if (onHoverEmptyU) onHoverEmptyU(u);
                }}
                onPointerOut={(e) => {
                  e.stopPropagation();
                  setHoveredEmptyU(null);
                  if (onHoverEmptyU) onHoverEmptyU(null);
                }}
              >
                <boxGeometry args={[rackWidth - 0.2, U_HEIGHT_3D, rackDepth * 0.7]} />
                <meshBasicMaterial
                  color="#0ea5e9"
                  transparent
                  opacity={isHovered ? 0.18 : 0}
                  depthWrite={false}
                />
              </mesh>

              {/* Subtle Outline Box on Hover */}
              {isHovered && (
                <>
                  <mesh>
                    <boxGeometry args={[rackWidth - 0.2, U_HEIGHT_3D, rackDepth * 0.7]} />
                    <meshBasicMaterial color="#38bdf8" wireframe transparent opacity={0.45} />
                  </mesh>
                  <Html position={[0, 0, (rackDepth * 0.7) / 2 + 0.15]} center distanceFactor={22}>
                    <div className="px-2 py-0.5 rounded-md text-[10px] font-semibold text-slate-300 bg-slate-950/90 border border-slate-700/80 shadow-lg pointer-events-none whitespace-nowrap flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                      <span>{zh ? `U${u} 空闲（只读）` : `U${u} free (read-only)`}</span>
                    </div>
                  </Html>
                </>
              )}
            </group>
          );
        })}
      </group>

      {/* Animated Hinged Honeycomb Mesh Front Door + Rear Split Mesh Doors */}
      {showDoor && (
        <>
        <group
          ref={frontDoorRef}
          position={[-rackWidth / 2, 0, (rackDepth / 2) + 0.05]}
        >
          {/* Steel vertical stiles & swing-handle lock assembly */}
          <mesh position={[0.07, rackHeight / 2, 0]}>
            <boxGeometry args={[0.14, rackHeight, 0.06]} />
            <meshStandardMaterial color="#1f2937" roughness={0.38} metalness={0.72} />
          </mesh>
          <mesh position={[rackWidth - 0.07, rackHeight / 2, 0]}>
            <boxGeometry args={[0.14, rackHeight, 0.06]} />
            <meshStandardMaterial color="#1f2937" roughness={0.38} metalness={0.72} />
          </mesh>
          <mesh position={[rackWidth - 0.24, rackHeight * 0.5 + 0.25, 0.085]}>
            <boxGeometry args={[0.05, 0.16, 0.03]} />
            <meshStandardMaterial color="#0f172a" roughness={0.4} metalness={0.6} />
          </mesh>
          {/* Door Mesh Panel */}
          <mesh position={[rackWidth / 2, rackHeight / 2, 0]}>
            <planeGeometry args={[rackWidth - 0.15, rackHeight - 0.1]} />
            <meshStandardMaterial
              map={doorTexture}
              transparent
              opacity={0.45}
              roughness={0.5}
              metalness={0.25}
            />
          </mesh>

          {/* Door Handle */}
          <mesh position={[rackWidth - 0.25, rackHeight / 2, 0.04]}>
            <boxGeometry args={[0.1, 0.9, 0.07]} />
            <meshStandardMaterial color="#cbd5e1" roughness={0.25} metalness={0.85} />
          </mesh>
        </group>
        {/* Rear Split Double-Leaf Honeycomb Doors */}
        <group ref={rearLeftDoorRef} position={[-rackWidth / 2, 0, -(rackDepth / 2) - 0.05]}>
          <mesh position={[rackWidth * 0.25, rackHeight / 2, 0]}>
            <planeGeometry args={[rackWidth * 0.48, rackHeight - 0.12]} />
            <meshStandardMaterial map={doorTexture} transparent opacity={0.45} roughness={0.44} metalness={0.45} side={THREE.DoubleSide} />
          </mesh>
          <mesh position={[rackWidth * 0.48, rackHeight / 2, -0.04]}>
            <boxGeometry args={[0.06, 0.65, 0.05]} />
            <meshStandardMaterial color="#94a3b8" roughness={0.3} metalness={0.8} />
          </mesh>
        </group>
        <group ref={rearRightDoorRef} position={[rackWidth / 2, 0, -(rackDepth / 2) - 0.05]}>
          <mesh position={[-rackWidth * 0.25, rackHeight / 2, 0]}>
            <planeGeometry args={[rackWidth * 0.48, rackHeight - 0.12]} />
            <meshStandardMaterial map={doorTexture} transparent opacity={0.45} roughness={0.44} metalness={0.45} side={THREE.DoubleSide} />
          </mesh>
          <mesh position={[-rackWidth * 0.48, rackHeight / 2, -0.04]}>
            <boxGeometry args={[0.06, 0.65, 0.05]} />
            <meshStandardMaterial color="#94a3b8" roughness={0.3} metalness={0.8} />
          </mesh>
        </group>
        </>
      )}
    </group>
  );
};

