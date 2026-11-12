const noiseFunctions = /* glsl */ `
float hash31(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.yzx + 33.33);
  return fract((p.x + p.y) * p.z);
}

float valueNoise3(vec3 p) {
  vec3 cell = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);

  float n000 = hash31(cell);
  float n100 = hash31(cell + vec3(1.0, 0.0, 0.0));
  float n010 = hash31(cell + vec3(0.0, 1.0, 0.0));
  float n110 = hash31(cell + vec3(1.0, 1.0, 0.0));
  float n001 = hash31(cell + vec3(0.0, 0.0, 1.0));
  float n101 = hash31(cell + vec3(1.0, 0.0, 1.0));
  float n011 = hash31(cell + vec3(0.0, 1.0, 1.0));
  float n111 = hash31(cell + vec3(1.0, 1.0, 1.0));

  float z0 = mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y);
  float z1 = mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y);
  return mix(z0, z1, f.z);
}
`;

export const simulationVertexShader = /* glsl */ `
precision highp float;

varying vec2 vUv;

void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const simulationFragmentShader = /* glsl */ `
precision highp float;

uniform sampler2D stateTexture;
uniform sampler2D referenceTexture;
uniform vec2 ringCenter;
uniform float time;
uniform float delta;
uniform vec2 resolution;

varying vec2 vUv;

${noiseFunctions}

void main() {
  vec4 previous = texture2D(stateTexture, vUv);
  vec4 reference = texture2D(referenceTexture, vUv);
  vec2 anchor = reference.xy;
  vec2 simResolution = max(resolution, vec2(1.0));
  vec2 particleUv = (floor(vUv * simResolution) + 0.5) / simResolution;

  float ringRadius = 0.175 + sin(time) * 0.03 + cos(time * 3.0) * 0.02;
  vec2 fromRing = anchor - ringCenter;
  float distanceToRing = length(fromRing);
  float edgeNoise = (valueNoise3(vec3(anchor * 0.2 + vec2(18.49, 72.97), time * 0.25)) * 2.0 - 1.0) * 0.005;
  float perturbedDistance = length(fromRing + edgeNoise);
  float narrowRing = smoothstep(ringRadius - 0.012, ringRadius, distanceToRing)
    - smoothstep(ringRadius, ringRadius + 0.006, perturbedDistance);
  float wideRing = smoothstep(ringRadius - 0.214, ringRadius, distanceToRing)
    - smoothstep(ringRadius, ringRadius + 0.107, perturbedDistance);
  narrowRing = pow(max(narrowRing, 0.0), 2.0);
  wideRing = pow(max(wideRing, 0.0), 3.0);
  float inner = 1.0 - smoothstep(ringRadius, ringRadius + 0.107, distanceToRing);

  vec2 coarseNoise = vec2(
    valueNoise3(vec3(anchor * 4.0 + vec2(88.494, 32.44), time * 0.175)),
    valueNoise3(vec3(anchor * 4.0 + vec2(50.90, 120.95), time * 0.175))
  );
  vec2 fineNoise = vec2(
    valueNoise3(vec3(anchor * 20.0 + vec2(18.49, 72.97), time * 0.25)),
    valueNoise3(vec3(anchor * 20.0 + vec2(50.90, 120.95), time * 0.25))
  );
  vec2 sineDrift = vec2(
    sin(time * 2.0 + anchor.x * 20.0),
    cos(time * 1.5 + anchor.y * 20.0)
  ) * 0.02 * clamp(distanceToRing, 0.0, 1.0);
  vec2 drift = (coarseNoise - 0.5) * 0.06 + (fineNoise - 0.5) * 0.01 + sineDrift;

  vec2 radialAction = (fromRing + drift) * pow(wideRing, 0.75) * 0.62 * 0.25;
  vec2 position = anchor + drift + previous.xy * 0.2 + radialAction;

  float fineScale = valueNoise3(vec3(anchor * 30.0 + vec2(11.49, 12.97), time * 0.25)) * 2.0 - 1.0;
  float ambientScale = valueNoise3(vec3(anchor * 2.0 + vec2(18.49, 72.97), time * 0.25)) * 2.0 - 1.0;
  float targetScale = narrowRing + wideRing * 3.0 + inner * (0.4 + fineScale * 0.5)
    + pow((ambientScale + 1.5) * 0.5, 2.0) * 0.6;
  float scaleResponse = 1.0 - pow(0.8, max(delta, 0.0) * 60.0);
  float scale = mix(previous.z, targetScale, scaleResponse);
  float brightnessVelocity = previous.w * 0.5 + scale * 0.25;

  gl_FragColor = vec4(position, scale, brightnessVelocity);
}
`;

export const particleVertexShader = /* glsl */ `
precision highp float;

