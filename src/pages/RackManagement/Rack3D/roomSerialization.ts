import * as THREE from 'three';
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DataCenterRoomModel, RackFleetPlacement } from './fleetLayout';

export interface ImportedGlbAsset {
  id: string;
  name: string;
  object: THREE.Group;
  position: [number, number, number];
  rotationY: number;
  scale: number;
  /** Original normalized dimensions in meters (width, height, depth) */
  sizeMeters: [number, number, number];
  attachedRackId?: string | null;
}

export interface RoomBlueprintPayload {
  schema: 'nexora.datacenter3d.blueprint/v1';
  exportedAt: string;
  standards: string[];
  analysisMode: string;
  layers: Record<string, boolean>;
  bounds: DataCenterRoomModel['bounds'];
  totals: DataCenterRoomModel['totals'];
  zones: DataCenterRoomModel['zones'];
  coldAisles: DataCenterRoomModel['coldAisles'];
  rows: Array<{
    id: string;
    label: string;
    zoneKind: string;
    z: number;
    xMin: number;
    xMax: number;
    facing: 1 | -1;
    rackCount: number;
    totalPowerW: number;
    usedU: number;
    totalU: number;
  }>;
  infrastructure: {
    upsUnits: DataCenterRoomModel['upsUnits'];
    batteryUnits: DataCenterRoomModel['batteryUnits'];
    cracUnits: DataCenterRoomModel['cracUnits'];
    pdfCabinets: DataCenterRoomModel['pdfCabinets'];
    odfUnits: Array<Omit<DataCenterRoomModel['odfUnits'][number], 'odfFrame'> & { odfFrameId: string | null }>;
    trays: DataCenterRoomModel['trays'];
  };
  racks: Array<{
    id: string;
    name: string;
    site_label?: string;
    floor?: string;
    room?: string;
    row?: string;
    zoneKind: string;
    archetype: string;
    facing: 1 | -1;
    position: [number, number, number];
    total_u: number;
    used_u: number;
    power_used_watts: number | null;
    health_status: string;
  }>;
  interRackLinks: Array<{
    id: string;
    sourceRackId: string;
    targetRackId: string;
    linkCount: number;
    label: string;
  }>;
  customModels: Array<{
    id: string;
    name: string;
    position: [number, number, number];
    rotationY: number;
    scale: number;
    sizeMeters: [number, number, number];
    attachedRackId?: string | null;
  }>;
}

export function buildRoomBlueprintJson(params: {
  room: DataCenterRoomModel;
  placements: RackFleetPlacement[];
  analysisMode: string;
  layers: Record<string, boolean>;
  interRackLinks?: Array<{
    id: string;
    sourceRackId: string;
    targetRackId: string;
    linkCount: number;
    label: string;
  }>;
  customModels?: ImportedGlbAsset[];
}): RoomBlueprintPayload {
  const {
    room,
    placements,
    analysisMode,
    layers,
    interRackLinks = [],
    customModels = [],
  } = params;

  return {
    schema: 'nexora.datacenter3d.blueprint/v1',
    exportedAt: new Date().toISOString(),
    standards: ['GB 50174-2017', 'GB 50462-2015', 'GB 50370-2005'],
    analysisMode,
    layers: { ...layers },
    bounds: { ...room.bounds },
    totals: { ...room.totals },
    zones: room.zones.map(z => ({ ...z, bounds: { ...z.bounds } })),
    coldAisles: room.coldAisles.map(a => ({ ...a })),
    rows: room.rows.map(r => ({
      id: r.id,
      label: r.label,
      zoneKind: r.zoneKind,
      z: r.z,
      xMin: r.xMin,
      xMax: r.xMax,
      facing: r.facing,
      rackCount: r.rackCount,
      totalPowerW: r.totalPowerW,
      usedU: r.usedU,
      totalU: r.totalU,
    })),
    infrastructure: {
      upsUnits: room.upsUnits.map(u => ({ ...u })),
      batteryUnits: room.batteryUnits.map(b => ({ ...b })),
      cracUnits: room.cracUnits.map(c => ({ ...c })),
      pdfCabinets: room.pdfCabinets.map(p => ({ ...p })),
      odfUnits: room.odfUnits.map(({ odfFrame, ...rest }) => ({
        ...rest,
        odfFrameId: odfFrame?.id ?? null,
      })),
      trays: room.trays.map(t => ({ ...t })),
    },
    racks: placements.map(p => ({
      id: p.rack.id,
      name: p.rack.name,
      site_label: p.rack.site_label,
      floor: p.rack.floor,
      room: p.rack.room,
      row: p.rack.row,
      zoneKind: p.zoneKind,
      archetype: p.archetype,
      facing: p.facing,
      position: [...p.position] as [number, number, number],
      total_u: p.rack.total_u,
      used_u: p.rack.used_u,
      power_used_watts: p.rack.power_used_watts,
      health_status: p.rack.health_status,
    })),
    interRackLinks: interRackLinks.map(l => ({ ...l })),
    customModels: customModels.map(m => ({
      id: m.id,
      name: m.name,
      position: [...m.position] as [number, number, number],
      rotationY: m.rotationY,
      scale: m.scale,
      sizeMeters: [...m.sizeMeters] as [number, number, number],
      attachedRackId: m.attachedRackId ?? null,
    })),
  };
}

