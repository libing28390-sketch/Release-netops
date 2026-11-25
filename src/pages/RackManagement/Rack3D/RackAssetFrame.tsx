import React from 'react';
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
  const clonedScene = React.useMemo(() => scene.clone(true), [scene]);
  const widthScale = Math.max(0.1, widthMm / 600);
  const depthScale = Math.max(0.1, depthMm / 1000);
  const heightScale = Math.max(0.1, totalU / 42);

  // RackVision v2 GLB is native glTF 2.0 Y-up, centered on X=0/Z=0, U1 bottom at Y=0.
  // Pure positive scale preserves outward normals and eliminates all depth/winding hacks.
  return (
    <primitive
      object={clonedScene}
      position={[0, 0, 0]}
      rotation={[0, 0, 0]}
      scale={[10 * widthScale, 10 * heightScale, 10 * depthScale]}
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

/** Load the native Y-up RackVision v2 cabinet GLB with procedural frame fallback. */
export const RackAssetFrame: React.FC<RackFrameProps> = (props) => {
  const widthMm = props.widthMm ?? 600;
  const depthMm = props.depthMm ?? 1000;
  const totalU = props.totalU;
  const fallback = <RackFrame {...props} />;

  return (
    <RackGlbErrorBoundary fallback={fallback}>
      <React.Suspense fallback={fallback}>
        <RackGlbAsset widthMm={widthMm} depthMm={depthMm} totalU={totalU} />
        <RackFrame {...props} renderStructure={false} />
      </React.Suspense>
    </RackGlbErrorBoundary>
  );
};

useGLTF.preload(RACK_ASSET_URL);
