// Four render passes (colour / normal+depth / flat colour) plus bloom, combined
// by one composite shader: ink lines, two-tone shading, world-space hatching,
// painted sky, night grade.
import * as THREE from 'three';

const SS = 2; // internal supersampling: RTs are 2x the output, downsampled on read

const VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const COMPOSITE = /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform sampler2D tBeauty;
uniform sampler2D tFlat;
uniform sampler2D tNormal;
uniform sampler2D tDepth;
uniform sampler2D tBloom;
uniform vec2 uTexel;
uniform vec2 uRTexel;
uniform mat4 uInvProj;
uniform mat4 uCamWorld;
uniform vec3 uCamPos;
uniform float uInk;

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float vnoise(vec2 p) {
  vec2 i = floor(p); vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1,0)), u.x),
             mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) { v += a * vnoise(p); p *= 2.03; a *= 0.5; }
  return v;
}

float depthAt(vec2 uv) { return texture2D(tDepth, uv).r; }

vec3 skyColor(vec3 dir) {
  float h = clamp(dir.y, 0.0, 1.0);
  vec3 horizon = vec3(0.118, 0.072, 0.086);
  vec3 mid = vec3(0.030, 0.042, 0.082);
  vec3 zenith = vec3(0.006, 0.009, 0.020);
  vec3 c = mix(horizon, mid, smoothstep(0.0, 0.14, h));
  c = mix(c, zenith, smoothstep(0.13, 0.55, h));
  c += vec3(0.30, 0.12, 0.16) * exp(-h * 19.0) * 0.30;   // city glow
  float n = fbm(dir.xz / (0.10 + max(dir.y, 0.05)) * 1.6);
  c += vec3(0.05, 0.045, 0.06) * n * smoothstep(0.02, 0.35, dir.y);
  return c;
}

