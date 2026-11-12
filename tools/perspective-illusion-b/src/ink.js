// ink.js — final composite: ink lines, two-tone shading, world-anchored
// hatching, painted sky, bloom, grade. Inputs are the colour pass and the
// normal+depth pass. Sky is painted by VIEW DIRECTION so clouds stay put.
import * as THREE from 'three';

const VERT = `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const FRAG = `
precision highp float;
varying vec2 vUv;
uniform sampler2D tColor, tGeo;
uniform vec2  uRes;
uniform mat4  uInvProj, uCamMat;
uniform vec3  uLightView;
uniform float uNoInk, uTime;

float lum(vec3 c){ return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  f = f*f*(3.0-2.0*f);
  return mix(mix(hash(i), hash(i+vec2(1,0)), f.x),
             mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y);
}
float fbm(vec2 p){
  float v = 0.0, a = 0.5;
  for(int i=0;i<4;i++){ v += a*noise(p); p *= 2.03; a *= 0.5; }
  return v;
}
vec3 skyColor(vec3 d){
  float h = clamp(d.y*0.5+0.5, 0.0, 1.0);
  vec3 low  = vec3(0.38, 0.29, 0.42);
  vec3 mid  = vec3(0.20, 0.20, 0.36);
  vec3 high = vec3(0.055, 0.075, 0.16);
  vec3 col = mix(low, mid, smoothstep(0.47, 0.60, h));
  col = mix(col, high, smoothstep(0.58, 0.88, h));
  vec2 q = vec2(atan(d.z, d.x)*1.35, d.y*2.7);
  float n = fbm(q*1.9 + vec2(3.1, 1.7));
  col += vec3(0.16, 0.13, 0.19) * smoothstep(0.50, 0.76, n) * smoothstep(-0.1, 0.3, d.y);
  col += vec3(0.10, 0.07, 0.10) * smoothstep(0.62, 0.85, fbm(q*0.8 - 5.0));
  vec3 md = normalize(vec3(-0.34, 0.40, -0.85));
  float dm = distance(d, md);
  col += vec3(0.95, 0.90, 0.76) * (1.0 - smoothstep(0.010, 0.016, dm));
  col += vec3(0.30, 0.32, 0.48) * exp(-dm*dm*150.0) * 0.5;
  return col;
}

vec3 groundFar(vec3 d){
  float down = clamp(-d.y*16.0, 0.0, 1.0);
  vec3 c = mix(vec3(0.30,0.23,0.35), vec3(0.055,0.072,0.13), down);
  float a = atan(d.z, d.x);
  float bands = smoothstep(0.72, 0.96, sin(a*62.0)*0.5+0.5) * (1.0-down*0.55);
  c += vec3(0.17,0.12,0.08) * bands * 0.32;
  float streak = smoothstep(0.93, 0.999, sin(a*90.0)*0.5+0.5);
  c += vec3(0.10,0.14,0.22) * streak * down * 0.16;
  return c;
}

