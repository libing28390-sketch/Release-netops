import React from 'react';
import * as THREE from 'three';
import { useGLTF } from '@react-three/drei';
import { RackFrame, RackFrameProps } from './RackFrame';

const RACK_ASSET_URL = '/assets/3d/rack_42u_600x1000.glb';

interface RackGlbAssetProps {
  widthMm: number;
  depthMm: number;
  totalU: number;
}

const RackGlbAsset: React.FC<RackGlbAssetProps> = ({ widthMm, depthMm, totalU }) => {
  const { scene } = useGLTF(RACK_ASSET_URL);
  const clonedScene = React.useMemo(() => {
    const clone = scene.clone(true);

    // The production cabinet header is a solid front cap whose lower bevel
    // overlaps the top two U positions by a few millimetres.  Keep the cap
    // visible, but do not let it depth-occlude a real device mounted in U41/U42
    // (or its cable endpoint).  Cloning the materials is important because
    // drei shares GLTF materials between instances.
    clone.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;
      const name = String(object.name || '').toUpperCase();
      if (!/^(RACK_DOOR_TOP|RACK_FRONT_HEADER|RACK_LABEL|RACK_MODEL_LABEL|RACK_TOP_CAP|RACK_STATUS_STRIP)$/.test(name)) return;
      object.renderOrder = -10;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      const clonedMaterials = materials.map(material => {
        const cloned = material.clone();
        cloned.depthWrite = false;
        return cloned;
      });
      object.material = Array.isArray(object.material) ? clonedMaterials : clonedMaterials[0];
    });
    return clone;
  }, [scene]);
  const widthScale = Math.max(0.1, widthMm / 600);
  const depthScale = Math.max(0.1, depthMm / 1000);
  const heightScale = Math.max(0.1, totalU / 42);
  const rackDepth = 10 * depthScale;

  // The rack asset uses Blender X/Y/Z = left-right/front-back/vertical;
  // the scene uses X/Y/Z = left-right/vertical/front-back.  The source GLB
  // origin is the bottom-front center and its depth extends toward local -Y;
  // the viewer's rack space is centered on Z=0, so translate it by half the
  // scene depth to align the physical front plane with the device contract.
  return (
    <primitive
      object={clonedScene}
      position={[0, 0, rackDepth / 2]}
      rotation={[Math.PI / 2, 0, 0]}
      scale={[10 * widthScale, 10 * depthScale, -10 * heightScale]}
    />
  );
};

class RackGlbErrorBoundary extends React.Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { hasError: boolean }
> {
  state: { hasError: boolean } = { hasError: false };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

/** Load the production cabinet GLB and retain the existing procedural frame as a safe fallback. */
export const RackAssetFrame: React.FC<RackFrameProps> = props => {
  const widthMm = props.widthMm ?? 600;
  const depthMm = props.depthMm ?? 1000;
  const totalU = props.totalU;
  const fallback = <RackFrame {...props} />;

  return (
    <RackGlbErrorBoundary fallback={fallback}>
      <React.Suspense fallback={fallback}>
        <RackGlbAsset widthMm={widthMm} depthMm={depthMm} totalU={totalU} />
        {/* Keep door/empty-U interactions from the existing viewer on top of
            the production cabinet without duplicating its structural mesh. */}
        <RackFrame {...props} renderStructure={false} />
      </React.Suspense>
    </RackGlbErrorBoundary>
  );
};

useGLTF.preload(RACK_ASSET_URL);