attribute vec2 referenceUv;
attribute vec4 seed;

uniform sampler2D stateTexture;
uniform float time;
uniform float pixelRatio;
uniform float particleScale;
uniform vec2 ringCenter;
uniform float fallbackMotion;

varying float vScale;
varying float vBrightness;
varying vec2 vLocalPosition;
varying vec4 vSeed;

void main() {
  vec4 state = texture2D(stateTexture, referenceUv);
  vec2 position = state.xy;
  float scale = state.z;
  float brightness = state.w;

  if (fallbackMotion > 0.5) {
    float phase = seed.x * 6.2831853;
    vec2 fromRing = state.xy - ringCenter;
    float distanceToRing = length(fromRing);
    vec2 direction = fromRing / max(distanceToRing, 0.0001);
    vec2 tangent = vec2(-direction.y, direction.x);
    float pointerInfluence = 1.0 - smoothstep(0.12, 0.72, distanceToRing);
    float wave = sin(time * 2.1 + phase);
    vec2 ambientDrift = vec2(
      sin(time * 0.9 + phase),
      cos(time * 1.1 + phase * 1.7)
    ) * 0.004;
    vec2 pointerDrift = (direction * wave * 0.03 + tangent * cos(time * 1.7 + phase) * 0.012)
      * pointerInfluence;
    position = state.xy + ambientDrift + pointerDrift;

    float ringRadius = 0.175 + sin(time) * 0.03 + cos(time * 3.0) * 0.02;
    float ringDistance = abs(distanceToRing - ringRadius);
    float ringIntensity = 1.0 - smoothstep(0.025, 0.12, ringDistance);
    scale = state.z * (0.85 + wave * 0.08) + ringIntensity * 0.45;
    brightness = state.w * 0.5 + scale * 0.25;
  }

  vScale = scale;
  vBrightness = brightness;
  vLocalPosition = position;
  vSeed = seed;

  vec4 viewPosition = modelViewMatrix * vec4(position, 0.0, 1.0);
  gl_Position = projectionMatrix * viewPosition;
  gl_PointSize = scale * 7.0 * pixelRatio * 0.5 * particleScale;
}
`;

export const particleFragmentShader = /* glsl */ `
precision highp float;

uniform vec2 ringCenter;
uniform float time;

varying float vScale;
varying float vBrightness;
varying vec2 vLocalPosition;
varying vec4 vSeed;

${noiseFunctions}

float sdRoundBox(vec2 p, vec2 halfSize, float radius) {
  vec2 q = abs(p) - halfSize + radius;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
}

void main() {
  vec2 radial = vLocalPosition - ringCenter;
  float radialLength = length(radial);
  radial = radialLength > 0.0001 ? radial / radialLength : vec2(1.0, 0.0);

  vec2 point = gl_PointCoord - 0.5;
  point.y *= -1.0;
  mat2 orientToRadius = mat2(radial.x, radial.y, -radial.y, radial.x);
  vec2 capsulePoint = orientToRadius * point;
  float capsuleLength = 0.5;
  float capsuleWidth = 0.2;
  float capsuleDistance = sdRoundBox(capsulePoint, vec2(capsuleLength, capsuleWidth), capsuleWidth);
  float capsule = 1.0 - smoothstep(0.0, 0.1, capsuleDistance);

  float colorField = valueNoise3(vec3(vLocalPosition * 2.0 + vec2(74.66, 91.56), time * 0.5));
  float colorProgress = smoothstep(0.0, 0.75, colorField * colorField);

  vec3 blue = vec3(0.025187, 0.127438, 0.846873);  // #2c64ed in linear RGB
  vec3 red = vec3(0.938686, 0.054480, 0.054480);   // #f84242 in linear RGB
  vec3 yellow = vec3(1.0, 0.623960, 0.000911);     // #ffcf03 in linear RGB
  vec3 color = colorProgress < 0.8
    ? mix(blue, red, colorProgress / 0.8)
    : mix(red, yellow, (colorProgress - 0.8) / 0.2);

  float scaleAlpha = smoothstep(0.1, 0.2, vScale);
  float alpha = capsule * scaleAlpha;
  if (alpha <= 0.001) discard;

  gl_FragColor = vec4(color * clamp(vBrightness, 0.0, 1.0), alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;
