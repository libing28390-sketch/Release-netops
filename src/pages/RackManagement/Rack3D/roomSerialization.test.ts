import * as THREE from 'three';
import { describe, expect, it } from 'vitest';
import { RackSummary } from '../types';
import { buildDataCenterRoomModel, buildRackFleetLayout } from './fleetLayout';
import {
  buildExportableSceneGroup,
  buildRoomBlueprintJson,
  ImportedGlbAsset,
} from './roomSerialization';

const makeRack = (index: number): RackSummary => ({
  id: `rack-${index}`,
  name: `R-${String(index).padStart(3, '0')}`,
  datacenter: 'DC-A',
  floor: '1F',
  room: 'Room-1',
  row: String.fromCharCode(65 + (Math.floor(index / 20) % 20)),
  total_u: 42,
  description: '',
  status: 'active',
  created_at: '2026-08-28T00:00:00Z',
  updated_at: '2026-08-28T00:00:00Z',
  site_label: 'DC-A',
  device_count: 8,
  front_used: 8,
  rear_used: 0,
  used_u: 8,
  available_u: 34,
  u_utilization_pct: 19,
  power_used_watts: 1200,
  power_utilization_pct: 24,
  monitored_device_count: 8,
  healthy_device_count: 8,
  offline_device_count: 0,
  unknown_monitoring_device_count: 0,
  unlinked_asset_count: 0,
  unmonitored_device_count: 0,
  invalid_device_count: 0,
  health_status: 'healthy',
  data_quality_status: 'complete',
});

describe('roomSerialization', () => {
  it('builds a clean JSON-serializable Data Center Hall blueprint payload', () => {
    const placements = buildRackFleetLayout([makeRack(0), makeRack(1), makeRack(20), makeRack(21)]);
    const room = buildDataCenterRoomModel(placements);
    const customModel: ImportedGlbAsset = {
      id: 'glb-test-1',
      name: 'vendor-ups.glb',
      object: new THREE.Group(),
      position: [1.2, 0, -2.4],
      rotationY: Math.PI / 2,
      scale: 1,
      sizeMeters: [0.8, 2.0, 0.9],
      attachedRackId: 'rack-0',
    };

    const payload = buildRoomBlueprintJson({
      room,
      placements,
      analysisMode: 'physical',
      layers: { trays: true, cooling: true, odf: true, containment: true, airflow: true, architecture: true, fireMep: true },
      interRackLinks: [{ id: 'l1', sourceRackId: 'rack-0', targetRackId: 'rack-1', linkCount: 4, label: '4 LLDP' }],
      customModels: [customModel],
    });

    const roundTrip = JSON.parse(JSON.stringify(payload));
    expect(roundTrip.schema).toBe('nexora.datacenter3d.blueprint/v1');
    expect(roundTrip.standards).toContain('GB 50174-2017');
    expect(roundTrip.racks).toHaveLength(4);
    expect(roundTrip.infrastructure.upsUnits).toHaveLength(2);
    expect(roundTrip.infrastructure.batteryUnits).toHaveLength(2);
    expect(roundTrip.infrastructure.cracUnits.length).toBeGreaterThanOrEqual(4);
    expect(roundTrip.coldAisles).toHaveLength(1);
    expect(roundTrip.customModels).toEqual([
      {
        id: 'glb-test-1',
        name: 'vendor-ups.glb',
        position: [1.2, 0, -2.4],
        rotationY: Math.PI / 2,
        scale: 1,
        sizeMeters: [0.8, 2.0, 0.9],
        attachedRackId: 'rack-0',
      },
    ]);
  });

  it('flattens InstancedMesh instances with colors and skips excluded subtrees for GLB/Scene JSON export', () => {
    const root = new THREE.Group();
    root.name = 'DataCenterHall3D';

    const geo = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshStandardMaterial({ color: '#ffffff' });

    const regularMesh = new THREE.Mesh(geo, mat);
    regularMesh.name = 'floor_slab';
    regularMesh.position.set(2, 0, -1);
    root.add(regularMesh);

    const inst = new THREE.InstancedMesh(geo, mat, 3);
    inst.name = 'rack_hull';
    const dummy = new THREE.Object3D();
    // Instance 0: visible cyan
    dummy.position.set(0, 1, 0);
    dummy.scale.set(0.8, 2, 0.96);
    dummy.updateMatrix();
    inst.setMatrixAt(0, dummy.matrix);
    inst.setColorAt(0, new THREE.Color('#22d3ee'));
    // Instance 1: zero-scale hidden (must be skipped)
    dummy.position.set(0, 0, 0);
    dummy.scale.set(0, 0, 0);
    dummy.updateMatrix();
    inst.setMatrixAt(1, dummy.matrix);
    inst.setColorAt(1, new THREE.Color('#000000'));
    // Instance 2: visible amber
    dummy.position.set(0.84, 1, 0);
    dummy.scale.set(0.8, 2, 0.96);
    dummy.updateMatrix();
    inst.setMatrixAt(2, dummy.matrix);
    inst.setColorAt(2, new THREE.Color('#f59e0b'));
    root.add(inst);

    const excludedGroup = new THREE.Group();
    excludedGroup.userData = { excludeFromExport: true };
    excludedGroup.add(new THREE.Mesh(geo, mat));
    root.add(excludedGroup);

    const { group, dispose } = buildExportableSceneGroup(root);
    try {
      expect(group.children).toHaveLength(3);
      expect(group.children.map(c => c.name)).toEqual(['floor_slab', 'rack_hull_0', 'rack_hull_2']);

      const rack0Mat = (group.children[1] as THREE.Mesh).material as THREE.MeshStandardMaterial;
      const rack2Mat = (group.children[2] as THREE.Mesh).material as THREE.MeshStandardMaterial;
      expect(rack0Mat.color.getHexString()).not.toBe(rack2Mat.color.getHexString());

      const jsonObj = group.toJSON();
      expect(jsonObj.object).toBeDefined();
      expect(jsonObj.geometries.length).toBeGreaterThanOrEqual(1);
    } finally {
      dispose();
      geo.dispose();
      mat.dispose();
    }
  });
});
