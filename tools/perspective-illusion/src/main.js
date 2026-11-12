// Page contract for the renderers (perspective-illusion doctrine):
//   window.render(ms)       draws the frame at time ms (deterministic, pure)
//   window.probe(ms)        screen positions of street points, sizes motion blur
//   window.setJitter(x, y)  sub-pixel lens offset in canvas pixels
//   window.renderMany(list) averages several [ms, jx, jy] renders on the GPU
//                           and draws once (one image leaves the page)
//   window.READY            set once assets are loaded
// Debug switches: ?raw=1 (beauty only), ?noaux=1 (hide rain/glows),
// ?scale=.5 (half-size canvas), ?w=&h= (explicit size).
import * as THREE from 'three';
import { buildScene } from './scene.js';
import { Rig } from './rig.js';
import { Post } from './post.js';

const params = new URLSearchParams(location.search);
const SCALE = parseFloat(params.get('scale') || '1');
const W = parseInt(params.get('w') || String(Math.round(1920 * SCALE)), 10);
const H = parseInt(params.get('h') || String(Math.round(1080 * SCALE)), 10);
const RAW = params.get('raw') === '1';
const NOAUX = params.get('noaux') === '1';

const canvas = document.getElementById('view');
canvas.width = W;
canvas.height = H;

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: false, // AA comes from the jittered sub-frames, not MSAA
  preserveDrawingBuffer: true,
  powerPreference: 'high-performance',
  alpha: false,
});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
renderer.toneMapping = THREE.NoToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const world = buildScene();
const camera = new THREE.PerspectiveCamera(5, W / H, 0.3, 1500);
camera._probeW = W;
camera._probeH = H;
const rig = new Rig(camera);
const post = new Post(renderer, W, H);

function drawSceneAt(ms) {
  world.update(ms / 1000);
  const st = rig.apply(ms);
  world.updateSwap(st.lay, st.cs);
  world.setFog(st.d);
  if (NOAUX) world.setAuxVisible(false);
  post.render(world.scene, camera, world);
  return st;
}

// Full pipeline render (deterministic per ms).
window.render = (ms) => {
  const st = drawSceneAt(ms);
  return { t: ms, fov: +st.fov.toFixed(2), d: +st.d.toFixed(1), y: +st.y.toFixed(2), lay: +st.lay.toFixed(2) };
};

window.renderAt = window.render;
window.grabFrame = (ms) => {
  window.render(ms);
  return canvas.toDataURL('image/png');
};

window.setJitter = (jx, jy) => rig.setJitter(jx, jy);
window.probe = (ms) => rig.probe(ms).points;

// ---- GPU accumulation: average a frame's sub-renders inside the page ----
const frameRT = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType });
const accRT = new THREE.WebGLRenderTarget(W, H, { type: THREE.FloatType });
const QUAD_VS = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0., 1.); }';
const accScene = new THREE.Scene();
const accMat = new THREE.ShaderMaterial({
  uniforms: { t: { value: frameRT.texture }, w: { value: 1 } },
  vertexShader: QUAD_VS,
  fragmentShader: 'uniform sampler2D t; uniform float w; varying vec2 vUv; void main(){ gl_FragColor = vec4(texture2D(t, vUv).rgb * w, 1.); }',
  transparent: true,
  blending: THREE.AdditiveBlending,
  depthTest: false,
  depthWrite: false,
});
const accQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), accMat);
accQuad.frustumCulled = false;
accScene.add(accQuad);
const outScene = new THREE.Scene();
const outMat = new THREE.ShaderMaterial({
  uniforms: { t: { value: accRT.texture } },
  vertexShader: QUAD_VS,
  fragmentShader: 'uniform sampler2D t; varying vec2 vUv; void main(){ gl_FragColor = vec4(texture2D(t, vUv).rgb, 1.); }',
  depthTest: false,
  depthWrite: false,
});
const outQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), outMat);
outQuad.frustumCulled = false;
outScene.add(outQuad);
const quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

window.renderMany = (list) => {
  const r = renderer;
  r.setRenderTarget(accRT);
  r.setClearColor(0x000000, 1);
  r.clear();
  accMat.uniforms.w.value = 1 / list.length;
  for (const [ms, jx, jy] of list) {
    rig.setJitter(jx, jy);
    r.setRenderTarget(frameRT);
    drawSceneAt(ms);
    const ac = r.autoClear;
    r.autoClear = false;
    r.setRenderTarget(accRT);
    r.render(accScene, quadCam);
    r.autoClear = ac;
  }
  r.setRenderTarget(null);
  r.render(outScene, quadCam);
  rig.setJitter(0, 0);
};

if (RAW) {
  // debug: straight beauty render, no composite, to tell scene colour from grade
  window.render = (ms) => {
    world.update(ms / 1000);
    const st = rig.apply(ms);
    world.updateSwap(st.lay, st.cs);
    world.setFog(st.d);
    renderer.setRenderTarget(null);
    renderer.render(world.scene, camera);
    return { t: ms, raw: true };
  };
  window.renderMany = undefined;
}

const gl = renderer.getContext();
const dbg = gl.getExtension('WEBGL_debug_renderer_info');
window.__gpu = {
  version: gl.getParameter(gl.VERSION),
  renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : 'n/a',
};

window.render(0);
window.READY = true;
window.__world = world; // debug handle for probe scripts
window.__cam = camera;
window.__THREE = THREE;
