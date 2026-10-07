import React from 'react';

export type SfpModuleMedia = 'fiber' | 'copper' | 'dac' | 'unknown';

interface SfpModuleAssemblyProps {
  x: number;
  yOffset: number;
  frontZ: number;
  media: SfpModuleMedia;
}

const MEDIA_STYLE: Record<SfpModuleMedia, {
  body: string;
  face: string;
  accent: string;
  label: string;
}> = {
  fiber: {
    body: '#5f6b75',
    face: '#0c151d',
    accent: '#59d9c1',
    label: '#8be8d7',
  },
  copper: {
    body: '#6c5946',
    face: '#15100b',
    accent: '#e9b65b',
    label: '#f4c978',
  },
  dac: {
    body: '#415b66',
    face: '#07171e',
    accent: '#4bd6ee',
    label: '#7de8f7',
  },
  unknown: {
    body: '#56616b',
    face: '#0b131a',
    accent: '#7c8c97',
    label: '#a4b2bd',
  },
};

/**
 * A small inserted SFP/SFP+ transceiver body for a verified physical link.
 * Empty SFP cages remain the GLB socket; this component only appears when a
 * topology endpoint proves that a pluggable is present.
 */
export const SfpModuleAssembly: React.FC<SfpModuleAssemblyProps> = ({
  x,
  yOffset,
  frontZ,
  media,
}) => {
  const style = MEDIA_STYLE[media];
  const moduleZ = frontZ + 0.176;
  const faceZ = frontZ + 0.205;

  return (
    <group position={[x, yOffset, 0]} renderOrder={7}>
      {/* Inserted transceiver canister, recessed into the existing cage. */}
      <mesh position={[0, 0, moduleZ]} renderOrder={7}>
        <boxGeometry args={[0.103, 0.072, 0.052]} />
        <meshStandardMaterial color={style.body} roughness={0.34} metalness={0.78} />
      </mesh>
      <mesh position={[0, 0, faceZ]} renderOrder={8}>
        <boxGeometry args={[0.087, 0.052, 0.008]} />
        <meshStandardMaterial color={style.face} roughness={0.22} metalness={0.46} />
      </mesh>

      {/* Pull tab / latch at the top edge of the module. */}
      <mesh position={[0, 0.043, frontZ + 0.190]} renderOrder={9}>
        <boxGeometry args={[0.071, 0.008, 0.012]} />
        <meshStandardMaterial color={style.accent} roughness={0.27} metalness={0.78} />
      </mesh>
      <mesh position={[0, -0.039, frontZ + 0.191]} renderOrder={9}>
        <boxGeometry args={[0.070, 0.006, 0.009]} />
        <meshStandardMaterial color="#28343d" roughness={0.32} metalness={0.72} />
      </mesh>

      {/* A visible receptacle. Optical SFPs expose two small LC apertures;
          copper/DAC variants keep a single compact insert face. */}
      {media === 'fiber' ? (
        [-0.017, 0.017].map(socketX => (
          <group key={socketX}>
            <mesh position={[socketX, 0.002, frontZ + 0.211]} rotation={[Math.PI / 2, 0, 0]} renderOrder={10}>
              <cylinderGeometry args={[0.008, 0.008, 0.007, 12]} />
              <meshStandardMaterial color="#02060a" roughness={0.18} metalness={0.35} />
            </mesh>
            <mesh position={[socketX, 0.002, frontZ + 0.216]} rotation={[Math.PI / 2, 0, 0]} renderOrder={11}>
              <cylinderGeometry args={[0.0034, 0.0034, 0.002, 12]} />
              <meshStandardMaterial
                color="#157d73"
                emissive={style.accent}
                emissiveIntensity={0.48}
                toneMapped={false}
              />
            </mesh>
          </group>
        ))
      ) : (
        <>
          <mesh position={[0, 0.002, frontZ + 0.211]} renderOrder={10}>
            <boxGeometry args={[media === 'copper' ? 0.060 : 0.052, 0.023, 0.006]} />
            <meshStandardMaterial color="#02060a" roughness={0.18} metalness={0.35} />
          </mesh>
          <mesh position={[0, -0.002, frontZ + 0.215]} renderOrder={11}>
            <boxGeometry args={[media === 'copper' ? 0.042 : 0.032, 0.004, 0.003]} />
            <meshStandardMaterial
              color={style.accent}
              emissive={style.accent}
              emissiveIntensity={0.3}
              toneMapped={false}
            />
          </mesh>
        </>
      )}

      {/* Tiny silk mark: optical modules use a cool mark, copper modules an
          amber mark, and DAC a cyan mark. */}
      <mesh position={[0.035, 0.021, frontZ + 0.214]} renderOrder={11}>
        <boxGeometry args={[0.013, 0.003, 0.002]} />
        <meshStandardMaterial color={style.label} emissive={style.label} emissiveIntensity={0.22} toneMapped={false} />
      </mesh>
    </group>
  );
};