function sanitizeUserData(raw: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!raw) return {};
  const out: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(raw)) {
    if (
      typeof val === 'string' ||
      typeof val === 'number' ||
      typeof val === 'boolean' ||
      val === null
    ) {
      out[key] = val;
    }
  }
  return out;
}

function isDegenerateMatrix(m: THREE.Matrix4): boolean {
  const te = m.elements;
  const sxSq = te[0] * te[0] + te[1] * te[1] + te[2] * te[2];
  const sySq = te[4] * te[4] + te[5] * te[5] + te[6] * te[6];
  const szSq = te[8] * te[8] + te[9] * te[9] + te[10] * te[10];
  return sxSq < 1e-10 || sySq < 1e-10 || szSq < 1e-10;
}

/**
 * Flatten a live Three.js scene subtree into a clean, exportable Group:
 * - Skips hidden nodes and nodes tagged with `userData.excludeFromExport === true`
 * - Expands active `THREE.InstancedMesh` instances (preserving `instanceColor`) into standard `THREE.Mesh` nodes
 *   so Blender, GLB viewers, and Three.js ObjectLoader preserve every rack, nozzle, detector, and cable drop.
 */
export function buildExportableSceneGroup(root: THREE.Object3D): {
  group: THREE.Group;
  dispose: () => void;
} {
  root.updateMatrixWorld(true);
  const exportGroup = new THREE.Group();
  exportGroup.name = root.name || 'DataCenterHall3D';

  const tempMaterials: THREE.Material[] = [];
  const tmpMatrix = new THREE.Matrix4();
  const worldMatrix = new THREE.Matrix4();
  const pos = new THREE.Vector3();
  const quat = new THREE.Quaternion();
  const scale = new THREE.Vector3();
  const instColor = new THREE.Color();

  const walk = (node: THREE.Object3D) => {
    if (!node.visible || node.userData?.excludeFromExport === true) {
      return;
    }

    if ((node as THREE.InstancedMesh).isInstancedMesh) {
      const instMesh = node as THREE.InstancedMesh;
      const baseMat = Array.isArray(instMesh.material) ? instMesh.material[0] : instMesh.material;
      const colorMatCache = new Map<number, THREE.Material>();

      for (let i = 0; i < instMesh.count; i++) {
        instMesh.getMatrixAt(i, tmpMatrix);
        worldMatrix.multiplyMatrices(instMesh.matrixWorld, tmpMatrix);

        // Skip hidden / uninitialized zero-scale instances before decompose()
        if (isDegenerateMatrix(worldMatrix)) continue;
        worldMatrix.decompose(pos, quat, scale);

        let matForInstance: THREE.Material | THREE.Material[] = instMesh.material;
        if (instMesh.instanceColor && baseMat) {
          instMesh.getColorAt(i, instColor);
          const hex = instColor.getHex();
          let cached = colorMatCache.get(hex);
          if (!cached) {
            const cloned = baseMat.clone();
            if ('color' in cloned && (cloned as THREE.MeshStandardMaterial).color instanceof THREE.Color) {
              (cloned as THREE.MeshStandardMaterial).color.multiply(instColor);
            }
            colorMatCache.set(hex, cloned);
            tempMaterials.push(cloned);
            cached = cloned;
          }
          matForInstance = cached;
        }

        const singleMesh = new THREE.Mesh(instMesh.geometry, matForInstance);
        singleMesh.name = `${instMesh.name || 'instance'}_${i}`;
        singleMesh.position.copy(pos);
        singleMesh.quaternion.copy(quat);
        singleMesh.scale.copy(scale);
        singleMesh.userData = sanitizeUserData(instMesh.userData);
        exportGroup.add(singleMesh);
      }
      return;
    }

    if ((node as THREE.Mesh).isMesh) {
      const mesh = node as THREE.Mesh;
      if (!isDegenerateMatrix(mesh.matrixWorld)) {
        mesh.matrixWorld.decompose(pos, quat, scale);
        const cloned = new THREE.Mesh(mesh.geometry, mesh.material);
        cloned.name = mesh.name || 'mesh';
        cloned.position.copy(pos);
        cloned.quaternion.copy(quat);
        cloned.scale.copy(scale);
        cloned.userData = sanitizeUserData(mesh.userData);
        exportGroup.add(cloned);
      }
      return;
    }

    for (const child of node.children) {
      walk(child);
    }
  };

  walk(root);

  return {
    group: exportGroup,
    dispose: () => {
      for (const m of tempMaterials) {
        m.dispose();
      }
    },
  };
}