void main() {
  vec2 uv = vUv;
  vec2 e = uRTexel;

  float dC = depthAt(uv);
  vec3 nC = texture2D(tNormal, uv).rgb * 2.0 - 1.0;
  vec3 flatC = texture2D(tFlat, uv).rgb;
  vec3 beauty = texture2D(tBeauty, uv).rgb;

  float dL = depthAt(uv - vec2(e.x, 0.0));
  float dR = depthAt(uv + vec2(e.x, 0.0));
  float dU = depthAt(uv + vec2(0.0, e.y));
  float dD = depthAt(uv - vec2(0.0, e.y));
  vec3 nL = texture2D(tNormal, uv - vec2(e.x, 0.0)).rgb * 2.0 - 1.0;
  vec3 nR = texture2D(tNormal, uv + vec2(e.x, 0.0)).rgb * 2.0 - 1.0;
  vec3 nU = texture2D(tNormal, uv + vec2(0.0, e.y)).rgb * 2.0 - 1.0;
  vec3 nD = texture2D(tNormal, uv - vec2(0.0, e.y)).rgb * 2.0 - 1.0;

  // ---- edge masks -------------------------------------------------------
  float dispC = 1.0 / max(dC, 0.06);
  float relDepth = (abs(1.0 / max(dL, 0.06) - dispC) + abs(1.0 / max(dR, 0.06) - dispC)
                  + abs(1.0 / max(dU, 0.06) - dispC) + abs(1.0 / max(dD, 0.06) - dispC)) / dispC;
  float lineDepth = smoothstep(0.012, 0.055, relDepth);

  float nDiff = max(max(1.0 - dot(nC, nL), 1.0 - dot(nC, nR)),
                    max(1.0 - dot(nC, nU), 1.0 - dot(nC, nD)));
  float lineNormal = smoothstep(0.10, 0.44, nDiff) * smoothstep(0.0, 0.02, dC);

  float fC = luma(flatC);
  float fEdge = abs(luma(texture2D(tFlat, uv - vec2(e.x, 0.0)).rgb) - fC)
              + abs(luma(texture2D(tFlat, uv + vec2(e.x, 0.0)).rgb) - fC)
              + abs(luma(texture2D(tFlat, uv + vec2(0.0, e.y)).rgb) - fC)
              + abs(luma(texture2D(tFlat, uv - vec2(0.0, e.y)).rgb) - fC);
  float lineFlat = smoothstep(0.030, 0.11, fEdge);

  // thin lines from colour changes (windows, neon edges); fade with distance
  float bL = luma(texture2D(tBeauty, uv - vec2(e.x, 0.0)).rgb);
  float bR = luma(texture2D(tBeauty, uv + vec2(e.x, 0.0)).rgb);
  float bU = luma(texture2D(tBeauty, uv + vec2(0.0, e.y)).rgb);
  float bD = luma(texture2D(tBeauty, uv - vec2(0.0, e.y)).rgb);
  float bGrad = abs(bR - bL) + abs(bU - bD);
  float distFade = 1.0 - smoothstep(30.0, 260.0, dC);
  float lineLuma = smoothstep(0.10, 0.30, bGrad) * mix(0.35, 1.0, distFade);

  float line = clamp(max(max(lineDepth, lineNormal), lineFlat) + lineLuma * 0.55, 0.0, 1.0);
  line *= uInk;

  // ---- illustration shading ---------------------------------------------
  float l = luma(beauty);
  float tone = smoothstep(0.045, 0.26, l);
  vec3 col = beauty * mix(0.62, 1.12, tone);
  col = mix(col, flatC * mix(0.45, 1.10, tone), 0.24);

  // world position for hatching
  vec2 ndc = uv * 2.0 - 1.0;
  vec4 vp = uInvProj * vec4(ndc, 1.0, 1.0);
  vp /= vp.w;
  vec3 viewPos = vp.xyz * (max(dC, 0.06) / max(-vp.z, 0.0001));
  vec3 worldPos = (uCamWorld * vec4(viewPos, 1.0)).xyz;

  bool isSky = dC < 0.05;
  if (isSky) {
    vec3 dir = normalize((uCamWorld * vec4(vp.xyz, 0.0)).xyz);
    col = skyColor(dir);
  } else {
    float hx = sin((worldPos.x * 0.7 + worldPos.z) * 7.0 + worldPos.y * 0.9);
    float hatch = smoothstep(0.55, 0.95, hx);
    float near = 1.0 - smoothstep(6.0, 55.0, dC);
    col *= 1.0 - 0.16 * hatch * (1.0 - tone) * near;
    // ground sheen: grazing angles catch the neon
    float sheen = pow(1.0 - clamp(abs(nC.y), 0.0, 1.0), 4.0);
    col += vec3(0.05, 0.06, 0.09) * sheen * 0.35;
  }

  // ---- bloom, ink, grade -------------------------------------------------
  vec3 bloom = min(texture2D(tBloom, uv).rgb, vec3(0.55));
  col += bloom * 0.52;

  vec3 ink = mix(vec3(0.015, 0.018, 0.028), flatC * 0.18, 0.4);
  col = mix(col, ink, line);

  // night grade: cool shadows, warm highlights, deeper blacks
  float lum = luma(col);
  col = mix(col * vec3(0.78, 0.92, 1.16), col * vec3(1.12, 1.00, 0.92), smoothstep(0.05, 0.55, lum));
  col *= 1.22;
  col += vec3(0.002, 0.003, 0.007);
  col = mix(col, col * col * (3.0 - 2.0 * col), 0.28);
  float gsat = luma(col);
  col = mix(vec3(gsat), col, 1.14);
  col = pow(max(col, vec3(0.0)), vec3(0.98, 1.00, 1.03));

  // ACES-ish filmic, but first pull the brightest colours toward neutral: the
  // per-channel curve otherwise turns bright blue-white paint (the zebra) green.
  float hl = luma(col);
  col = mix(col, vec3(hl), smoothstep(0.45, 1.30, hl) * 0.6);
  col = (col * (2.51 * col + 0.03)) / (col * (2.43 * col + 0.59) + 0.14);
  col = clamp(col, 0.0, 1.0);

  // vignette + grain
  vec2 q = uv - 0.5;
  col *= 1.0 - 0.42 * dot(q, q) * 1.25;
  float g = hash(uv * vec2(1920.0, 1080.0)) - 0.5;
  col += g * 0.012;

  // linear -> sRGB
  col = mix(col * 12.92, 1.055 * pow(max(col, vec3(0.0001)), vec3(1.0 / 2.4)) - 0.055, step(0.0031308, col));
  gl_FragColor = vec4(col, 1.0);
}
`;

const BLUR = /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform sampler2D tMap;
uniform vec2 uDir;
void main() {
  vec3 sum = vec3(0.0);
  float wsum = 0.0;
  for (int i = -4; i <= 4; i++) {
    float w = exp(-abs(float(i)) * 0.55);
    sum += texture2D(tMap, vUv + uDir * float(i)).rgb * w;
    wsum += w;
  }
  gl_FragColor = vec4(sum / wsum, 1.0);
}
`;

