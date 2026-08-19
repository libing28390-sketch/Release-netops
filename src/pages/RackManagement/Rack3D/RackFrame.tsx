import React, { useMemo } from 'react';
import {
  U_HEIGHT_3D,
  RACK_OUTER_WIDTH_DEFAULT,
  RACK_TOTAL_DEPTH_DEFAULT
} from '../adapters/rackViewModel';
import {
  getHoneycombDoorTexture,
  getRackRailTexture,
  getNameplateTexture
} from './utils/textures';

interface RackFrameProps {
  name: string;
  totalU: number;
  widthMm?: number;
  depthMm?: number;
  showDoor?: boolean;
  isDoorOpen?: boolean;
  showULabels?: boolean;
  onHoverEmptyU?: (u: number | null) => void;
}

export const RackFrame: React.FC<RackFrameProps> = ({
  name,
  totalU,
  widthMm = 600,
  depthMm = 1000,
  showDoor = true,
  isDoorOpen = true,
  showULabels = true
}) => {
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
  const railXOffset = 2.413; // 19 inch / 2 = 4.826 / 2
  const railZOffset = (rackDepth * 0.72) / 2;

  return (
    <group>
      {/* 4 Vertical Corner Structural Posts */}
      {postPositions.map((pos, i) => (
        <mesh key={i} position={pos} castShadow receiveShadow>
          <boxGeometry args={[postThickness, rackHeight, postThickness]} />
          <meshStandardMaterial color="#1e293b" roughness={0.35} metalness={0.8} />
        </mesh>
      ))}

      {/* Top Cap */}
      <mesh position={[0, rackHeight + 0.15, 0]} castShadow receiveShadow>
        <boxGeometry args={[rackWidth + 0.1, 0.3, rackDepth + 0.1]} />
        <meshStandardMaterial color="#1e293b" roughness={0.4} metalness={0.7} />
      </mesh>

      {/* Top Nameplate with High-Res Texture */}
      <mesh position={[0, rackHeight + 0.15, (rackDepth / 2) + 0.06]}>
        <planeGeometry args={[rackWidth * 0.75, 0.24]} />
        <meshBasicMaterial map={nameplateTexture} />
      </mesh>

      {/* Bottom Plinth Base */}
      <mesh position={[0, -0.2, 0]} castShadow receiveShadow>
        <boxGeometry args={[rackWidth + 0.1, 0.4, rackDepth + 0.1]} />
        <meshStandardMaterial color="#1e293b" roughness={0.45} metalness={0.7} />
      </mesh>

      {/* 4 Leveling Feet */}
      {postPositions.map((pos, i) => (
        <mesh key={i} position={[pos[0], -0.45, pos[2]]}>
          <cylinderGeometry args={[0.12, 0.16, 0.1, 16]} />
          <meshStandardMaterial color="#475569" roughness={0.3} metalness={0.9} />
        </mesh>
      ))}

      {/* Front Left & Right Vertical Mounting Rails with U Markings */}
      {showULabels && (
        <>
          <mesh position={[-railXOffset, rackHeight / 2, railZOffset]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshStandardMaterial map={railTexture} roughness={0.35} metalness={0.85} />
          </mesh>
          <mesh position={[railXOffset, rackHeight / 2, railZOffset]} scale={[-1, 1, 1]}>
            <planeGeometry args={[railWidth, rackHeight]} />
            <meshStandardMaterial map={railTexture} roughness={0.35} metalness={0.85} />
          </mesh>
        </>
      )}

      {/* Rear Vertical Mounting Rails */}
      <mesh position={[-railXOffset, rackHeight / 2, -railZOffset]} rotation={[0, Math.PI, 0]}>
        <planeGeometry args={[railWidth, rackHeight]} />
        <meshStandardMaterial map={railTexture} roughness={0.35} metalness={0.85} />
      </mesh>
      <mesh position={[railXOffset, rackHeight / 2, -railZOffset]} rotation={[0, Math.PI, 0]} scale={[-1, 1, 1]}>
        <planeGeometry args={[railWidth, rackHeight]} />
        <meshStandardMaterial map={railTexture} roughness={0.35} metalness={0.85} />
      </mesh>

      {/* Lightweight Honeycomb Mesh Front Door (100° Open by default) */}
      {showDoor && (
        <group
          position={[-rackWidth / 2, 0, (rackDepth / 2) + 0.05]}
          rotation={[0, isDoorOpen ? -Math.PI / 1.75 : 0, 0]}
        >
          {/* Door Mesh Panel */}
          <mesh position={[rackWidth / 2, rackHeight / 2, 0]}>
            <planeGeometry args={[rackWidth - 0.15, rackHeight - 0.1]} />
            <meshStandardMaterial
              map={doorTexture}
              transparent
              opacity={0.55}
              roughness={0.4}
              metalness={0.8}
            />
          </mesh>

          {/* Door Handle */}
          <mesh position={[rackWidth - 0.25, rackHeight / 2, 0.04]}>
            <boxGeometry args={[0.06, 0.8, 0.06]} />
            <meshStandardMaterial color="#cbd5e1" roughness={0.2} metalness={0.9} />
          </mesh>
        </group>
      )}
    </group>
  );
};