void main(){
  vec2 px = 1.0/uRes;
  vec4 C  = texture2D(tColor, vUv);
  vec4 G  = texture2D(tGeo,   vUv);
  float sky = step(G.a, 0.0015);
  vec3 wdir = normalize(mat3(uCamMat) * normalize((uInvProj * vec4(vUv*2.0-1.0, 1.0, 1.0)).xyz));

  vec4 Gl = texture2D(tGeo, vUv-vec2(px.x,0.0));
  vec4 Gr = texture2D(tGeo, vUv+vec2(px.x,0.0));
  vec4 Gu = texture2D(tGeo, vUv+vec2(0.0,px.y));
  vec4 Gd = texture2D(tGeo, vUv-vec2(0.0,px.y));
  vec3 Cl = texture2D(tColor, vUv-vec2(px.x,0.0)).rgb;
  vec3 Cr = texture2D(tColor, vUv+vec2(px.x,0.0)).rgb;
  vec3 Cu = texture2D(tColor, vUv+vec2(0.0,px.y)).rgb;
  vec3 Cd = texture2D(tColor, vUv-vec2(0.0,px.y)).rgb;

  // ink: normals + second difference of depth + colour discontinuities
  float nd = length(G.rgb-Gl.rgb)+length(G.rgb-Gr.rgb)+length(G.rgb-Gu.rgb)+length(G.rgb-Gd.rgb);
  float dd = abs(Gl.a+Gr.a+Gu.a+Gd.a-4.0*G.a);
  float cd = length(C.rgb-Cl)+length(C.rgb-Cr)+length(C.rgb-Cu)+length(C.rgb-Cd);
  float farFade = 1.0 - 0.78*smoothstep(0.20, 0.55, G.a);
  float edge = nd*1.05 + dd*26.0 + cd*0.42*farFade;
  float ink = smoothstep(0.20, 0.52, edge) * (1.0-sky);
  // never ink the bright emissive faces (signs / lamps)
  ink *= 1.0 - 0.85*smoothstep(0.72, 0.98, lum(C.rgb));

  // two-tone: hard light/shade step, no gradients
  vec3 N = normalize(G.rgb*2.0-1.0);
  float lam = dot(N, normalize(uLightView));
  float lit = smoothstep(0.22, 0.40, lam);
  vec3 base = C.rgb;
  vec3 shade = mix(base*0.50, vec3(0.065,0.082,0.145), 0.42);
  vec3 col = mix(shade, base, lit);

  // world-anchored hatching, only on the shaded side (cast-shadow stand-in)
  vec3 dirV = normalize((uInvProj * vec4(vUv*2.0-1.0, 1.0, 1.0)).xyz);
  float vz = G.a*700.0;
  vec3 Pv = dirV * (vz / max(-dirV.z, 0.0001));
  vec3 Pw = (uCamMat * vec4(Pv, 1.0)).xyz;
  float hp = (Pw.x*0.85 + Pw.z*0.40 + Pw.y*0.30) * 3.6;
  float hatch = smoothstep(0.55, 0.92, sin(hp));
  hatch *= 1.0 - smoothstep(0.10, 0.55, fwidth(hp));
  col = mix(col, shade*0.62, hatch*(1.0-lit)*(1.0-sky)*0.55);

  col = mix(col, vec3(0.030,0.038,0.072), ink*0.88*(1.0-uNoInk));

  // bloom on emissive highlights
  vec3 bloom = vec3(0.0);
  for(int i=0;i<12;i++){
    float a = float(i)*0.5236;
    vec2 o = vec2(cos(a), sin(a)) * px * (4.0 + mod(float(i),3.0)*4.0);
    vec3 s = texture2D(tColor, vUv+o).rgb;
    bloom += max(s - vec3(0.52), vec3(0.0));
  }
  col += bloom/12.0 * 0.72;

  vec3 bg = mix(groundFar(wdir), skyColor(wdir), smoothstep(-0.006, 0.020, wdir.y));
  col = mix(col, bg, sky);

  // grade: cool night, gentle contrast, paper grain, vignette
  col = pow(max(col, vec3(0.0)), vec3(0.93));
  col *= vec3(1.02, 1.00, 1.09);
  float v = length((vUv-0.5)*vec2(1.05,1.0));
  col *= 1.0 - 0.42*pow(v, 2.1);
  col += (hash(gl_FragCoord.xy)-0.5)*0.016;
  gl_FragColor = vec4(col, 1.0);
}
`;

export function makeComposite(W, H) {
  const uniforms = {
    tColor: { value: null }, tGeo: { value: null },
    uRes: { value: new THREE.Vector2(W, H) },
    uInvProj: { value: new THREE.Matrix4() },
    uCamMat: { value: new THREE.Matrix4() },
    uLightView: { value: new THREE.Vector3(-0.4, 0.75, 0.52).normalize() },
    uNoInk: { value: 0 }, uTime: { value: 0 },
  };
  const material = new THREE.ShaderMaterial({
    uniforms, vertexShader: VERT, fragmentShader: FRAG,
    depthTest: false, depthWrite: false,
  });
  const scene = new THREE.Scene();
  const cam = new THREE.Camera();
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  quad.frustumCulled = false;
  scene.add(quad);
  return { uniforms, material, scene, cam };
}

export const GEO_VERT = `
varying vec3 vN;
varying float vZ;
void main(){
  vec4 local = vec4(position, 1.0);
  vec3 n = normal;
  #ifdef USE_INSTANCING
    local = instanceMatrix * local;
    n = mat3(instanceMatrix) * n;
  #endif
  vec4 mv = modelViewMatrix * local;
  vN = normalize(normalMatrix * n);
  vZ = -mv.z;
  gl_Position = projectionMatrix * mv;
}
`;
export const GEO_FRAG = `
precision highp float;
varying vec3 vN;
varying float vZ;
void main(){
  gl_FragColor = vec4(normalize(vN)*0.5+0.5, clamp(vZ/700.0, 0.0, 1.0));
}
`;

export const BLIT_FRAG = `
precision highp float;
varying vec2 vUv;
uniform sampler2D tSrc, tRaw;
uniform float uRaw;
void main(){
  gl_FragColor = uRaw > 0.5 ? texture2D(tRaw, vUv) : texture2D(tSrc, vUv);
}
`;