const BRIGHT = /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform sampler2D tMap;
uniform vec2 uTexel;
void main() {
  vec3 c = vec3(0.0);
  c += texture2D(tMap, vUv + uTexel * vec2(-1.0, -1.0)).rgb;
  c += texture2D(tMap, vUv + uTexel * vec2( 1.0, -1.0)).rgb;
  c += texture2D(tMap, vUv + uTexel * vec2(-1.0,  1.0)).rgb;
  c += texture2D(tMap, vUv + uTexel * vec2( 1.0,  1.0)).rgb;
  c *= 0.25;
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  float k = smoothstep(0.52, 1.05, l);
  gl_FragColor = vec4(c * k * 1.15, 1.0);
}
`;

export class Post {
  constructor(renderer, width, height) {
    this.renderer = renderer;
    this.width = width;
    this.height = height;
    this.rw = width * SS;
    this.rh = height * SS;

    const rtOpts = {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      depthBuffer: true,
      stencilBuffer: false,
      generateMipmaps: false,
    };
    this.rtBeauty = new THREE.WebGLRenderTarget(this.rw, this.rh, { ...rtOpts, type: THREE.HalfFloatType });
    this.rtFlat = new THREE.WebGLRenderTarget(this.rw, this.rh, { ...rtOpts, type: THREE.UnsignedByteType });
    this.rtNormal = new THREE.WebGLRenderTarget(this.rw, this.rh, { ...rtOpts, type: THREE.UnsignedByteType });
    this.rtDepth = new THREE.WebGLRenderTarget(this.rw, this.rh, { ...rtOpts, type: THREE.HalfFloatType });
    for (const t of [this.rtBeauty, this.rtFlat, this.rtNormal, this.rtDepth]) {
      t.texture.colorSpace = THREE.NoColorSpace;
      t.texture.wrapS = t.texture.wrapT = THREE.ClampToEdgeWrapping;
    }

    const bw = Math.max(1, Math.floor(this.rw / 4));
    const bh = Math.max(1, Math.floor(this.rh / 4));
    this.rtBloomA = new THREE.WebGLRenderTarget(bw, bh, { ...rtOpts, depthBuffer: false, type: THREE.HalfFloatType });
    this.rtBloomB = new THREE.WebGLRenderTarget(bw, bh, { ...rtOpts, depthBuffer: false, type: THREE.HalfFloatType });
    this.rtBloomA.texture.colorSpace = THREE.NoColorSpace;
    this.rtBloomB.texture.colorSpace = THREE.NoColorSpace;

    // passes
    this.quadScene = new THREE.Scene();
    this.quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
    this.quad.frustumCulled = false;
    this.quadScene.add(this.quad);

    this.normalMat = new THREE.ShaderMaterial({
      vertexShader: /* glsl */ `
        varying vec3 vN;
        void main() {
          vN = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: /* glsl */ `
        varying vec3 vN;
        void main() {
          vec3 n = normalize(vN);
          gl_FragColor = vec4(n * 0.5 + 0.5, 1.0);
        }`,
      side: THREE.FrontSide,
    });

    this.depthMat = new THREE.ShaderMaterial({
      vertexShader: /* glsl */ `
        varying float vZ;
        void main() {
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vZ = -mv.z;
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: /* glsl */ `
        varying float vZ;
        void main() { gl_FragColor = vec4(vZ, 0.0, 0.0, 1.0); }`,
      side: THREE.FrontSide,
    });

    this.flatMat = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.FrontSide });

    this.blurMat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: BLUR,
      uniforms: { tMap: { value: null }, uDir: { value: new THREE.Vector2() } },
      depthTest: false,
      depthWrite: false,
    });
    this.brightMat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: BRIGHT,
      uniforms: { tMap: { value: null }, uTexel: { value: new THREE.Vector2(1 / this.rw, 1 / this.rh) } },
      depthTest: false,
      depthWrite: false,
    });

    this.compMat = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: COMPOSITE,
      uniforms: {
        tBeauty: { value: this.rtBeauty.texture },
        tFlat: { value: this.rtFlat.texture },
        tNormal: { value: this.rtNormal.texture },
        tDepth: { value: this.rtDepth.texture },
        tBloom: { value: this.rtBloomA.texture },
        uTexel: { value: new THREE.Vector2(1 / width, 1 / height) },
        uRTexel: { value: new THREE.Vector2(1 / this.rw, 1 / this.rh) },
        uInvProj: { value: new THREE.Matrix4() },
        uCamWorld: { value: new THREE.Matrix4() },
        uCamPos: { value: new THREE.Vector3() },
        uInk: { value: 1.0 },
      },
      depthTest: false,
      depthWrite: false,
    });
  }

  pass(material, target) {
    this.quad.material = material;
    this.renderer.setRenderTarget(target);
    this.renderer.clear();
    this.renderer.render(this.quadScene, this.quadCam);
  }

  render(scene, camera, world) {
    const r = this.renderer;
    const prevTarget = r.getRenderTarget();

    // 1. beauty
    r.setRenderTarget(this.rtBeauty);
    r.setClearColor(0x05070c, 1);
    r.clear();
    r.render(scene, camera);

    // 2. geometric passes (no rain / glows / smears)
    world.setAuxVisible(false);
    scene.overrideMaterial = this.normalMat;
    r.setRenderTarget(this.rtNormal);
    r.setClearColor(0x000000, 1);
    r.clear();
    r.render(scene, camera);

    scene.overrideMaterial = this.depthMat;
    r.setRenderTarget(this.rtDepth);
    r.clear();
    r.render(scene, camera);

    scene.overrideMaterial = this.flatMat;
    r.setRenderTarget(this.rtFlat);
    r.clear();
    r.render(scene, camera);
    scene.overrideMaterial = null;
    world.setAuxVisible(true);

    // 3. bloom
    this.brightMat.uniforms.tMap.value = this.rtBeauty.texture;
    this.pass(this.brightMat, this.rtBloomA);

    const bw = this.rtBloomA.width;
    const bh = this.rtBloomA.height;
    this.blurMat.uniforms.tMap.value = this.rtBloomA.texture;
    this.blurMat.uniforms.uDir.value.set(1.6 / bw, 0);
    this.pass(this.blurMat, this.rtBloomB);
    this.blurMat.uniforms.tMap.value = this.rtBloomB.texture;
    this.blurMat.uniforms.uDir.value.set(0, 1.6 / bh);
    this.pass(this.blurMat, this.rtBloomA);
    this.blurMat.uniforms.tMap.value = this.rtBloomA.texture;
    this.blurMat.uniforms.uDir.value.set(3.2 / bw, 0);
    this.pass(this.blurMat, this.rtBloomB);
    this.blurMat.uniforms.tMap.value = this.rtBloomB.texture;
    this.blurMat.uniforms.uDir.value.set(0, 3.2 / bh);
    this.pass(this.blurMat, this.rtBloomA);

    // 4. composite to the canvas
    this.compMat.uniforms.uInvProj.value.copy(camera.projectionMatrixInverse);
    this.compMat.uniforms.uCamWorld.value.copy(camera.matrixWorld);
    this.compMat.uniforms.uCamPos.value.copy(camera.position);
    this.quad.material = this.compMat;
    r.setRenderTarget(prevTarget);
    r.setViewport(0, 0, this.width, this.height);
    r.clear();
    r.render(this.quadScene, this.quadCam);
  }
}
