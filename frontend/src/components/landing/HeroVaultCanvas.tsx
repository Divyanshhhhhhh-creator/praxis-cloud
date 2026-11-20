"use client";

/**
 * "The Sovereign AI Treasury Vault" — native three.js (no R3F).
 * Faceted metallic core + counter-rotating titanium / indigo gyroscope rings, emerald/cyan
 * transaction orbs streaming through the core, crimson threat nodes deflecting off the outer
 * firewall perimeter. Mouse parallax, 60fps, pauses off-screen, full disposal on unmount,
 * CSS-3D fallback when WebGL is unavailable.
 */

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { cn } from "@/lib/format";

const TX_COUNT = 150;
const THREAT_COUNT = 12;
const FIREWALL_RADIUS = 2.95;

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(window.WebGLRenderingContext && (canvas.getContext("webgl2") || canvas.getContext("webgl")));
  } catch {
    return false;
  }
}

function makeGlowTexture(): THREE.CanvasTexture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.22, "rgba(255,255,255,0.85)");
  g.addColorStop(0.5, "rgba(255,255,255,0.22)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export default function HeroVaultCanvas({ className }: { className?: string }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    if (!webglAvailable()) {
      setFallback(true);
      return;
    }

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setFallback(true);
      return;
    }

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const speed = reduceMotion ? 0.15 : 1;

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";
    renderer.domElement.setAttribute("aria-hidden", "true");
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    camera.position.set(0, 0.35, 10.2);

    // Image-based lighting for believable brushed-metal reflections
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const envTexture = pmrem.fromScene(room, 0.04).texture;
    scene.environment = envTexture;
    room.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      mesh.geometry?.dispose();
      const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat?.dispose();
    });

    // 3-point coloured lighting
    scene.add(new THREE.AmbientLight(0x1b2140, 0.7));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(2.5, 5, 6);
    const indigo = new THREE.PointLight(0x4f46e5, 70, 0, 2);
    indigo.position.set(-4.5, 3, 4);
    const cyan = new THREE.PointLight(0x06b6d4, 55, 0, 2);
    cyan.position.set(4.8, -1.2, 3.2);
    const emerald = new THREE.PointLight(0x10b981, 30, 0, 2);
    emerald.position.set(0, -4.2, 2.2);
    scene.add(key, indigo, cyan, emerald);

    const parallax = new THREE.Group(); // pointer-driven tilt
    const vault = new THREE.Group(); // continuous rotation
    parallax.add(vault);
    scene.add(parallax);

    // Faceted dark-metal core
    const coreGeo = new THREE.IcosahedronGeometry(1.08, 1);
    const coreMat = new THREE.MeshPhysicalMaterial({
      color: 0x0d1424,
      metalness: 0.95,
      roughness: 0.2,
      clearcoat: 1,
      clearcoatRoughness: 0.12,
      flatShading: true,
      envMapIntensity: 1.3,
    });
    const core = new THREE.Mesh(coreGeo, coreMat);
    vault.add(core);

    // Glass shell wireframe
    const shellGeo = new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1.42, 1));
    const shellMat = new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.28 });
    const shell = new THREE.LineSegments(shellGeo, shellMat);
    vault.add(shell);

    // Inner energy glow
    const glowTex = makeGlowTexture();
    const coreGlow = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: glowTex, color: 0x6366f1, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    coreGlow.scale.setScalar(4.2);
    parallax.add(coreGlow);

    // Gyroscope firewall rings
    const ringAGeo = new THREE.TorusGeometry(2.05, 0.055, 32, 240);
    const ringAMat = new THREE.MeshPhysicalMaterial({ color: 0xa9b3c2, metalness: 1, roughness: 0.32, clearcoat: 0.6, envMapIntensity: 1.4 });
    const ringA = new THREE.Mesh(ringAGeo, ringAMat);
    ringA.rotation.x = Math.PI / 2.35;
    vault.add(ringA);

    const ringBGeo = new THREE.TorusGeometry(2.5, 0.026, 20, 280);
    const ringBMat = new THREE.MeshStandardMaterial({ color: 0x4f46e5, emissive: 0x4f46e5, emissiveIntensity: 2.2, metalness: 0.4, roughness: 0.35 });
    const ringB = new THREE.Mesh(ringBGeo, ringBMat);
    ringB.rotation.y = Math.PI / 2.6;
    vault.add(ringB);

    const perimeterGeo = new THREE.TorusGeometry(FIREWALL_RADIUS, 0.01, 8, 320);
    const perimeterMat = new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.35 });
    const perimeter = new THREE.Mesh(perimeterGeo, perimeterMat);
    parallax.add(perimeter);

    // Transaction stream (emerald / cyan orbs funnelled through the core)
    const txGeo = new THREE.BufferGeometry();
    const txPos = new Float32Array(TX_COUNT * 3);
    const txCol = new Float32Array(TX_COUNT * 3);
    const txSeed = Array.from({ length: TX_COUNT }, () => ({
      phase: Math.random(),
      speed: 0.045 + Math.random() * 0.05,
      y0: (Math.random() - 0.5) * 5.2,
      z0: (Math.random() - 0.5) * 3.2,
    }));
    const emeraldC = new THREE.Color(0x34d399);
    const cyanC = new THREE.Color(0x22d3ee);
    txSeed.forEach((_, i) => {
      const c = i % 3 === 0 ? cyanC : emeraldC;
      txCol.set([c.r, c.g, c.b], i * 3);
    });
    txGeo.setAttribute("position", new THREE.BufferAttribute(txPos, 3));
    txGeo.setAttribute("color", new THREE.BufferAttribute(txCol, 3));
    const txMat = new THREE.PointsMaterial({
      size: 0.16,
      map: glowTex,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });
    const tx = new THREE.Points(txGeo, txMat);
    parallax.add(tx);

    // Crimson threat nodes deflecting off the firewall perimeter
    const threats = Array.from({ length: THREAT_COUNT }, (_, i) => {
      const mat = new THREE.SpriteMaterial({ map: glowTex, color: 0xef4444, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
      const sprite = new THREE.Sprite(mat);
      parallax.add(sprite);
      return {
        sprite,
        mat,
        angle: (i / THREAT_COUNT) * Math.PI * 2 + Math.random() * 0.4,
        phase: Math.random(),
        speed: 0.12 + Math.random() * 0.08,
        z: (Math.random() - 0.5) * 0.6,
      };
    });
    const impactFlashes = threats.map(() => {
      const mat = new THREE.SpriteMaterial({ map: glowTex, color: 0xf87171, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
      const s = new THREE.Sprite(mat);
      parallax.add(s);
      return { sprite: s, mat };
    });

    // Sizing
    const resize = () => {
      const { clientWidth: w, clientHeight: h } = mount;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.position.z = w / h < 0.9 ? 12.8 : 10.2;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(mount);
    resize();

    // Pointer parallax
    const pointer = { x: 0, y: 0 };
    const onPointer = (e: PointerEvent) => {
      pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    // Only render while visible
    let visible = true;
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
    });
    io.observe(mount);

    const timer = new THREE.Timer();
    let raf = 0;
    let t = 0;
    const tick = (timestamp?: number) => {
      raf = requestAnimationFrame(tick);
      timer.update(timestamp);
      const dt = Math.min(timer.getDelta(), 0.05);
      if (!visible || document.visibilityState !== "visible") return;
      t += dt * speed;

      vault.rotation.y += 0.16 * dt * speed;
      core.rotation.x += 0.22 * dt * speed;
      ringA.rotation.z += 0.45 * dt * speed;
      ringB.rotation.x -= 0.32 * dt * speed;
      shell.rotation.y -= 0.1 * dt * speed;
      coreGlow.material.opacity = 0.62 + Math.sin(t * 2.2) * 0.12;

      parallax.rotation.y += (pointer.x * 0.38 - parallax.rotation.y) * 0.05;
      parallax.rotation.x += (pointer.y * 0.22 - parallax.rotation.x) * 0.05;

      // transactions: x sweeps -6 → 6, y/z collapse to 0 at the core (funnel)
      for (let i = 0; i < TX_COUNT; i++) {
        const s = txSeed[i];
        s.phase = (s.phase + s.speed * dt * speed) % 1;
        const x = -6 + 12 * s.phase;
        const f = 1 - Math.exp(-(x * x) / 1.7);
        txPos[i * 3] = x;
        txPos[i * 3 + 1] = s.y0 * f + Math.sin(t * 1.3 + i) * 0.04;
        txPos[i * 3 + 2] = s.z0 * f;
      }
      txGeo.attributes.position.needsUpdate = true;

      // threats: approach the perimeter, impact, deflect outwards
      threats.forEach((th, i) => {
        th.phase = (th.phase + th.speed * dt * speed) % 1;
        const v = Math.abs(1 - 2 * th.phase); // 1 → 0 (impact) → 1
        const r = FIREWALL_RADIUS + 0.12 + 3.6 * Math.pow(v, 1.15);
        const a = th.angle + t * 0.05;
        th.sprite.position.set(Math.cos(a) * r, Math.sin(a) * r, th.z);
        const pulse = 0.34 + Math.sin(t * 6 + i) * 0.06;
        th.sprite.scale.setScalar(pulse + (1 - v) * 0.25);
        th.mat.opacity = Math.min(1, 0.35 + (1 - v) * 0.9);

        const flash = impactFlashes[i];
        const impact = Math.max(0, 1 - v / 0.12);
        flash.sprite.position.set(Math.cos(a) * FIREWALL_RADIUS, Math.sin(a) * FIREWALL_RADIUS, th.z);
        flash.sprite.scale.setScalar(0.4 + impact * 1.1);
        flash.mat.opacity = impact * 0.85;
      });
      perimeterMat.opacity = 0.28 + Math.sin(t * 1.6) * 0.06;

      renderer.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(raf);
      timer.dispose();
      window.removeEventListener("pointermove", onPointer);
      ro.disconnect();
      io.disconnect();
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        mesh.geometry?.dispose();
        const mat = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose();
      });
      glowTex.dispose();
      envTexture.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div className={cn("relative h-full w-full", className)}>
      <div ref={mountRef} className="absolute inset-0" />
      {fallback && <VaultFallback />}
    </div>
  );
}

/** Animated CSS-3D stand-in when WebGL is unavailable. */
function VaultFallback() {
  return (
    <div className="absolute inset-0 grid place-items-center [perspective:900px]" aria-hidden="true">
      <div className="relative size-72 [transform-style:preserve-3d] [transform:rotateX(62deg)]">
        <div className="absolute inset-0 rounded-full border-[3px] border-slate-400/60 animate-spin-slow" />
        <div className="absolute inset-6 rounded-full border-2 border-indigo-500/80 shadow-[0_0_40px_#4f46e5] animate-spin-reverse" />
        <div className="absolute -inset-8 rounded-full border border-cyan-400/40 animate-spin-slower" />
      </div>
      <div className="absolute size-28 rotate-45 rounded-2xl bg-linear-to-br from-slate-700 via-slate-900 to-black shadow-[0_0_80px_#4f46e5aa] ring-1 ring-white/10" />
    </div>
  );
}