export async function exportRoomToGlb(root: THREE.Object3D): Promise<Blob> {
  const { group, dispose } = buildExportableSceneGroup(root);
  const exporter = new GLTFExporter();
  try {
    const result = await new Promise<ArrayBuffer>((resolve, reject) => {
      exporter.parse(
        group,
        output => {
          if (output instanceof ArrayBuffer) {
            resolve(output);
          } else {
            const text = JSON.stringify(output);
            resolve(new TextEncoder().encode(text).buffer);
          }
        },
        err => reject(err instanceof Error ? err : new Error(String(err))),
        { binary: true, onlyVisible: true },
      );
    });
    return new Blob([result], { type: 'model/gltf-binary' });
  } finally {
    dispose();
  }
}

export function exportRoomToThreeSceneJson(root: THREE.Object3D): Blob {
  const { group, dispose } = buildExportableSceneGroup(root);
  try {
    const json = JSON.stringify(group.toJSON(), null, 2);
    return new Blob([json], { type: 'application/json' });
  } finally {
    dispose();
  }
}

export function exportRoomToBlueprintJson(
  params: Parameters<typeof buildRoomBlueprintJson>[0],
): Blob {
  const payload = buildRoomBlueprintJson(params);
  return new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
}

export async function parseLocalGlbFile(
  file: File,
  defaultPosition: [number, number, number],
): Promise<ImportedGlbAsset> {
  const buffer = await file.arrayBuffer();
  const loader = new GLTFLoader();
  const gltf = await new Promise<Awaited<ReturnType<GLTFLoader['parseAsync']>>>((resolve, reject) => {
    loader.parse(
      buffer,
      '',
      parsed => resolve(parsed),
      err => reject(err instanceof Error ? err : new Error(String(err))),
    );
  });

  const wrapper = new THREE.Group();
  const scene = gltf.scene;
  wrapper.name = `imported_${file.name}`;

  const rawBox = new THREE.Box3().setFromObject(scene);
  const rawSize = new THREE.Vector3();
  rawBox.getSize(rawSize);

  const maxDim = Math.max(rawSize.x, rawSize.y, rawSize.z);
  let autoScale = 1;
  // Auto-normalize models exported in millimeters/centimeters or microscopic scale
  if (maxDim > 8 || (maxDim > 0 && maxDim < 0.08)) {
    const targetHeight = 2.0;
    const refHeight = rawSize.y > 0.001 ? rawSize.y : maxDim;
    autoScale = refHeight > 0 ? targetHeight / refHeight : 1;
  }
  scene.scale.multiplyScalar(autoScale);
  scene.updateMatrixWorld(true);

  const scaledBox = new THREE.Box3().setFromObject(scene);
  const center = new THREE.Vector3();
  const finalSize = new THREE.Vector3();
  scaledBox.getCenter(center);
  scaledBox.getSize(finalSize);

  // Center X/Z around local origin and seat bottom flush on the raised floor (Y = 0)
  scene.position.x -= center.x;
  scene.position.z -= center.z;
  scene.position.y -= scaledBox.min.y;
  wrapper.add(scene);

  return {
    id: `glb-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    name: file.name,
    object: wrapper,
    position: [
      Number(defaultPosition[0].toFixed(2)),
      0,
      Number(defaultPosition[2].toFixed(2)),
    ],
    rotationY: 0,
    scale: 1,
    sizeMeters: [
      Number(finalSize.x.toFixed(2)),
      Number(finalSize.y.toFixed(2)),
      Number(finalSize.z.toFixed(2)),
    ],
    attachedRackId: null,
  };
}

export function disposeGlbObject(obj: THREE.Object3D): void {
  obj.traverse(child => {
    if ((child as THREE.Mesh).isMesh) {
      const mesh = child as THREE.Mesh;
      mesh.geometry?.dispose();
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const mat of mats) {
        if (!mat) continue;
        const std = mat as THREE.MeshStandardMaterial;
        std.map?.dispose();
        std.normalMap?.dispose();
        std.roughnessMap?.dispose();
        std.metalnessMap?.dispose();
        std.emissiveMap?.dispose();
        mat.dispose();
      }
    }
  });
}

export function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
