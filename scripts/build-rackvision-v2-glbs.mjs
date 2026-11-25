/**
 * RackVision v2 Native Y-Up PBR GLB Asset Compiler
 *
 * Generates lightweight, batch-merged, physically-aligned glTF 2.0 (.glb) models
 * in standard Three.js / glTF right-handed coordinates (+X right, +Y up, +Z front).
 *
 * Scale convention: 1 GLB unit = 1 meter (scene applies uniform positive scale [10, 10, 10]).
 * - Rack (42U 600x1000mm): X in [-0.30, +0.30], Y in [0, 1.8669] (plinth/casters down to -0.108), Z in [-0.50, +0.50], rails at Z = +-0.42.
 * - 1U Device (centered at origin): width 0.442m (ears 0.4826m), height 0.0436m, nominal depth 0.84m (Z in [-0.42, +0.42], front bezel +0.42..+0.435).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const OUT_DIRS = [
  path.join(ROOT, 'public', 'assets', '3d'),
  path.join(ROOT, 'assets', 'build', 'glb'),
];

const U_M = 0.04445;

// ---------------------------------------------------------------------------
// Minimal deterministic binary glTF 2.0 (.glb) writer (zero browser DOM deps)
// ---------------------------------------------------------------------------
function exportSceneToGlbBuffer(materialsList, meshDefs) {
  const bufferChunks = [];
  let byteOffset = 0;
  const bufferViews = [];
  const accessors = [];
  const meshes = [];
  const nodes = [];

  const align4 = (len) => (4 - (len % 4)) % 4;
  const pushTypedArray = (arr, target) => {
    const buf = Buffer.from(arr.buffer, arr.byteOffset, arr.byteLength);
    const pad = align4(buf.length);
    bufferChunks.push(buf);
    if (pad > 0) bufferChunks.push(Buffer.alloc(pad));
    const viewIndex = bufferViews.length;
    bufferViews.push({
      buffer: 0,
      byteOffset,
      byteLength: buf.length,
      ...(target ? { target } : {}),
    });
    byteOffset += buf.length + pad;
    return viewIndex;
  };

  const gltfMaterials = materialsList.map((m) => ({
    name: m.name,
    doubleSided: Boolean(m.doubleSided),
    ...(m.alphaBlend ? { alphaMode: 'BLEND' } : {}),
    ...(m.emissive ? { emissiveFactor: m.emissive } : {}),
    pbrMetallicRoughness: {
      baseColorFactor: m.baseColor,
      metallicFactor: m.metallic ?? 0.5,
      roughnessFactor: m.roughness ?? 0.5,
    },
  }));

  for (const def of meshDefs) {
    const geo = def.geometry.index ? def.geometry : def.geometry;
    geo.computeVertexNormals();
    const posAttr = geo.getAttribute('position');
    const normAttr = geo.getAttribute('normal');
    const posArr = new Float32Array(posAttr.array);
    const normArr = new Float32Array(normAttr.array);

    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < posArr.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        const v = posArr[i + k];
        if (v < min[k]) min[k] = v;
        if (v > max[k]) max[k] = v;
      }
    }

    const posView = pushTypedArray(posArr, 34962);
    const posAcc = accessors.length;
    accessors.push({
      bufferView: posView,
      componentType: 5126,
      count: posAttr.count,
      type: 'VEC3',
      min,
      max,
    });

    const normView = pushTypedArray(normArr, 34962);
    const normAcc = accessors.length;
    accessors.push({
      bufferView: normView,
      componentType: 5126,
      count: normAttr.count,
      type: 'VEC3',
    });

    let idxAcc;
    if (geo.index) {
      const useU32 = posAttr.count > 65535;
      const idxArr = useU32 ? new Uint32Array(geo.index.array) : new Uint16Array(geo.index.array);
      const idxView = pushTypedArray(idxArr, 34963);
      idxAcc = accessors.length;
      accessors.push({
        bufferView: idxView,
        componentType: useU32 ? 5125 : 5123,
        count: idxArr.length,
        type: 'SCALAR',
      });
    }

    const meshIdx = meshes.length;
    meshes.push({
      name: def.name,
      primitives: [
        {
          attributes: { POSITION: posAcc, NORMAL: normAcc },
          ...(idxAcc !== undefined ? { indices: idxAcc } : {}),
          material: def.materialIndex,
        },
      ],
    });

    const nodeIdx = nodes.length;
    nodes.push({
      name: def.name,
      mesh: meshIdx,
      ...(def.translation ? { translation: def.translation } : {}),
      ...(def.extras ? { extras: def.extras } : {}),
    });
  }

  const rootNodeIdx = nodes.length;
  nodes.push({
    name: 'RACKVISION_V2_ROOT',
    children: nodes.map((_, i) => i),
    extras: { rackvision_spec: 'v2_yup_merged' },
  });

  const binBuffer = Buffer.concat(bufferChunks);
  const gltfJson = {
    asset: { version: '2.0', generator: 'Nexora RackVision v2 PBR Builder' },
    scene: 0,
    scenes: [{ name: 'Scene', nodes: [rootNodeIdx] }],
    nodes,
    meshes,
    materials: gltfMaterials,
    accessors,
    bufferViews,
    buffers: [{ byteLength: binBuffer.length }],
  };

  const jsonStr = JSON.stringify(gltfJson);
  const jsonBuf = Buffer.from(jsonStr, 'utf8');
  const jsonPad = align4(jsonBuf.length);
  const jsonChunk = jsonPad > 0 ? Buffer.concat([jsonBuf, Buffer.alloc(jsonPad, 0x20)]) : jsonBuf;

  const binPad = align4(binBuffer.length);
  const binChunk = binPad > 0 ? Buffer.concat([binBuffer, Buffer.alloc(binPad, 0x00)]) : binBuffer;

  const totalLength = 12 + 8 + jsonChunk.length + 8 + binChunk.length;
  const header = Buffer.alloc(12);
  header.writeUInt32LE(0x46546c67, 0); // 'glTF'
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(totalLength, 8);

  const jsonHeader = Buffer.alloc(8);
  jsonHeader.writeUInt32LE(jsonChunk.length, 0);
  jsonHeader.writeUInt32LE(0x4e4f534a, 4); // 'JSON'

  const binHeader = Buffer.alloc(8);
  binHeader.writeUInt32LE(binChunk.length, 0);
  binHeader.writeUInt32LE(0x004e4942, 4); // 'BIN\0'

  return Buffer.concat([header, jsonHeader, jsonChunk, binHeader, binChunk]);
}

function hexToRgba(hex, alpha = 1) {
  const c = new THREE.Color(hex);
  return [Number(c.r.toFixed(4)), Number(c.g.toFixed(4)), Number(c.b.toFixed(4)), alpha];
}

function box(w, h, d, x = 0, y = 0, z = 0) {
  const g = new THREE.BoxGeometry(w, h, d);
  if (x !== 0 || y !== 0 || z !== 0) g.translate(x, y, z);
  return g;
}

function cyl(rt, rb, h, segs, x = 0, y = 0, z = 0, rotX = 0, rotZ = 0) {
  const g = new THREE.CylinderGeometry(rt, rb, h, segs);
  if (rotX) g.rotateX(rotX);
  if (rotZ) g.rotateZ(rotZ);
  if (x !== 0 || y !== 0 || z !== 0) g.translate(x, y, z);
  return g;
}

class BatchBuilder {
  constructor() {
    this.materials = [];
    this.matMap = new Map();
    this.buckets = new Map();
    this.standaloneNodes = [];
  }

  mat(name, hex, metallic = 0.6, roughness = 0.38, extra = {}) {
    if (this.matMap.has(name)) return this.matMap.get(name);
    const idx = this.materials.length;
    this.materials.push({
      name,
      baseColor: hexToRgba(hex, extra.alpha ?? 1),
      metallic,
      roughness,
      doubleSided: extra.doubleSided ?? false,
      alphaBlend: extra.alphaBlend ?? false,
      emissive: extra.emissive ?? undefined,
    });
    this.matMap.set(name, idx);
    this.buckets.set(idx, []);
    return idx;
  }

  add(matIdx, geometry) {
    // Strip UVs so mergeGeometries never mismatches attributes across primitives
    if (geometry.getAttribute('uv')) geometry.deleteAttribute('uv');
    this.buckets.get(matIdx).push(geometry);
  }

  addNode(name, matIdx, geometry, translation = undefined, extras = undefined) {
    if (geometry.getAttribute('uv')) geometry.deleteAttribute('uv');
    this.standaloneNodes.push({ name, materialIndex: matIdx, geometry, translation, extras });
  }

  toGlb() {
    const meshDefs = [];
    for (const [matIdx, geos] of this.buckets.entries()) {
      if (!geos.length) continue;
      const merged = geos.length === 1 ? geos[0] : mergeGeometries(geos, false);
      meshDefs.push({
        name: `BATCH_${this.materials[matIdx].name}`,
        materialIndex: matIdx,
        geometry: merged,
      });
    }
    for (const node of this.standaloneNodes) {
      meshDefs.push(node);
    }
    return exportSceneToGlbBuffer(this.materials, meshDefs);
  }
}

// ---------------------------------------------------------------------------
// 1. Standard 42U 600x1000mm Industrial Server Cabinet
// ---------------------------------------------------------------------------
function buildRack42U() {
  const b = new BatchBuilder();
  const mFrame = b.mat('MAT_RACK_FRAME', '#1b222c', 0.68, 0.36);
  const mPanel = b.mat('MAT_RACK_SIDE_PANEL', '#141a22', 0.55, 0.46);
  const mRail = b.mat('MAT_RACK_EIA_RAIL', '#475569', 0.82, 0.28);
  const mHole = b.mat('MAT_RACK_DARK_TRIM', '#090d14', 0.3, 0.7);
  const mSteel = b.mat('MAT_RACK_CHROME', '#94a3b8', 0.88, 0.22);
  const mAccent = b.mat('MAT_RACK_CYAN_TRIM', '#0ea5e9', 0.3, 0.3, { emissive: [0.04, 0.38, 0.58] });

  const W = 0.60;
  const D = 1.00;
  const H = 42 * U_M; // 1.8669m
  const post = 0.032;

  // 4 outer structural corner posts
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      b.add(mFrame, box(post, H + 0.04, post, sx * (W / 2 - post / 2), H / 2, sz * (D / 2 - post / 2)));
    }
    // Top & bottom depth beams
    b.add(mFrame, box(post, 0.036, D - post * 2, sx * (W / 2 - post / 2), H + 0.018, 0));
    b.add(mFrame, box(post, 0.044, D - post * 2, sx * (W / 2 - post / 2), -0.022, 0));

    // Recessed side panels (split upper/lower industrial service panels with latch seam)
    const panelH = (H - 0.06) / 2;
    b.add(mPanel, box(0.008, panelH, D - 0.14, sx * (W / 2 - 0.01), panelH / 2 + 0.02, 0));
    b.add(mPanel, box(0.008, panelH, D - 0.14, sx * (W / 2 - 0.01), panelH * 1.5 + 0.04, 0));
    // Side horizontal support braces for EIA rails
    for (const braceY of [0.35, H * 0.5, H - 0.35]) {
      b.add(mFrame, box(0.018, 0.032, 0.88, sx * (W / 2 - 0.026), braceY, 0));
    }
  }

  // Front & rear top/bottom cross headers + slim cyan architectural light strip
  for (const sz of [-1, 1]) {
    b.add(mFrame, box(W, 0.042, 0.036, 0, H + 0.021, sz * (D / 2 - 0.018)));
    b.add(mFrame, box(W, 0.048, 0.04, 0, -0.024, sz * (D / 2 - 0.02)));
  }
  b.add(mAccent, box(W - 0.12, 0.005, 0.006, 0, H + 0.021, D / 2 + 0.002));

  // Roof canopy with cable brush entry slots & 4-fan exhaust module
  b.add(mFrame, box(W - 0.02, 0.016, D - 0.02, 0, H + 0.042, 0));
  b.add(mHole, box(0.38, 0.02, 0.09, 0, H + 0.043, -0.34)); // rear cable brush entry
  b.add(mHole, box(0.38, 0.02, 0.07, 0, H + 0.043, 0.34)); // front fiber waterfall brush entry
  for (const fx of [-0.14, 0.14]) {
    for (const fz of [-0.08, 0.12]) {
      b.add(mHole, cyl(0.068, 0.068, 0.02, 18, fx, H + 0.043, fz));
      b.add(mSteel, cyl(0.02, 0.02, 0.024, 12, fx, H + 0.044, fz));
    }
  }

  // Heavy plinth base + 4 industrial casters + leveling feet (reaching Y = -0.106m)
  b.add(mFrame, box(W - 0.01, 0.042, D - 0.01, 0, -0.045, 0));
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      const cx = sx * (W / 2 - 0.055);
      const cz = sz * (D / 2 - 0.065);
      b.add(mSteel, box(0.048, 0.018, 0.058, cx, -0.072, cz));
      b.add(mHole, cyl(0.026, 0.026, 0.024, 16, cx, -0.082, cz, 0, Math.PI / 2));
      // Leveling foot next to caster
      b.add(mSteel, cyl(0.01, 0.01, 0.036, 10, cx, -0.084, cz - sz * 0.055));
      b.add(mHole, cyl(0.022, 0.024, 0.01, 12, cx, -0.103, cz - sz * 0.055));
    }
  }

  // 4 EIA-310 19-inch vertical mounting rails at Z = +-0.42m, X = +-0.2325m
  const railZ = 0.42;
  const railX = 0.2325;
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      // L-profile steel rail
      b.add(mRail, box(0.022, H, 0.006, sx * railX, H / 2, sz * railZ - sz * 0.003));
      b.add(mRail, box(0.006, H, 0.028, sx * (railX + sx * 0.011), H / 2, sz * railZ - sz * 0.016));
    }
    // Dual Rear 0U Vertical Smart PDUs (Left = A-Feed Red, Right = B-Feed Blue)
    const pduX = sx * (W / 2 - 0.046);
    const pduZ = -0.33;
    const pduH = H - 0.24;
    const mPduFeed = sx < 0
      ? b.mat('MAT_PDU_FEED_A', '#dc2626', 0.35, 0.3, { emissive: [0.22, 0.02, 0.02] })
      : b.mat('MAT_PDU_FEED_B', '#2563eb', 0.35, 0.3, { emissive: [0.02, 0.08, 0.26] });
    const mPduMeter = b.mat('MAT_PDU_AMMETER', '#10b981', 0.15, 0.2, { emissive: [0.04, 0.55, 0.25] });
    b.add(mRail, box(0.044, pduH, 0.048, pduX, H / 2, pduZ));
    b.add(mPduFeed, box(0.012, pduH - 0.04, 0.008, pduX, H / 2, pduZ - 0.025));
    // Illuminated digital current meter halfway up each 0U PDU
    b.add(mHole, box(0.036, 0.068, 0.012, pduX, H * 0.52, pduZ - 0.026));
    b.add(mPduMeter, box(0.026, 0.036, 0.006, pduX, H * 0.52, pduZ - 0.031));
    // 24 IEC C13/C19 power outlets down the rear face of each 0U PDU
    for (let s = 0; s < 24; s++) {
      const sy = 0.18 + (s / 23) * (pduH - 0.14);
      if (Math.abs(sy - H * 0.52) < 0.055) continue;
      b.add(mHole, box(0.024, 0.024, 0.008, pduX, sy, pduZ - 0.025));
    }
  }

  // Crisp square cage-nut notches every 1U on front rails (lightweight: 1 recessed dark strip + U tick)
  for (let u = 1; u <= 42; u++) {
    const uCenterY = (u - 0.5) * U_M;
    for (const sx of [-1, 1]) {
      b.add(mHole, box(0.009, U_M * 0.68, 0.002, sx * railX, uCenterY, railZ + 0.0008));
      if (u % 5 === 0 || u === 1 || u === 42) {
        b.add(mAccent, box(0.02, 0.0018, 0.0022, sx * railX, (u - 1) * U_M + 0.001, railZ + 0.001));
      }
    }
  }

  return b.toGlb();
}

// ---------------------------------------------------------------------------
// Shared 1U/2U Hardware Chassis & Port Primitives
// ---------------------------------------------------------------------------
function createHardwareChassis(b, {
  heightU = 1,
  bodyHex = '#232b36',
  faceHex = '#1a222d',
  earHex = '#3b4758',
  accentHex = '#0ea5e9',
  dualPsu = true,
  fanCount = 4,
  fanHandleHex = '#dc2626',
  omitLeftMgmtBlock = false,
}) {
  const mBody = b.mat('MAT_CHASSIS_BODY', bodyHex, 0.65, 0.42);
  const mFace = b.mat('MAT_FACEPLATE', faceHex, 0.72, 0.32);
  const mEar = b.mat('MAT_RACK_EAR', earHex, 0.82, 0.28);
  const mDark = b.mat('MAT_CAVITY_DARK', '#060a10', 0.25, 0.75);
  const mShield = b.mat('MAT_PORT_SHIELD', '#94a3b8', 0.88, 0.22);
  const mGold = b.mat('MAT_CONTACT_GOLD', '#eab308', 0.92, 0.22);
  const mAccent = b.mat('MAT_BRAND_ACCENT', accentHex, 0.4, 0.3, {
    emissive: hexToRgba(accentHex).slice(0, 3).map((v) => v * 0.35),
  });
  const mPsuFan = b.mat('MAT_REAR_MODULE_HANDLE', fanHandleHex, 0.5, 0.35);

  const H = heightU * U_M - 0.0009; // 0.04355m for 1U
  const W_BODY = 0.440;
  const W_EARS = 0.4826;
  const Z_FRONT = 0.42;
  const Z_REAR = -0.42;
  const D = Z_FRONT - Z_REAR; // 0.84m

  // Main sheet-metal chassis + top/bottom subtle bevel seams
  b.add(mBody, box(W_BODY, H, D, 0, 0, 0));
  // Front sculpted bezel (protrudes +14mm in front of mounting rail plane Z=+0.42)
  b.add(mFace, box(W_BODY + 0.002, H - 0.0015, 0.014, 0, 0, Z_FRONT + 0.007));
  // Left brand accent stripe (skipped for edge-to-edge silver switches like H3C S6850)
  if (!omitLeftMgmtBlock) {
    b.add(mAccent, box(0.004, H - 0.008, 0.003, -W_BODY / 2 + 0.006, 0, Z_FRONT + 0.0145));
  }

  // Left & Right EIA-310 Rack Mounting Ears + captive screws + pull handles
  for (const sx of [-1, 1]) {
    const earW = (W_EARS - W_BODY) / 2;
    const earX = sx * (W_BODY / 2 + earW / 2);
    b.add(mEar, box(earW, H - 0.001, 0.005, earX, 0, Z_FRONT + 0.0025));
    // Captive rack screws
    for (const sy of [-0.013, 0.013]) {
      b.add(mShield, cyl(0.0032, 0.0032, 0.004, 10, earX + sx * 0.003, sy, Z_FRONT + 0.006, Math.PI / 2));
    }
    // Front mini pull handle on ear
    b.add(mEar, box(0.004, H * 0.52, 0.014, earX - sx * 0.004, 0, Z_FRONT + 0.011));
  }

  // Rear FRU Bay: Dual Hot-Swap PSUs (A-Red / B-Blue handles + C14 inlets + rear green LEDs) + Fan Trays
  b.add(mFace, box(W_BODY, H - 0.002, 0.008, 0, 0, Z_REAR - 0.004));
  const mPsuHandleA = b.mat('MAT_REAR_PSU_A', '#dc2626', 0.45, 0.32);
  const mPsuHandleB = b.mat('MAT_REAR_PSU_B', '#2563eb', 0.45, 0.32);
  const mRearLedOk = b.mat('MAT_REAR_LED_OK', '#00d930', 0.12, 0.22, { emissive: [0.0, 0.65, 0.14] });
  if (dualPsu) {
    [-0.155, 0.155].forEach((px, idx) => {
      b.add(mEar, box(0.098, H - 0.008, 0.012, px, 0, Z_REAR - 0.008));
      b.add(mDark, box(0.030, 0.019, 0.008, px - 0.022, 0, Z_REAR - 0.013)); // IEC C14 AC inlet
      b.add(mGold, box(0.014, 0.004, 0.006, px - 0.022, 0, Z_REAR - 0.014)); // C14 brass pins
      b.add(mShield, cyl(0.012, 0.012, 0.006, 12, px + 0.022, 0, Z_REAR - 0.013, Math.PI / 2)); // PSU fan grill
      b.add(idx === 0 ? mPsuHandleA : mPsuHandleB, box(0.034, 0.0055, 0.018, px, -0.011, Z_REAR - 0.018)); // A/B latch handle
      b.add(mRearLedOk, box(0.004, 0.004, 0.004, px + 0.038, 0.010, Z_REAR - 0.015)); // Rear PSU AC-OK green LED
    });
  }
  const fanSpan = dualPsu ? 0.18 : 0.34;
  for (let i = 0; i < fanCount; i++) {
    const fx = -fanSpan / 2 + ((i + 0.5) / fanCount) * fanSpan;
    const fw = (fanSpan / fanCount) - 0.005;
    b.add(mEar, box(fw, H - 0.009, 0.01, fx, 0, Z_REAR - 0.007));
    b.add(mDark, cyl(Math.min(0.013, fw * 0.38), Math.min(0.013, fw * 0.38), 0.006, 12, fx, 0.002, Z_REAR - 0.011, Math.PI / 2));
    b.add(mPsuFan, box(fw * 0.65, 0.004, 0.012, fx, -0.011, Z_REAR - 0.014));
    b.add(mRearLedOk, box(0.003, 0.003, 0.004, fx + fw * 0.34, 0.011, Z_REAR - 0.013)); // Rear fan module OK LED
  }

  // Status LEDs (animated by RackDeviceItem.tsx; Z_FRONT + 0.0158 sits cleanly in front of silkscreen overlay)
  const ledZ = Z_FRONT + 0.0158;
  if (omitLeftMgmtBlock) {
    // Horizontal top-left SYS / PSU / FAN micro-LEDs aligned 1:1 with H3C S6850 silkscreen sockets
    const topLedDefs = [
      { name: 'STATUS_LED_SYS', hex: '#00d930', x: -0.2075 },
      { name: 'STATUS_LED_PWR', hex: '#00c828', x: -0.1921 },
      { name: 'STATUS_LED_FAN', hex: '#00c828', x: -0.1766 },
    ];
    for (const l of topLedDefs) {
      const mLed = b.mat(`MAT_${l.name}`, l.hex, 0.1, 0.2, {
        emissive: hexToRgba(l.hex).slice(0, 3).map((v) => v * 0.85),
      });
      b.addNode(
        l.name,
        mLed,
        box(0.0034, 0.0034, 0.0024),
        [l.x, 0.0128, ledZ],
        { component_type: 'status_led' },
      );
    }
  } else {
    const ledDefs = [
      { name: 'STATUS_LED_PWR', hex: '#22c55e', y: 0.011 },
      { name: 'STATUS_LED_SYS', hex: '#10b981', y: 0.000 },
      { name: 'STATUS_LED_ALM', hex: '#334155', y: -0.011 },
    ];
    for (const l of ledDefs) {
      const mLed = b.mat(`MAT_${l.name}`, l.hex, 0.1, 0.2, {
        emissive: hexToRgba(l.hex).slice(0, 3).map((v) => v * 0.7),
      });
      b.addNode(
        l.name,
        mLed,
        box(0.0048, 0.0036, 0.0026),
        [-W_BODY / 2 + 0.016, l.y, ledZ],
        { component_type: 'status_led' },
      );
    }

    // Console + MGMT RJ45 stack on left management block
    b.add(mShield, box(0.016, 0.026, 0.006, -W_BODY / 2 + 0.034, 0, Z_FRONT + 0.0125));
    b.add(mDark, box(0.012, 0.009, 0.006, -W_BODY / 2 + 0.034, 0.006, Z_FRONT + 0.0132));
    b.add(mDark, box(0.012, 0.009, 0.006, -W_BODY / 2 + 0.034, -0.006, Z_FRONT + 0.0132));
  }

  return { H, W_BODY, Z_FRONT, mBody, mFace, mEar, mDark, mShield, mGold, mAccent };
}

function addPortBank(b, ctx, {
  startPort = 1,
  cols = 12,
  rows = 2,
  xStart = -0.15,
  xEnd = 0.12,
  kind = 'sfp', // 'rj45' | 'sfp' | 'qsfp'
}) {
  const { Z_FRONT, mDark, mShield, mGold } = ctx;
  const portW = kind === 'qsfp' ? 0.0185 : 0.0132;
  const portH = kind === 'qsfp' ? 0.0105 : 0.0096;
  const zShield = Z_FRONT + 0.0135;
  const zCavity = Z_FRONT + 0.0142;

  let portNum = startPort;
  for (let c = 0; c < cols; c++) {
    const t = cols === 1 ? 0.5 : c / (cols - 1);
    const x = xStart + t * (xEnd - xStart);
    for (let r = 0; r < rows; r++) {
      const y = rows === 1 ? 0 : (r === 0 ? 0.0072 : -0.0072);
      b.add(mShield, box(portW, portH, 0.005, x, y, zShield));
      b.add(mDark, box(portW - 0.0024, portH - 0.0022, 0.005, x, y, zCavity));
      if (kind === 'rj45') {
        b.add(mGold, box(portW - 0.005, 0.0014, 0.004, x, y + (r === 0 ? 0.0022 : -0.0022), zCavity + 0.0004));
      } else {
        // SFP / QSFP transceiver guide tongue
        b.add(mShield, box(portW - 0.004, 0.0012, 0.004, x, y, zCavity + 0.0003));
      }

      // Dedicated per-port LED node for live topology link illumination
      const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, {
        emissive: [0.02, 0.05, 0.08],
      });
      const ledY = rows === 1 ? (portH / 2 + 0.003) : (r === 0 ? y + portH / 2 + 0.0024 : y - portH / 2 - 0.0024);
      b.addNode(
        `PORT_LED_${portNum}`,
        ledMat,
        box(0.0034, 0.0020, 0.0022),
        [x, ledY, Z_FRONT + 0.0158],
        { component_type: 'port_led', port_index: portNum, connection_face: 'front' },
      );
      portNum += 1;
    }
  }
}

// ---------------------------------------------------------------------------
// 2. Device Family Builders
// ---------------------------------------------------------------------------
function buildH3cS6800() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#b8c2ce',
    faceHex: '#d4dce6',
    earHex: '#9aa5b4',
    accentHex: '#dc2626',
    dualPsu: true,
    fanCount: 5,
    fanHandleHex: '#e11d48',
    omitLeftMgmtBlock: true,
  });
  const mBezelFrame = b.mat('MAT_PORT_BANK_BEZEL', '#8f9cac', 0.84, 0.25);

  // Official H3C S6850 Series front panel geometry:
  // - Edge-to-edge brushed silver faceplate (no left console block)
  // - Top strip (y = +0.010..+0.021): H3C S6850 Series plate + hexagonal honeycomb vent grill
  // - 4 x 12-port SFP28 banks (6 cols x 2 rows = 48 ports, odd top y=+0.0044, even bottom y=-0.0084)
  // - Unobstructed center brushed-silver numbering strip between top & bottom rows (y = -0.0044..+0.0004)
  // - Right-side 8-port QSFP28 bank (4 cols x 2 rows = ports 49..56, odd top, even bottom)
  const sfpBankWidths = [0.076, 0.076, 0.076, 0.076];
  const sfpBankGap = 0.008;
  const topRowY = 0.0044;
  const botRowY = -0.0084;
  let bankLeft = -0.208;

  for (let bankIndex = 0; bankIndex < 4; bankIndex++) {
    const bw = sfpBankWidths[bankIndex];
    const bankCenterX = bankLeft + bw / 2;
    const cols = 6;
    const portW = 0.0114;
    const portH = 0.0074;

    // Separate top & bottom row EMI frames so the center silver numbering strip stays 100% unobstructed
    for (const rowY of [topRowY, botRowY]) {
      b.add(mBezelFrame, box(bw + 0.013, portH + 0.0018, 0.003, bankCenterX, rowY, ctx.Z_FRONT + 0.0132));
      b.add(ctx.mDark, box(bw + 0.010, portH + 0.0004, 0.0032, bankCenterX, rowY, ctx.Z_FRONT + 0.0136));
    }

    for (let col = 0; col < cols; col++) {
      const x = bankLeft + col * (bw / (cols - 1));
      for (let row = 0; row < 2; row++) {
        // Odd ports (1,3,5...) on top row; Even ports (2,4,6...) on bottom row
        const portNum = bankIndex * 12 + col * 2 + (row === 0 ? 1 : 2);
        const y = row === 0 ? topRowY : botRowY;

        b.add(ctx.mShield, box(portW, portH, 0.0042, x, y, ctx.Z_FRONT + 0.014));
        b.add(ctx.mDark, box(portW - 0.0018, portH - 0.0018, 0.0046, x, y, ctx.Z_FRONT + 0.0145));
        b.add(ctx.mShield, box(portW - 0.0032, 0.001, 0.004, x, y, ctx.Z_FRONT + 0.0148));

        const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, {
          emissive: [0.02, 0.05, 0.08],
        });
        // Micro link LED positioned cleanly in front of the center silver strip next to ▲/▼
        const ledY = row === 0 ? -0.0001 : -0.0039;
        b.addNode(
          `PORT_LED_${portNum}`,
          ledMat,
          box(0.0032, 0.0020, 0.0022),
          [x + (row === 0 ? -0.0028 : 0.0028), ledY, ctx.Z_FRONT + 0.0158],
          { component_type: 'port_led', port_index: portNum, connection_face: 'front' },
        );
      }
    }
    bankLeft += bw + sfpBankGap;
  }

  // Right-side 8-port QSFP28 bank (4 cols x 2 rows = ports 49..56)
  const qsfpLeft = 0.134;
  const qsfpWidth = 0.074;
  const qsfpCenterX = qsfpLeft + qsfpWidth / 2;
  const qsfpCols = 4;
  const qsfpW = 0.0182;
  const qsfpH = 0.0074;

  for (const rowY of [topRowY, botRowY]) {
    b.add(mBezelFrame, box(qsfpWidth + 0.020, qsfpH + 0.0018, 0.003, qsfpCenterX, rowY, ctx.Z_FRONT + 0.0132));
    b.add(ctx.mDark, box(qsfpWidth + 0.017, qsfpH + 0.0004, 0.0032, qsfpCenterX, rowY, ctx.Z_FRONT + 0.0136));
  }

  for (let col = 0; col < qsfpCols; col++) {
    const x = qsfpLeft + col * (qsfpWidth / (qsfpCols - 1));
    for (let row = 0; row < 2; row++) {
      const portNum = 49 + col * 2 + row; // 49,51,53,55 top; 50,52,54,56 bottom
      const y = row === 0 ? topRowY : botRowY;

      b.add(ctx.mShield, box(qsfpW, qsfpH, 0.0048, x, y, ctx.Z_FRONT + 0.0141));
      b.add(ctx.mDark, box(qsfpW - 0.0024, qsfpH - 0.0018, 0.0050, x, y, ctx.Z_FRONT + 0.0146));
      b.add(ctx.mGold, box(qsfpW - 0.005, 0.0012, 0.004, x, y, ctx.Z_FRONT + 0.0149));

      const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, {
        emissive: [0.02, 0.05, 0.08],
      });
      const ledY = row === 0 ? -0.0001 : -0.0039;
      b.addNode(
        `PORT_LED_${portNum}`,
        ledMat,
        box(0.0040, 0.0022, 0.0022),
        [x + (row === 0 ? -0.0042 : 0.0042), ledY, ctx.Z_FRONT + 0.0158],
        { component_type: 'port_led', port_index: portNum, connection_face: 'front' },
      );
    }
  }

  return b.toGlb();
}

function buildGenericSwitch48P() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#252f3d',
    faceHex: '#1e293b',
    accentHex: '#06b6d4',
    dualPsu: true,
    fanCount: 4,
    fanHandleHex: '#0284c7',
  });
  const blockStarts = [-0.164, -0.074, 0.016, 0.106];
  blockStarts.forEach((bx, idx) => {
    addPortBank(b, ctx, {
      startPort: idx * 12 + 1,
      cols: 6,
      rows: 2,
      xStart: bx,
      xEnd: bx + 0.072,
      kind: 'rj45',
    });
  });
  addPortBank(b, ctx, {
    startPort: 49,
    cols: 2,
    rows: 2,
    xStart: 0.188,
    xEnd: 0.205,
    kind: 'sfp',
  });
  return b.toGlb();
}

function buildGenericSwitch24P() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#273240',
    faceHex: '#1f2937',
    accentHex: '#0ea5e9',
    dualPsu: true,
    fanCount: 3,
    fanHandleHex: '#0ea5e9',
  });
  // Left louvered intake grill + 24x RJ45 + 4x SFP+ uplinks
  for (let i = 0; i < 6; i++) {
    b.add(ctx.mDark, box(0.068, 0.0024, 0.004, -0.115, -0.012 + i * 0.0048, ctx.Z_FRONT + 0.014));
  }
  addPortBank(b, ctx, { startPort: 1, cols: 6, rows: 2, xStart: -0.055, xEnd: 0.025, kind: 'rj45' });
  addPortBank(b, ctx, { startPort: 13, cols: 6, rows: 2, xStart: 0.045, xEnd: 0.125, kind: 'rj45' });
  addPortBank(b, ctx, { startPort: 25, cols: 2, rows: 2, xStart: 0.165, xEnd: 0.192, kind: 'sfp' });
  return b.toGlb();
}

function buildGenericSwitchSfp() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#1e293b',
    faceHex: '#151f2e',
    accentHex: '#38bdf8',
    dualPsu: true,
    fanCount: 4,
    fanHandleHex: '#38bdf8',
  });
  addPortBank(b, ctx, { startPort: 1, cols: 6, rows: 2, xStart: -0.14, xEnd: -0.055, kind: 'sfp' });
  addPortBank(b, ctx, { startPort: 13, cols: 6, rows: 2, xStart: -0.03, xEnd: 0.055, kind: 'sfp' });
  addPortBank(b, ctx, { startPort: 25, cols: 4, rows: 2, xStart: 0.10, xEnd: 0.185, kind: 'qsfp' });
  return b.toGlb();
}

function buildFirewall1U() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#1b222d',
    faceHex: '#151b26',
    earHex: '#8d99a8',
    accentHex: '#dc2626', // Authentic H3C SecPath crimson left trim
    dualPsu: true,
    fanCount: 4,
    fanHandleHex: '#dc2626',
  });
  // Clean H3C SecPath F1090 front bay layout (no floating red bar overlapping port labels):
  // MGMT / HA dual copper ports (4)
  addPortBank(b, ctx, { startPort: 1, cols: 2, rows: 2, xStart: -0.145, xEnd: -0.125, kind: 'rj45' });
  // 12x GE Security Zone Copper Ports (5..16)
  addPortBank(b, ctx, { startPort: 5, cols: 6, rows: 2, xStart: -0.085, xEnd: -0.005, kind: 'rj45' });
  // 8x 10G SFP+ Threat Inspection Fiber Ports (17..24)
  addPortBank(b, ctx, { startPort: 17, cols: 4, rows: 2, xStart: 0.025, xEnd: 0.082, kind: 'sfp' });
  // Right Modular FIC-NGFW Expansion Subcard Bay with brushed plate, cooling vents & captive thumbscrews
  const mSubcard = b.mat('MAT_NGFW_SUBCARD', '#273142', 0.78, 0.3);
  b.add(mSubcard, box(0.092, 0.026, 0.0045, 0.156, 0, ctx.Z_FRONT + 0.0138));
  for (let i = 0; i < 4; i++) {
    b.add(ctx.mDark, box(0.052, 0.0022, 0.004, 0.156, -0.006 + i * 0.004, ctx.Z_FRONT + 0.0144));
  }
  b.add(ctx.mShield, cyl(0.0028, 0.0028, 0.0045, 10, 0.116, 0, ctx.Z_FRONT + 0.0156, Math.PI / 2));
  b.add(ctx.mShield, cyl(0.0028, 0.0028, 0.0045, 10, 0.196, 0, ctx.Z_FRONT + 0.0156, Math.PI / 2));
  return b.toGlb();
}

function buildWirelessAc1U() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#253040',
    faceHex: '#1b2636',
    earHex: '#94a3b8',
    accentHex: '#0ea5e9', // Wireless AC cyan-blue trim
    dualPsu: true,
    fanCount: 3,
    fanHandleHex: '#06b6d4',
  });
  // Left louvered metallic cooling intake bay + exact H3C WX5540H 28-port layout (24x GE RJ45 + 4x 10G SFP+)
  const mTrim = b.mat('MAT_AC_BRUSHED_TRIM', '#475569', 0.82, 0.28);
  b.add(mTrim, box(0.088, 0.026, 0.0035, -0.112, 0, ctx.Z_FRONT + 0.0136));
  for (let i = 0; i < 5; i++) {
    b.add(ctx.mDark, box(0.072, 0.0022, 0.004, -0.112, -0.008 + i * 0.0042, ctx.Z_FRONT + 0.0144));
  }
  // Ports 0..11 (12x GE), 12..23 (12x GE), 24..27 (4x 10G SFP+) -> 28 real physical cages!
  addPortBank(b, ctx, { startPort: 0, cols: 6, rows: 2, xStart: -0.052, xEnd: 0.024, kind: 'rj45' });
  addPortBank(b, ctx, { startPort: 12, cols: 6, rows: 2, xStart: 0.036, xEnd: 0.112, kind: 'rj45' });
  addPortBank(b, ctx, { startPort: 24, cols: 2, rows: 2, xStart: 0.145, xEnd: 0.175, kind: 'sfp' });
  return b.toGlb();
}

function buildPatchPanel24P() {
  const b = new BatchBuilder();
  const mFrame = b.mat('MAT_PP_FRAME', '#181f28', 0.65, 0.42);
  const mDark = b.mat('MAT_PP_DARK', '#05080d', 0.2, 0.8);
  const mShield = b.mat('MAT_PP_KEYSTONE', '#64748b', 0.78, 0.3);
  const mLabel = b.mat('MAT_PP_LABEL', '#e2e8f0', 0.1, 0.6);

  const H = U_M - 0.001;
  const Z_FRONT = 0.42;
  // Shallow passive keystone frame + rear cable strain-relief bar (no fake chassis box!)
  b.add(mFrame, box(0.4826, H, 0.012, 0, 0, Z_FRONT + 0.004));
  b.add(mFrame, box(0.442, 0.012, 0.008, 0, -0.012, Z_FRONT - 0.08));
  for (const sx of [-1, 1]) {
    b.add(mFrame, box(0.008, 0.01, 0.09, sx * 0.215, -0.012, Z_FRONT - 0.038));
  }
  for (let i = 0; i < 24; i++) {
    const group = Math.floor(i / 6);
    const colInGroup = i % 6;
    const x = -0.192 + group * 0.102 + colInGroup * 0.0145;
    b.add(mShield, box(0.0125, 0.014, 0.008, x, -0.003, Z_FRONT + 0.009));
    b.add(mDark, box(0.0095, 0.010, 0.006, x, -0.003, Z_FRONT + 0.011));
    b.add(mLabel, box(0.0115, 0.005, 0.002, x, 0.010, Z_FRONT + 0.0105));
  }
  return b.toGlb();
}

function buildServer1U() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#2a3340',
    faceHex: '#171e29',
    earHex: '#64748b',
    accentHex: '#10b981',
    dualPsu: true,
    fanCount: 6,
    fanHandleHex: '#10b981',
  });
  const mLatch = b.mat('MAT_NVME_LATCH', '#0ea5e9', 0.5, 0.3);
  // 8 x 2.5" NVMe hot-swap drive caddies across front bezel
  for (let i = 0; i < 8; i++) {
    const x = -0.145 + i * 0.044;
    b.add(ctx.mEar, box(0.040, 0.028, 0.006, x, 0, ctx.Z_FRONT + 0.0135));
    b.add(ctx.mDark, box(0.030, 0.018, 0.004, x - 0.003, 0, ctx.Z_FRONT + 0.0155));
    b.add(mLatch, box(0.005, 0.022, 0.005, x + 0.015, 0, ctx.Z_FRONT + 0.016));
  }
  return b.toGlb();
}

function buildServer2U() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    heightU: 2,
    bodyHex: '#252f3d',
    faceHex: '#141c28',
    earHex: '#64748b',
    accentHex: '#0ea5e9',
    dualPsu: true,
    fanCount: 6,
    fanHandleHex: '#0ea5e9',
    omitLeftMgmtBlock: true,
  });
  const mLatch = b.mat('MAT_LFF_LATCH', '#0ea5e9', 0.5, 0.3);
  const mLed = b.mat('MAT_DRIVE_LED', '#00d930', 0.12, 0.2, { emissive: [0.0, 0.55, 0.12] });
  // 12 x 3.5" LFF hot-swap drive sleds (4 cols x 3 rows)
  for (let row = 0; row < 3; row++) {
    const y = 0.026 - row * 0.026;
    for (let col = 0; col < 4; col++) {
      const x = -0.155 + col * 0.103;
      b.add(ctx.mEar, box(0.095, 0.022, 0.006, x, y, ctx.Z_FRONT + 0.0135));
      b.add(ctx.mDark, box(0.072, 0.014, 0.004, x - 0.006, y, ctx.Z_FRONT + 0.0155));
      b.add(mLatch, box(0.008, 0.018, 0.006, x + 0.038, y, ctx.Z_FRONT + 0.016));
      b.add(mLed, box(0.003, 0.003, 0.004, x + 0.028, y + 0.005, ctx.Z_FRONT + 0.0165));
    }
  }
  return b.toGlb();
}

// ---------------------------------------------------------------------------
// 3. Vendor-Authentic 1U Box Switches (Cisco / Huawei / Ruijie / H3C Campus)
// ---------------------------------------------------------------------------
function buildCiscoCatalyst9300(portCount = 48) {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#252c36',
    faceHex: '#1b222c',
    earHex: '#8d99a8',
    accentHex: '#00bceb', // Cisco signature cyan-teal Catalyst accent
    dualPsu: true,
    fanCount: 3,
    fanHandleHex: '#00bceb',
  });
  // Cisco blue Beacon (UID) LED + MODE button on far left
  const mBeacon = b.mat('MAT_CISCO_BEACON', '#0ea5e9', 0.1, 0.2, { emissive: [0.02, 0.35, 0.6] });
  b.add(mBeacon, cyl(0.0028, 0.0028, 0.003, 10, -0.194, 0.014, ctx.Z_FRONT + 0.0156, Math.PI / 2));

  if (portCount <= 24) {
    // 24 x GE/mGig RJ45 (2 x 12-port blocks) + left louvered intake
    for (let i = 0; i < 5; i++) {
      b.add(ctx.mDark, box(0.075, 0.0024, 0.004, -0.125, -0.010 + i * 0.005, ctx.Z_FRONT + 0.014));
    }
    addPortBank(b, ctx, { startPort: 1, cols: 6, rows: 2, xStart: -0.062, xEnd: 0.016, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 13, cols: 6, rows: 2, xStart: 0.034, xEnd: 0.112, kind: 'rj45' });
  } else {
    // 48 x GE/mGig RJ45 (4 x 12-port blocks)
    addPortBank(b, ctx, { startPort: 1, cols: 6, rows: 2, xStart: -0.168, xEnd: -0.100, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 13, cols: 6, rows: 2, xStart: -0.088, xEnd: -0.020, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 25, cols: 6, rows: 2, xStart: -0.008, xEnd: 0.060, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 37, cols: 6, rows: 2, xStart: 0.072, xEnd: 0.140, kind: 'rj45' });
  }

  // Right-side hot-swappable Network Module Slot (NM-8X: 8x 10G/25G SFP+) with retention jackscrew
  const mSlot = b.mat('MAT_NM_MODULE_BAY', '#334155', 0.78, 0.28);
  b.add(mSlot, box(0.068, 0.032, 0.004, 0.180, 0, ctx.Z_FRONT + 0.0132));
  b.add(ctx.mShield, cyl(0.0028, 0.0028, 0.005, 10, 0.146, 0.012, ctx.Z_FRONT + 0.0156, Math.PI / 2));
  addPortBank(b, ctx, {
    startPort: portCount <= 24 ? 25 : 49,
    cols: 4,
    rows: 2,
    xStart: portCount <= 24 ? 0.142 : 0.158,
    xEnd: 0.206,
    kind: 'sfp',
  });
  return b.toGlb();
}

function buildCiscoNexus93180() {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#1d2430',
    faceHex: '#151c27',
    earHex: '#7d8a9a',
    accentHex: '#00bceb', // Cisco Nexus teal-cyan
    dualPsu: true,
    fanCount: 4,
    fanHandleHex: '#00bceb',
    omitLeftMgmtBlock: true,
  });
  // Nexus left teal bezel bar + 4x12 SFP28 + 6x QSFP28
  const mBezelFrame = b.mat('MAT_NEXUS_BEZEL', '#475569', 0.82, 0.28);
  const sfpBankWidths = [0.076, 0.076, 0.076, 0.076];
  const sfpBankGap = 0.008;
  const topRowY = 0.0044;
  const botRowY = -0.0084;
  let bankLeft = -0.208;

  for (let bankIndex = 0; bankIndex < 4; bankIndex++) {
    const bw = sfpBankWidths[bankIndex];
    const bankCenterX = bankLeft + bw / 2;
    for (const rowY of [topRowY, botRowY]) {
      b.add(mBezelFrame, box(bw + 0.012, 0.0092, 0.003, bankCenterX, rowY, ctx.Z_FRONT + 0.0132));
      b.add(ctx.mDark, box(bw + 0.009, 0.0078, 0.0032, bankCenterX, rowY, ctx.Z_FRONT + 0.0136));
    }
    for (let col = 0; col < 6; col++) {
      const x = bankLeft + col * (bw / 5);
      for (let row = 0; row < 2; row++) {
        const portNum = bankIndex * 12 + col * 2 + (row === 0 ? 1 : 2);
        const y = row === 0 ? topRowY : botRowY;
        b.add(ctx.mShield, box(0.0114, 0.0074, 0.0042, x, y, ctx.Z_FRONT + 0.014));
        b.add(ctx.mDark, box(0.0096, 0.0056, 0.0046, x, y, ctx.Z_FRONT + 0.0145));
        const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, { emissive: [0.01, 0.03, 0.04] });
        b.addNode(`PORT_LED_${portNum}`, ledMat, box(0.003, 0.0018, 0.0022), [x + (row === 0 ? -0.0028 : 0.0028), row === 0 ? -0.0001 : -0.0039, ctx.Z_FRONT + 0.0158], { component_type: 'port_led', port_index: portNum, connection_face: 'front' });
      }
    }
    bankLeft += bw + sfpBankGap;
  }

  // Right 6x 100G QSFP28 (3 cols x 2 rows)
  const qsfpLeft = 0.138;
  const qsfpWidth = 0.068;
  for (const rowY of [topRowY, botRowY]) {
    b.add(mBezelFrame, box(qsfpWidth + 0.022, 0.0092, 0.003, qsfpLeft + qsfpWidth / 2, rowY, ctx.Z_FRONT + 0.0132));
  }
  for (let col = 0; col < 3; col++) {
    const x = qsfpLeft + col * (qsfpWidth / 2);
    for (let row = 0; row < 2; row++) {
      const portNum = 49 + col * 2 + row;
      const y = row === 0 ? topRowY : botRowY;
      b.add(ctx.mShield, box(0.019, 0.0074, 0.0048, x, y, ctx.Z_FRONT + 0.0141));
      b.add(ctx.mDark, box(0.0165, 0.0056, 0.005, x, y, ctx.Z_FRONT + 0.0146));
      b.add(ctx.mGold, box(0.013, 0.0012, 0.004, x, y, ctx.Z_FRONT + 0.0149));
      const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, { emissive: [0.01, 0.03, 0.04] });
      b.addNode(`PORT_LED_${portNum}`, ledMat, box(0.0038, 0.002, 0.0022), [x + (row === 0 ? -0.004 : 0.004), row === 0 ? -0.0001 : -0.0039, ctx.Z_FRONT + 0.0158], { component_type: 'port_led', port_index: portNum, connection_face: 'front' });
    }
  }
  return b.toGlb();
}

function buildHuaweiBox1U({ optical = true, copper48 = false, dcStyle = true }) {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: dcStyle ? '#9aa5b4' : '#313a48',
    faceHex: dcStyle ? '#c4cdd8' : '#232b38',
    earHex: '#8d99a8',
    accentHex: '#e11d48', // Huawei signature crimson
    dualPsu: true,
    fanCount: 4,
    fanHandleHex: '#e11d48',
    omitLeftMgmtBlock: dcStyle,
  });

  if (dcStyle) {
    // CloudEngine CE6881/CE6885/S6730: 4x12 SFP28 + 4x2 QSFP28
    const mBezelFrame = b.mat('MAT_HW_BEZEL', '#64748b', 0.82, 0.26);
    const topRowY = 0.0044;
    const botRowY = -0.0084;
    let bankLeft = -0.208;
    for (let bankIndex = 0; bankIndex < 4; bankIndex++) {
      const bw = 0.076;
      for (const rowY of [topRowY, botRowY]) {
        b.add(mBezelFrame, box(bw + 0.012, 0.0092, 0.003, bankLeft + bw / 2, rowY, ctx.Z_FRONT + 0.0132));
        b.add(ctx.mDark, box(bw + 0.009, 0.0078, 0.0032, bankLeft + bw / 2, rowY, ctx.Z_FRONT + 0.0136));
      }
      for (let col = 0; col < 6; col++) {
        const x = bankLeft + col * (bw / 5);
        for (let row = 0; row < 2; row++) {
          const portNum = bankIndex * 12 + col * 2 + (row === 0 ? 1 : 2);
          const y = row === 0 ? topRowY : botRowY;
          b.add(ctx.mShield, box(0.0114, 0.0074, 0.0042, x, y, ctx.Z_FRONT + 0.014));
          b.add(ctx.mDark, box(0.0096, 0.0056, 0.0046, x, y, ctx.Z_FRONT + 0.0145));
          const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, { emissive: [0.01, 0.03, 0.04] });
          b.addNode(`PORT_LED_${portNum}`, ledMat, box(0.003, 0.0018, 0.0022), [x + (row === 0 ? -0.0028 : 0.0028), row === 0 ? -0.0001 : -0.0039, ctx.Z_FRONT + 0.0158], { component_type: 'port_led', port_index: portNum, connection_face: 'front' });
        }
      }
      bankLeft += bw + 0.008;
    }
    const qsfpLeft = 0.134;
    const qsfpWidth = 0.074;
    for (const rowY of [topRowY, botRowY]) {
      b.add(mBezelFrame, box(qsfpWidth + 0.020, 0.0092, 0.003, qsfpLeft + qsfpWidth / 2, rowY, ctx.Z_FRONT + 0.0132));
    }
    for (let col = 0; col < 4; col++) {
      const x = qsfpLeft + col * (qsfpWidth / 3);
      for (let row = 0; row < 2; row++) {
        const portNum = 49 + col * 2 + row;
        const y = row === 0 ? topRowY : botRowY;
        b.add(ctx.mShield, box(0.0182, 0.0074, 0.0048, x, y, ctx.Z_FRONT + 0.0141));
        b.add(ctx.mDark, box(0.0158, 0.0056, 0.005, x, y, ctx.Z_FRONT + 0.0146));
        b.add(ctx.mGold, box(0.013, 0.0012, 0.004, x, y, ctx.Z_FRONT + 0.0149));
        const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, { emissive: [0.01, 0.03, 0.04] });
        b.addNode(`PORT_LED_${portNum}`, ledMat, box(0.0038, 0.002, 0.0022), [x + (row === 0 ? -0.004 : 0.004), row === 0 ? -0.0001 : -0.0039, ctx.Z_FRONT + 0.0158], { component_type: 'port_led', port_index: portNum, connection_face: 'front' });
      }
    }
  } else {
    // Huawei S5755-H Campus Switch: 48x GE RJ45 + right modular 10G/25G uplink slot
    const kind = copper48 ? 'rj45' : optical ? 'sfp' : 'rj45';
    addPortBank(b, ctx, { startPort: 1, cols: 6, rows: 2, xStart: -0.168, xEnd: -0.100, kind });
    addPortBank(b, ctx, { startPort: 13, cols: 6, rows: 2, xStart: -0.088, xEnd: -0.020, kind });
    addPortBank(b, ctx, { startPort: 25, cols: 6, rows: 2, xStart: -0.008, xEnd: 0.060, kind });
    addPortBank(b, ctx, { startPort: 37, cols: 6, rows: 2, xStart: 0.072, xEnd: 0.140, kind });
    addPortBank(b, ctx, { startPort: 49, cols: 4, rows: 2, xStart: 0.158, xEnd: 0.208, kind: 'sfp' });
  }
  return b.toGlb();
}

function buildRuijieBox1U({ dcStyle = false }) {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#283242',
    faceHex: dcStyle ? '#1e2838' : '#263142',
    earHex: '#8d99a8',
    accentHex: '#2563eb', // Ruijie signature cobalt blue
    dualPsu: true,
    fanCount: 4,
    fanHandleHex: '#2563eb',
    omitLeftMgmtBlock: dcStyle,
  });
  if (dcStyle) {
    // Ruijie RG-S6510-48VS8CQ: 4x12 SFP28 + 4x2 QSFP28
    const mBezelFrame = b.mat('MAT_RJ_BEZEL', '#475569', 0.82, 0.26);
    const topRowY = 0.0044;
    const botRowY = -0.0084;
    let bankLeft = -0.208;
    for (let bankIndex = 0; bankIndex < 4; bankIndex++) {
      const bw = 0.076;
      for (const rowY of [topRowY, botRowY]) {
        b.add(mBezelFrame, box(bw + 0.012, 0.0092, 0.003, bankLeft + bw / 2, rowY, ctx.Z_FRONT + 0.0132));
        b.add(ctx.mDark, box(bw + 0.009, 0.0078, 0.0032, bankLeft + bw / 2, rowY, ctx.Z_FRONT + 0.0136));
      }
      for (let col = 0; col < 6; col++) {
        const x = bankLeft + col * (bw / 5);
        for (let row = 0; row < 2; row++) {
          const portNum = bankIndex * 12 + col * 2 + (row === 0 ? 1 : 2);
          const y = row === 0 ? topRowY : botRowY;
          b.add(ctx.mShield, box(0.0114, 0.0074, 0.0042, x, y, ctx.Z_FRONT + 0.014));
          b.add(ctx.mDark, box(0.0096, 0.0056, 0.0046, x, y, ctx.Z_FRONT + 0.0145));
          const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, { emissive: [0.01, 0.03, 0.04] });
          b.addNode(`PORT_LED_${portNum}`, ledMat, box(0.003, 0.0018, 0.0022), [x + (row === 0 ? -0.0028 : 0.0028), row === 0 ? -0.0001 : -0.0039, ctx.Z_FRONT + 0.0158], { component_type: 'port_led', port_index: portNum, connection_face: 'front' });
        }
      }
      bankLeft += bw + 0.008;
    }
    const qsfpLeft = 0.134;
    const qsfpWidth = 0.074;
    for (let col = 0; col < 4; col++) {
      const x = qsfpLeft + col * (qsfpWidth / 3);
      for (let row = 0; row < 2; row++) {
        const portNum = 49 + col * 2 + row;
        const y = row === 0 ? topRowY : botRowY;
        b.add(ctx.mShield, box(0.0182, 0.0074, 0.0048, x, y, ctx.Z_FRONT + 0.0141));
        b.add(ctx.mDark, box(0.0158, 0.0056, 0.005, x, y, ctx.Z_FRONT + 0.0146));
        b.add(ctx.mGold, box(0.013, 0.0012, 0.004, x, y, ctx.Z_FRONT + 0.0149));
        const ledMat = b.mat(`MAT_LED_PORT_${portNum}`, '#1e293b', 0.1, 0.25, { emissive: [0.01, 0.03, 0.04] });
        b.addNode(`PORT_LED_${portNum}`, ledMat, box(0.0038, 0.002, 0.0022), [x + (row === 0 ? -0.004 : 0.004), row === 0 ? -0.0001 : -0.0039, ctx.Z_FRONT + 0.0158], { component_type: 'port_led', port_index: portNum, connection_face: 'front' });
      }
    }
  } else {
    // Ruijie RG-S6120 / RG-S5750 Campus 48p + 4x 10G/25G uplink
    addPortBank(b, ctx, { startPort: 1, cols: 6, rows: 2, xStart: -0.168, xEnd: -0.100, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 13, cols: 6, rows: 2, xStart: -0.088, xEnd: -0.020, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 25, cols: 6, rows: 2, xStart: -0.008, xEnd: 0.060, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 37, cols: 6, rows: 2, xStart: 0.072, xEnd: 0.140, kind: 'rj45' });
    addPortBank(b, ctx, { startPort: 49, cols: 4, rows: 2, xStart: 0.158, xEnd: 0.208, kind: 'sfp' });
  }
  return b.toGlb();
}

function buildH3cCampus1U({ optical = false }) {
  const b = new BatchBuilder();
  const ctx = createHardwareChassis(b, {
    bodyHex: '#b8c2ce',
    faceHex: '#d4dce6',
    earHex: '#9aa5b4',
    accentHex: '#dc2626',
    dualPsu: true,
    fanCount: 3,
    fanHandleHex: '#dc2626',
  });
  const kind = optical ? 'sfp' : 'rj45';
  addPortBank(b, ctx, { startPort: 1, cols: 6, rows: 2, xStart: -0.168, xEnd: -0.100, kind });
  addPortBank(b, ctx, { startPort: 13, cols: 6, rows: 2, xStart: -0.088, xEnd: -0.020, kind });
  addPortBank(b, ctx, { startPort: 25, cols: 6, rows: 2, xStart: -0.008, xEnd: 0.060, kind });
  addPortBank(b, ctx, { startPort: 37, cols: 6, rows: 2, xStart: 0.072, xEnd: 0.140, kind });
  addPortBank(b, ctx, { startPort: 49, cols: 4, rows: 2, xStart: 0.158, xEnd: 0.208, kind: 'sfp' });
  return b.toGlb();
}

// ---------------------------------------------------------------------------
// 4. Modular Core Chassis Switches (Slot-Driven 8U / 10U: MPU + LPU + Power Shelf)
// ---------------------------------------------------------------------------
function buildModularChassis({
  heightU = 8,
  bodyHex = '#232b36',
  faceHex = '#19212c',
  earHex = '#7c8898',
  accentHex = '#00bceb',
  leverHex = '#0ea5e9',
  slotTypes = ['mpu', 'mpu', 'lpu_sfp', 'lpu_sfp', 'lpu_qsfp', 'lpu_qsfp'],
}) {
  const b = new BatchBuilder();
  const mBody = b.mat('MAT_CHASSIS_BODY', bodyHex, 0.65, 0.42);
  const mFace = b.mat('MAT_FACEPLATE', faceHex, 0.72, 0.34);
  const mEar = b.mat('MAT_RACK_EAR', earHex, 0.82, 0.28);
  const mCard = b.mat('MAT_SLOT_CARD', '#2a3444', 0.76, 0.3);
  const mDark = b.mat('MAT_CAVITY_DARK', '#060a10', 0.25, 0.75);
  const mShield = b.mat('MAT_PORT_SHIELD', '#94a3b8', 0.88, 0.22);
  const mLever = b.mat('MAT_EJECTOR_LEVER', leverHex, 0.5, 0.32);
  const mAccent = b.mat('MAT_BRAND_ACCENT', accentHex, 0.4, 0.3, { emissive: hexToRgba(accentHex).slice(0, 3).map(v => v * 0.28) });
  const mLedOk = b.mat('MAT_CHASSIS_LED_OK', '#00d930', 0.12, 0.2, { emissive: [0.0, 0.65, 0.14] });

  const H = heightU * U_M - 0.002;
  const W_BODY = 0.440;
  const W_EARS = 0.4826;
  const Z_FRONT = 0.42;
  const Z_REAR = -0.42;
  const D = Z_FRONT - Z_REAR;

  // Main multi-U industrial steel chassis enclosure + full-height mounting ears
  b.add(mBody, box(W_BODY, H, D, 0, 0, 0));
  b.add(mFace, box(W_BODY + 0.002, H - 0.002, 0.014, 0, 0, Z_FRONT + 0.007));
  b.add(mAccent, box(W_BODY - 0.02, 0.005, 0.004, 0, H / 2 - 0.009, Z_FRONT + 0.0145));

  for (const sx of [-1, 1]) {
    const earW = (W_EARS - W_BODY) / 2;
    const earX = sx * (W_BODY / 2 + earW / 2);
    b.add(mEar, box(earW, H - 0.002, 0.006, earX, 0, Z_FRONT + 0.003));
    for (let u = 0; u < heightU; u++) {
      const sy = -H / 2 + (u + 0.5) * U_M;
      b.add(mShield, cyl(0.0032, 0.0032, 0.004, 10, earX + sx * 0.003, sy, Z_FRONT + 0.0065, Math.PI / 2));
    }
  }

  // Horizontal Card Cage (top 80% of chassis) + Bottom 4-Bay Power Shelf (bottom 16%)
  const powerShelfH = H * 0.14;
  const powerShelfY = -H / 2 + powerShelfH / 2 + 0.010;
  const cardZoneTop = H / 2 - 0.020;
  const cardZoneBot = powerShelfY + powerShelfH / 2 + 0.012;
  const slotPitch = (cardZoneTop - cardZoneBot) / slotTypes.length;

  slotTypes.forEach((slotKind, idx) => {
    const slotY = cardZoneTop - (idx + 0.5) * slotPitch;
    const cardH = Math.max(0.024, slotPitch - 0.005);

    // Individual hot-swap line card / MPU faceplate + left/right ejector levers
    b.add(mCard, box(0.418, cardH, 0.008, 0, slotY, Z_FRONT + 0.014));
    b.add(mDark, box(0.422, 0.002, 0.006, 0, slotY - cardH / 2 - 0.001, Z_FRONT + 0.0145));
    for (const sx of [-1, 1]) {
      b.add(mLever, box(0.014, cardH * 0.72, 0.014, sx * 0.204, slotY, Z_FRONT + 0.019));
      b.add(mShield, cyl(0.0028, 0.0028, 0.006, 8, sx * 0.192, slotY, Z_FRONT + 0.019, Math.PI / 2));
    }

    // Per-slot status LED node (live animated!)
    const ledName = slotKind === 'mpu'
      ? (idx === 0 ? 'STATUS_LED_SYS' : 'STATUS_LED_PWR')
      : `STATUS_LED_FAN`;
    const mSlotLed = b.mat(`MAT_SLOT_LED_${idx + 1}`, '#00d930', 0.12, 0.2, { emissive: [0.0, 0.65, 0.14] });
    b.addNode(ledName, mSlotLed, box(0.004, 0.004, 0.004), [-0.180, slotY + cardH * 0.18, Z_FRONT + 0.019], { component_type: 'status_led' });

    if (slotKind === 'mpu') {
      // MPU / Supervisor Engine: Console + MGMT + USB + Clock/Sync ports + protective grille
      for (let i = 0; i < 4; i++) {
        const px = -0.145 + i * 0.024;
        b.add(mShield, box(0.015, 0.012, 0.006, px, slotY, Z_FRONT + 0.017));
        b.add(mDark, box(0.011, 0.008, 0.006, px, slotY, Z_FRONT + 0.018));
      }
      for (let i = 0; i < 8; i++) {
        b.add(mDark, box(0.018, cardH * 0.55, 0.004, -0.02 + i * 0.024, slotY, Z_FRONT + 0.017));
      }
    } else if (slotKind === 'lpu_qsfp') {
      // High-density 36-port 100G/400G QSFP28 Core Line Card (18 cols x 2 rows)
      for (let c = 0; c < 18; c++) {
        const px = -0.165 + (c / 17) * 0.340;
        for (const ry of [cardH * 0.22, -cardH * 0.22]) {
          b.add(mShield, box(0.016, cardH * 0.34, 0.005, px, slotY + ry, Z_FRONT + 0.017));
          b.add(mDark, box(0.013, cardH * 0.24, 0.005, px, slotY + ry, Z_FRONT + 0.018));
        }
      }
    } else {
      // High-density 48-port SFP28 or GE RJ45 Line Card (24 cols x 2 rows in 4 banks)
      for (let bank = 0; bank < 4; bank++) {
        const bStart = -0.166 + bank * 0.088;
        for (let c = 0; c < 6; c++) {
          const px = bStart + c * 0.0132;
          for (const ry of [cardH * 0.22, -cardH * 0.22]) {
            b.add(mShield, box(0.0108, cardH * 0.34, 0.005, px, slotY + ry, Z_FRONT + 0.017));
            b.add(mDark, box(0.0088, cardH * 0.24, 0.005, px, slotY + ry, Z_FRONT + 0.018));
          }
        }
      }
    }
  });

  // Bottom Modular Power Shelf: 4 x 3000W/3200W hot-swap power supplies
  const mPsuA = b.mat('MAT_SHELF_PSU_A', '#dc2626', 0.45, 0.32);
  const mPsuB = b.mat('MAT_SHELF_PSU_B', '#2563eb', 0.45, 0.32);
  for (let p = 0; p < 4; p++) {
    const px = -0.156 + p * 0.104;
    b.add(mEar, box(0.098, powerShelfH, 0.012, px, powerShelfY, Z_FRONT + 0.015));
    b.add(mDark, box(0.044, powerShelfH * 0.56, 0.008, px - 0.018, powerShelfY, Z_FRONT + 0.019));
    b.add(p < 2 ? mPsuA : mPsuB, box(0.018, powerShelfH * 0.62, 0.016, px + 0.032, powerShelfY, Z_FRONT + 0.022));
    b.add(mLedOk, box(0.005, 0.005, 0.004, px + 0.014, powerShelfY + powerShelfH * 0.25, Z_FRONT + 0.022));
  }

  // Rear Orthogonal Fan Trays & Switch Fabric Modules
  b.add(mFace, box(W_BODY, H - 0.004, 0.01, 0, 0, Z_REAR - 0.005));
  for (let row = 0; row < 2; row++) {
    const fy = (row === 0 ? 1 : -1) * (H * 0.22);
    for (let col = 0; col < 4; col++) {
      const fx = -0.15 + col * 0.10;
      b.add(mEar, box(0.092, H * 0.38, 0.014, fx, fy, Z_REAR - 0.010));
      b.add(mDark, cyl(0.036, 0.036, 0.01, 16, fx, fy, Z_REAR - 0.015, Math.PI / 2));
      b.add(mLedOk, box(0.005, 0.005, 0.005, fx + 0.036, fy + H * 0.14, Z_REAR - 0.018));
    }
  }

  return b.toGlb();
}

// ---------------------------------------------------------------------------
// 5. Rack-Mount Online UPS (2U & 3U: Battery Honeycomb Grille + LCD Console + Rear Outlets)
// ---------------------------------------------------------------------------
function buildRackUps(heightU = 2) {
  const b = new BatchBuilder();
  const mBody = b.mat('MAT_UPS_BODY', '#1b2029', 0.62, 0.44);
  const mBezel = b.mat('MAT_UPS_BEZEL', '#11161f', 0.52, 0.36);
  const mEar = b.mat('MAT_UPS_EAR', '#526072', 0.82, 0.28);
  const mDark = b.mat('MAT_UPS_DARK', '#05080d', 0.25, 0.78);
  const mLcdGlass = b.mat('MAT_UPS_LCD_GLOW', '#0284c7', 0.15, 0.2, { emissive: [0.04, 0.42, 0.72] });
  const mBtn = b.mat('MAT_UPS_BUTTON', '#64748b', 0.6, 0.35);
  const mRed = b.mat('MAT_UPS_BREAKER', '#dc2626', 0.4, 0.35);
  const mSilver = b.mat('MAT_UPS_CHROME', '#94a3b8', 0.88, 0.22);

  const H = heightU * U_M - 0.0015;
  const W_BODY = 0.440;
  const W_EARS = 0.4826;
  const Z_FRONT = 0.42;
  const Z_REAR = -0.42;
  const D = Z_FRONT - Z_REAR;

  // Heavy steel UPS chassis + contoured front bezel + mounting ears
  b.add(mBody, box(W_BODY, H, D, 0, 0, 0));
  b.add(mBezel, box(W_BODY + 0.004, H - 0.002, 0.018, 0, 0, Z_FRONT + 0.009));

  for (const sx of [-1, 1]) {
    const earW = (W_EARS - W_BODY) / 2;
    const earX = sx * (W_BODY / 2 + earW / 2);
    b.add(mEar, box(earW, H - 0.002, 0.006, earX, 0, Z_FRONT + 0.003));
    for (let u = 0; u < heightU; u++) {
      const sy = -H / 2 + (u + 0.5) * U_M;
      b.add(mSilver, cyl(0.0032, 0.0032, 0.004, 10, earX + sx * 0.003, sy, Z_FRONT + 0.0065, Math.PI / 2));
    }
  }

  // Left Removable Battery-Pack Honeycomb Vent Panel (60% of front width)
  const ventRows = heightU === 3 ? 8 : 5;
  b.add(mEar, box(0.245, H - 0.014, 0.004, -0.088, 0, Z_FRONT + 0.018));
  for (let r = 0; r < ventRows; r++) {
    const vy = (H * 0.34) - (r / Math.max(1, ventRows - 1)) * (H * 0.68);
    b.add(mDark, box(0.220, 0.005, 0.005, -0.088, vy, Z_FRONT + 0.0195));
  }

  // Right Recessed Angled LCD Display Console + 5 Control Buttons + 4 Status LEDs
  const lcdX = 0.125;
  b.add(mDark, box(0.145, H * 0.78, 0.008, lcdX, 0, Z_FRONT + 0.017));
  b.add(mLcdGlass, box(0.095, H * 0.42, 0.005, lcdX - 0.010, H * 0.06, Z_FRONT + 0.020));
  // 5 physical tactile buttons below LCD (ESC, UP, DOWN, ENTER, PWR)
  for (let k = 0; k < 5; k++) {
    b.add(mBtn, box(0.014, 0.008, 0.006, lcdX - 0.048 + k * 0.020, -H * 0.26, Z_FRONT + 0.021));
  }
  // 4 live animated UPS status LEDs (Mains Green / Battery / Bypass / Fault)
  const upsLeds = [
    { name: 'STATUS_LED_PWR', hex: '#00d930', y: H * 0.24 },
    { name: 'STATUS_LED_SYS', hex: '#00c828', y: H * 0.10 },
    { name: 'STATUS_LED_FAN', hex: '#334155', y: -H * 0.04 },
    { name: 'STATUS_LED_ALM', hex: '#334155', y: -H * 0.18 },
  ];
  for (const l of upsLeds) {
    const mLed = b.mat(`MAT_UPS_${l.name}`, l.hex, 0.12, 0.2, { emissive: hexToRgba(l.hex).slice(0, 3).map(v => v * 0.75) });
    b.addNode(l.name, mLed, box(0.006, 0.004, 0.004), [lcdX + 0.056, l.y, Z_FRONT + 0.021], { component_type: 'status_led' });
  }

  // Rear UPS Power Distribution Panel: 8 x IEC C13 + 2 x IEC C19 + Input Breaker + SNMP Card + Dual Fans
  b.add(mBezel, box(W_BODY, H - 0.004, 0.01, 0, 0, Z_REAR - 0.005));
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 2; row++) {
      const rx = -0.175 + col * 0.036;
      const ry = (row === 0 ? 1 : -1) * (H * 0.20);
      b.add(mDark, box(0.024, 0.018, 0.008, rx, ry, Z_REAR - 0.011));
    }
  }
  // High-current IEC C19 outlets + Red Input Circuit Breaker + SNMP Management Slot + Rear Fans
  for (const rx of [-0.010, 0.030]) {
    b.add(mDark, box(0.030, 0.022, 0.008, rx, 0, Z_REAR - 0.011));
  }
  b.add(mRed, box(0.024, 0.028, 0.012, 0.075, 0, Z_REAR - 0.012));
  b.add(mEar, box(0.075, 0.024, 0.008, 0.145, H * 0.22, Z_REAR - 0.011)); // SNMP SmartSlot card
  b.add(mDark, cyl(Math.min(0.028, H * 0.26), Math.min(0.028, H * 0.26), 0.008, 16, 0.155, -H * 0.18, Z_REAR - 0.011, Math.PI / 2));

  return b.toGlb();
}

// ---------------------------------------------------------------------------
// Build & Publish All 25 Production PBR Assets
// ---------------------------------------------------------------------------
const ASSETS = [
  ['rack_42u_600x1000.glb', buildRack42U],
  // H3C (Box DC, Box Campus/Agg, Modular 8U Chassis)
  ['h3c_s6800_family.glb', buildH3cS6800],
  ['h3c_s6850_family.glb', buildH3cS6800],
  ['h3c_s6805_family.glb', buildH3cS6800],
  ['h3c_s5130s_ei_family.glb', () => buildH3cCampus1U({ optical: false })],
  ['h3c_s5560x_ei_family.glb', () => buildH3cCampus1U({ optical: true })],
  ['h3c_s10500x_chassis_8u.glb', () => buildModularChassis({ heightU: 8, bodyHex: '#b8c2ce', faceHex: '#cfd6df', earHex: '#9aa5b4', accentHex: '#dc2626', leverHex: '#dc2626' })],
  // Cisco (Catalyst 9300 24P/48P Box, Nexus 93180YC-FX3 DC Box, Catalyst 9407R 10U Modular Chassis)
  ['cisco_catalyst_9300_24p.glb', () => buildCiscoCatalyst9300(24)],
  ['cisco_catalyst_9300_48p.glb', () => buildCiscoCatalyst9300(48)],
  ['cisco_nexus_93180yc_fx3.glb', buildCiscoNexus93180],
  ['cisco_catalyst_9407r_chassis_10u.glb', () => buildModularChassis({ heightU: 10, bodyHex: '#252c36', faceHex: '#1b222c', earHex: '#8d99a8', accentHex: '#00bceb', leverHex: '#00bceb', slotTypes: ['lpu_rj45', 'lpu_sfp', 'mpu', 'mpu', 'lpu_sfp', 'lpu_sfp', 'lpu_qsfp'] })],
  // Huawei (S5755-H Campus, S6730-H Agg, CloudEngine 6800 DC, CloudEngine 12800 8U Modular Chassis)
  ['huawei_s5755_h_family.glb', () => buildHuaweiBox1U({ optical: false, copper48: true, dcStyle: false })],
  ['huawei_s6730_h_v2_family.glb', () => buildHuaweiBox1U({ optical: true, dcStyle: true })],
  ['huawei_ce6800_family.glb', () => buildHuaweiBox1U({ optical: true, dcStyle: true })],
  ['huawei_ce12800_chassis_8u.glb', () => buildModularChassis({ heightU: 8, bodyHex: '#9aa5b4', faceHex: '#2a3342', earHex: '#8d99a8', accentHex: '#e11d48', leverHex: '#e11d48' })],
  // Ruijie (Campus Box, RG-S6510 DC Box, RG-N18000 8U Modular Core Chassis)
  ['ruijie_campus_family.glb', () => buildRuijieBox1U({ dcStyle: false })],
  ['ruijie_s6510_dc_1u.glb', () => buildRuijieBox1U({ dcStyle: true })],
  ['ruijie_dc_family.glb', () => buildModularChassis({ heightU: 8, bodyHex: '#283242', faceHex: '#1d2736', earHex: '#8d99a8', accentHex: '#2563eb', leverHex: '#2563eb' })],
  // ZTE (ZXR10 9904-S 8U Data Center Modular Core Chassis)
  ['zte_zxr10_9904_s.glb', () => buildModularChassis({ heightU: 8, bodyHex: '#212936', faceHex: '#18202c', earHex: '#8d99a8', accentHex: '#0086d6', leverHex: '#0284c7' })],
  // Rack-Mount UPS (2U & 3U Online UPS)
  ['generic_ups_2u.glb', () => buildRackUps(2)],
  ['generic_ups_3u.glb', () => buildRackUps(3)],
  // Generic Switches, Firewalls, Wireless AC, Patch Panel & Servers
  ['generic_switch_1u_48p.glb', buildGenericSwitch48P],
  ['generic_switch_1u_24p.glb', buildGenericSwitch24P],
  ['generic_switch_1u_sfp.glb', buildGenericSwitchSfp],
  ['generic_switch_dc_1u.glb', buildH3cS6800],
  ['generic_firewall_1u.glb', buildFirewall1U],
  ['generic_wireless_ac_1u.glb', buildWirelessAc1U],
  ['generic_patch_panel_cat6_24p.glb', buildPatchPanel24P],
  ['generic_server_1u.glb', buildServer1U],
  ['generic_server_2u.glb', buildServer2U],
];

for (const dir of OUT_DIRS) {
  fs.mkdirSync(dir, { recursive: true });
}

for (const [filename, builder] of ASSETS) {
  const glb = builder();
  for (const dir of OUT_DIRS) {
    fs.writeFileSync(path.join(dir, filename), glb);
  }
  console.log(`Built ${filename.padEnd(32)} ${(glb.length / 1024).toFixed(1).padStart(6)} KB`);
}
