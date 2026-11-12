// main.js — two geometry passes (colour, normal+depth), one ink composite,
// GPU accumulation of jittered sub-frames, and the renderer page contract:
//   window.READY / render(ms) / probe(ms) / setJitter / renderMany(list)
import * as THREE from 'three';
import { buildCity } from './city.js';
import { sample, applyCamera, LOOP_MS, PROBE_POINTS } from './rig.js';
import { makeComposite, GEO_VERT, GEO_FRAG, BLIT_FRAG } from './ink.js';

THREE.ColorManagement.enabled = false;   // exact hex values, no hidden transfer

const q = new URLSearchParams(location.search);
const W = Math.round(Number(q.get('w')) || 960);
const H = Math.round(Number(q.get('h')) || 540);
const RAW = q.get('raw') === '1';
const NOINK = q.get('noink') === '1';

const canvas = document.querySelector('#view');
const renderer = new THREE.WebGLRenderer({
  canvas, antialias: false, preserveDrawingBuffer: true,
  powerPreference: 'high-performance', alpha: false,
});
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
renderer.setClearColor(0x000000, 0);

const gl = renderer.getContext();
const dbg = gl.getExtension('WEBGL_debug_renderer_info');
window.__gpu = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera();
const city = buildCity(scene, LOOP_MS);
const comp = makeComposite(W, H);
comp.uniforms.uNoInk.value = NOINK ? 1 : 0;

const rtOpt = {
  minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
  format: THREE.RGBAFormat, type: THREE.UnsignedByteType,
  depthBuffer: true, stencilBuffer: false,
};
const rtColor = new THREE.WebGLRenderTarget(W, H, rtOpt);
const rtGeo = new THREE.WebGLRenderTarget(W, H, rtOpt);
const rtComp = new THREE.WebGLRenderTarget(W, H, rtOpt);
const rtAcc = new THREE.WebGLRenderTarget(W, H, rtOpt);

const geoMat = new THREE.ShaderMaterial({
  vertexShader: GEO_VERT, fragmentShader: GEO_FRAG, side: THREE.DoubleSide,
});

const quadCam = new THREE.Camera();
const accScene = new THREE.Scene();
const accMat = new THREE.MeshBasicMaterial({
  map: rtComp.texture, transparent: true, opacity: 1,
  blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false,
});
accScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), accMat));
const blitScene = new THREE.Scene();
const blitMat = new THREE.ShaderMaterial({
  uniforms: {
    tSrc: { value: rtAcc.texture }, tRaw: { value: rtColor.texture },
    uRaw: { value: RAW ? 1 : 0 },
  },
  vertexShader: comp.material.vertexShader,
  fragmentShader: BLIT_FRAG,
  depthTest: false, depthWrite: false,
});
blitScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), blitMat));

const LIGHT_WORLD = new THREE.Vector3(-0.42, 0.76, 0.50).normalize();
const _lv = new THREE.Vector3();
let jitter = [0, 0];
let lastInfo = {};

function drawPasses(ms, jx, jy) {
  const s = sample(ms);
  const rig = applyCamera(camera, s, W / H, W, H, jx, jy);
  city.update(ms, s);

  comp.uniforms.uInvProj.value.copy(camera.projectionMatrixInverse);
  comp.uniforms.uCamMat.value.copy(camera.matrixWorld);
  _lv.copy(LIGHT_WORLD).transformDirection(camera.matrixWorldInverse);
  comp.uniforms.uLightView.value.copy(_lv);
  comp.uniforms.uTime.value = ms / 1000;

  renderer.autoClear = false;
  renderer.setClearColor(0x000000, 0);

  // 1) colour pass: flat unlit illustration colours + additive light fx
  camera.layers.enable(0);
  camera.layers.enable(1);
  renderer.setRenderTarget(rtColor);
  renderer.clear(true, true, true);
  renderer.render(scene, camera);

  // 2) geometry pass: view normals + linear depth; fx excluded
  scene.overrideMaterial = geoMat;
  camera.layers.set(0);
  renderer.setRenderTarget(rtGeo);
  renderer.clear(true, true, true);
  renderer.render(scene, camera);
  camera.layers.enable(1);
  scene.overrideMaterial = null;

  // 3) ink composite
  comp.uniforms.tColor.value = rtColor.texture;
  comp.uniforms.tGeo.value = rtGeo.texture;
  renderer.setRenderTarget(rtComp);
  renderer.clear(true, true, true);
  renderer.render(comp.scene, comp.cam);

  lastInfo = {
    fov: +s.fov.toFixed(2), dist: +rig.dist.toFixed(1),
    H: +s.H.toFixed(2), yaw: +s.yaw.toFixed(1), lay: +s.lay.toFixed(2),
  };
}

function accumulate(list) {
  const k = Math.max(1, list.length);
  renderer.autoClear = false;
  renderer.setRenderTarget(rtAcc);
  renderer.setClearColor(0x000000, 1);
  renderer.clear(true, true, true);
  for (let i = 0; i < k; i++) {
    const [ms, jx, jy] = list[i];
    drawPasses(ms, jx || 0, jy || 0);
    accMat.opacity = 1 / k;
    renderer.setRenderTarget(rtAcc);
    renderer.render(accScene, quadCam);
  }
  blitMat.uniforms.tSrc.value = rtAcc.texture;
  blitMat.uniforms.tRaw.value = rtColor.texture;
  renderer.setRenderTarget(null);
  renderer.setClearColor(0x000000, 1);
  renderer.clear(true, true, true);
  renderer.render(blitScene, quadCam);
}

window.setJitter = (x, y) => { jitter = [x, y]; };
window.render = (ms) => { accumulate([[ms, jitter[0], jitter[1]]]); return lastInfo; };
window.renderMany = (list) => { accumulate(list); return lastInfo; };
window.probe = (ms) => {
  const s = sample(ms);
  applyCamera(camera, s, W / H, W, H);
  camera.updateMatrixWorld(true);
  const v = new THREE.Vector3();
  return PROBE_POINTS.map((p) => {
    v.set(p[0], p[1], p[2]).project(camera);
    return [(v.x * 0.5 + 0.5) * W, (0.5 - v.y * 0.5) * H, v.z > -1 && v.z < 1 ? 1 : 0];
  });
};
window.rigInfo = () => lastInfo;
window.READY = true;
window.render(0);
