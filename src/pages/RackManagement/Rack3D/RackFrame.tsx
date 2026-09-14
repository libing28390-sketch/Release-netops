import React, { useState, useMemo } from 'react';
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
  // Keep the mounting rails inside the actual rack width.  A fixed 19-inch
  // offset makes 450mm/non-standard cabinets render their rails outside the
  // enclosure even when the read model supplies a different width_mm.
  const railXOffset = (rackWidth * (RACK_INNER_WIDTH / RACK_OUTER_WIDTH_DEFAULT)) / 2;
  const railZOffset = (rackDepth * 0.72) / 2;

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

      {/* Four mobile casters sit below the plinth.  Keep them outside the
          structural conditional so the production GLB and procedural frame
          share the same visible base detail. */}
      {[
        // Set the front pair just outside the plinth face so the wheel ring
        // remains visible even when the production GLB has a deep base lip.
        { x: -postOffsetW, z: postOffsetD + 0.38, front: true },
        { x: postOffsetW, z: postOffsetD + 0.38, front: true },
        { x: -postOffsetW, z: -postOffsetD - 0.38, front: false },
        { x: postOffsetW, z: -postOffsetD - 0.38, front: false },
      ].map((caster, index) => (
        <RackCasterAssembly
          key={`caster-${index}`}
          x={caster.x}
          // The GLB's caster bounds extend below the logical plinth to about
          // y=-1.0; matching that datum keeps the wheel under the base rather
          // than floating in the lowest empty U slots.
          y={-0.93}
          z={caster.z}
          front={caster.front}
        />
      ))}

      {/* The GLB carries the physical rails; this lightweight overlay keeps
          the viewer's U-number ruler available without duplicating posts or
          the cabinet shell. */}
      {showULabels && !renderStructure && (
        <>
          <mesh
            position={[-railXOffset, rackHeight / 2, railZOffset + 0.04]}
            renderOrder={20}
          >
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial
              map={railTexture}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh
            position={[railXOffset, rackHeight / 2, railZOffset + 0.04]}
            renderOrder={20}
          >
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial
              map={railTexture}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh
            position={[-railXOffset, rackHeight / 2, -railZOffset - 0.04]}
            rotation={[0, Math.PI, 0]}
            renderOrder={20}
          >
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial
              map={railTexture}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
          </mesh>
          <mesh
            position={[railXOffset, rackHeight / 2, -railZOffset - 0.04]}
            rotation={[0, Math.PI, 0]}
            renderOrder={20}
          >
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshBasicMaterial
              map={railTexture}
              transparent
              opacity={0.98}
              depthTest={false}
              depthWrite={false}
            />
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

      {/* Lightweight Honeycomb Mesh Front Door (shown as a compact open leaf) */}
      {showDoor && (
        <group
          position={[-rackWidth / 2, 0, (rackDepth / 2) + 0.05]}
          rotation={[0, isDoorOpen ? -Math.PI / 5.2 : 0, 0]}
        >
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
            <boxGeometry args={[0.06, 0.8, 0.06]} />
            <meshStandardMaterial color="#cbd5e1" roughness={0.3} metalness={0.6} />
          </mesh>
        </group>
      )}
    </group>
  );
};

