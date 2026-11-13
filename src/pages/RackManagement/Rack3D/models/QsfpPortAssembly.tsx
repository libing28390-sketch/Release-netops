import React, { useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';

interface QsfpPortAssemblyProps {
  x: number;
  portNumber: number;
  frontZ: number;
  connected: boolean;
}

/**
 * Front-most QSFP28 socket detail used on the H3C S6800 asset.
 *
 * The production GLB carries the source cage and its metadata, but its solid
 * cage/slot layers read like a dust cap at the rack-wide camera distance. This
 * small physical overlay keeps the original labels/anchors while making the
 * opening, contact lanes and dual link lamps legible. It does not invent a
 * transceiver: only ports present in the verified topology receive a green
 * link lamp.
 */
export const QsfpPortAssembly: React.FC<QsfpPortAssemblyProps> = ({
  x,
  portNumber,
  frontZ,
  connected,
}) => {
  const primaryLed = useRef<THREE.MeshStandardMaterial | null>(null);
  const secondaryLed = useRef<THREE.MeshStandardMaterial | null>(null);

  useFrame(({ clock }) => {
    const time = clock.getElapsedTime();
    const pulse = connected ? 2.1 + Math.sin(time * 2.6 + portNumber * 0.21) * 0.3 : 0.08;

    [primaryLed.current, secondaryLed.current].forEach((material, index) => {
      if (!material) return;
      material.color.set(connected
        ? (index === 0 ? '#48ffc0' : '#21785d')
        : '#182c35');
      material.emissive.set(connected
        ? (index === 0 ? '#20d889' : '#0c5f43')
        : '#000000');
      material.emissiveIntensity = connected
        ? (index === 0 ? pulse : pulse * 0.42)
        : 0;
    });
  });

  const cavityWidth = 0.182;
  const cavityHeight = 0.104;
  const frameWidth = 0.236;
  const frameHeight = 0.154;
  const frameDepth = 0.026;
  const cavityZ = frontZ + 0.205;
  const frameZ = frontZ + 0.225;
  const ledY = -0.084;

  return (
    <group position={[x, 0.008, 0]} renderOrder={8}>
      {/* Deep socket opening: intentionally matte black, not a solid grey cap. */}
      <mesh position={[0, 0, cavityZ]} renderOrder={8}>
        <boxGeometry args={[cavityWidth, cavityHeight, 0.012]} />
        <meshStandardMaterial
          color="#03070c"
          roughness={0.2}
          metalness={0.35}
          toneMapped={false}
          polygonOffset
          polygonOffsetFactor={-2}
          polygonOffsetUnits={-2}
        />
      </mesh>

      {/* Four recessed optical contact lanes. They sit behind the lip so they
          read as contacts inside the cage rather than as a protective grille. */}
      {[-0.052, -0.017, 0.017, 0.052].map(contactX => (
        <mesh key={contactX} position={[contactX, -0.006, cavityZ + 0.009]} renderOrder={9}>
          <boxGeometry args={[0.009, cavityHeight * 0.68, 0.004]} />
          <meshStandardMaterial
            color="#b58b45"
            roughness={0.26}
            metalness={0.82}
            toneMapped={false}
          />
        </mesh>
      ))}

      {/* Brushed-metal cage lip: four independent pieces preserve the open
          center and give the socket a physical depth cue. */}
      <mesh position={[0, cavityHeight / 2 + 0.018, frameZ]} renderOrder={10}>
        <boxGeometry args={[frameWidth, 0.014, frameDepth]} />
        <meshStandardMaterial color="#7b8792" roughness={0.3} metalness={0.86} />
      </mesh>
      <mesh position={[0, -cavityHeight / 2 - 0.018, frameZ]} renderOrder={10}>
        <boxGeometry args={[frameWidth, 0.014, frameDepth]} />
        <meshStandardMaterial color="#56616b" roughness={0.34} metalness={0.86} />
      </mesh>
      <mesh position={[-cavityWidth / 2 - 0.018, 0, frameZ]} renderOrder={10}>
        <boxGeometry args={[0.014, cavityHeight, frameDepth]} />
        <meshStandardMaterial color="#66737d" roughness={0.3} metalness={0.86} />
      </mesh>
      <mesh position={[cavityWidth / 2 + 0.018, 0, frameZ]} renderOrder={10}>
        <boxGeometry args={[0.014, cavityHeight, frameDepth]} />
        <meshStandardMaterial color="#4f5b66" roughness={0.34} metalness={0.86} />
      </mesh>

      {/* The two lamps are below the socket, matching the S6800 faceplate. */}
      <mesh position={[-0.074, ledY, frameZ + 0.003]} renderOrder={11}>
        <boxGeometry args={[0.022, 0.011, 0.009]} />
        <meshStandardMaterial
          ref={primaryLed}
          color="#182c35"
          roughness={0.16}
          metalness={0.15}
          toneMapped={false}
        />
      </mesh>
      <mesh position={[0.074, ledY, frameZ + 0.003]} renderOrder={11}>
        <boxGeometry args={[0.022, 0.011, 0.009]} />
        <meshStandardMaterial
          ref={secondaryLed}
          color="#182c35"
          roughness={0.16}
          metalness={0.15}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
};
