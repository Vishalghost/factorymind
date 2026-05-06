import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Grid, Html, RoundedBox, Float } from "@react-three/drei";
import * as THREE from "three";
import type { Machine } from "@/lib/mockData";

const STATUS_COLOR: Record<Machine["status"], string> = {
  running: "#16a34a",
  warning: "#f59e0b",
  critical: "#dc2626",
  idle: "#94a3b8",
};

function MachineMesh({ m, onSelect, selected }: { m: Machine; onSelect: (id: string) => void; selected: boolean }) {
  const ref = useRef<THREE.Group>(null);
  const color = STATUS_COLOR[m.status];
  useFrame((_, dt) => {
    if (!ref.current) return;
    if (m.status === "running") ref.current.rotation.y += dt * 0.3;
    if (m.status === "critical") {
      const s = 1 + Math.sin(performance.now() / 200) * 0.04;
      ref.current.scale.setScalar(s);
    }
  });

  return (
    <group position={m.position} onClick={(e) => { e.stopPropagation(); onSelect(m.id); }}>
      <group ref={ref}>
        <RoundedBox args={[1.2, 1.2, 1.2]} radius={0.08} smoothness={4} castShadow receiveShadow>
          <meshStandardMaterial color={color} metalness={0.4} roughness={0.35} />
        </RoundedBox>
        <mesh position={[0, 0.85, 0]}>
          <cylinderGeometry args={[0.15, 0.2, 0.4, 16]} />
          <meshStandardMaterial color="#475569" metalness={0.7} roughness={0.3} />
        </mesh>
        <mesh position={[0, 1.15, 0]}>
          <sphereGeometry args={[0.12, 16, 16]} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={m.status === "critical" ? 1.2 : 0.4} />
        </mesh>
      </group>
      {selected && (
        <Html position={[0, 1.8, 0]} center distanceFactor={8}>
          <div className="rounded-lg border border-border bg-card/95 px-3 py-2 text-xs shadow-lg backdrop-blur whitespace-nowrap">
            <div className="font-semibold">{m.name}</div>
            <div className="text-muted-foreground">{m.id} · Health {m.health}%</div>
          </div>
        </Html>
      )}
    </group>
  );
}

export function DigitalTwin3D({ machines, selectedId, onSelect }: { machines: Machine[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const fogColor = useMemo(() => new THREE.Color("#ffffff"), []);
  return (
    <Canvas shadows camera={{ position: [6, 5, 6], fov: 45 }} style={{ background: "white" }}>
      <fog attach="fog" args={[fogColor, 12, 25]} />
      <ambientLight intensity={0.7} />
      <directionalLight position={[5, 8, 5]} intensity={1.1} castShadow shadow-mapSize={[1024, 1024]} />
      <directionalLight position={[-5, 4, -5]} intensity={0.4} color="#a5b4fc" />

      {/* Floor */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.61, 0]} receiveShadow>
        <planeGeometry args={[40, 40]} />
        <meshStandardMaterial color="#f8fafc" />
      </mesh>
      <Grid
        position={[0, -0.6, 0]}
        args={[20, 20]}
        cellSize={0.5}
        cellThickness={0.5}
        cellColor="#cbd5e1"
        sectionSize={2}
        sectionThickness={1}
        sectionColor="#6366f1"
        fadeDistance={20}
        fadeStrength={1}
        infiniteGrid
      />

      {/* Production line strips */}
      {[-2, 1].map((z) => (
        <mesh key={z} position={[0, -0.59, z]} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[8, 1.6]} />
          <meshStandardMaterial color="#e0e7ff" />
        </mesh>
      ))}

      {machines.map((m) => (
        <MachineMesh key={m.id} m={m} onSelect={onSelect} selected={selectedId === m.id} />
      ))}

      <Float speed={1.5} rotationIntensity={0} floatIntensity={0.5}>
        <Html position={[0, 3.5, 0]} center>
          <div className="rounded-full border border-border bg-card/80 px-3 py-1 text-[10px] font-mono uppercase tracking-wider text-muted-foreground backdrop-blur">
            Live Twin · {machines.length} assets
          </div>
        </Html>
      </Float>

      <OrbitControls enablePan minDistance={4} maxDistance={20} maxPolarAngle={Math.PI / 2.1} />
    </Canvas>
  );
}
