import { Suspense, useEffect, useRef, useState } from "react";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { OrbitControls, Environment, Bounds, useBounds } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Box3, Vector3, Mesh, WebGLRenderer } from "three";
import { Camera, Loader2, Maximize2, RotateCcw } from "lucide-react";

// ---------------------------------------------------------------------------
// Inner mesh — loads the STL, auto-centers, auto-scales, fits camera
// ---------------------------------------------------------------------------
function STLMesh({ url }: { url: string }) {
  const geometry = useLoader(STLLoader, url);
  const meshRef = useRef<Mesh>(null);
  const bounds = useBounds();
  const { invalidate } = useThree();

  useEffect(() => {
    if (!geometry || !meshRef.current) return;

    // Center geometry at origin
    geometry.computeBoundingBox();
    const box = new Box3().setFromObject(meshRef.current);
    const center = new Vector3();
    box.getCenter(center);
    geometry.translate(-center.x, -center.y, -center.z);

    // Scale so longest axis = 2 units
    const size = new Vector3();
    box.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);
    if (maxDim > 0) meshRef.current.scale.setScalar(2 / maxDim);

    // Fit camera — Bounds handles the math and properly syncs OrbitControls
    bounds.refresh().fit();
    invalidate();
  }, [geometry]);

  return (
    <mesh ref={meshRef} geometry={geometry} castShadow receiveShadow>
      <meshStandardMaterial color="#a0a8c0" roughness={0.4} metalness={0.3} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Error boundary for loader failures
// ---------------------------------------------------------------------------
import { Component, ReactNode } from "react";

class LoaderErrorBoundary extends Component<
  { children: ReactNode; onError: (msg: string) => void },
  { hasError: boolean }
> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: Error) {
    this.props.onError(error.message);
  }
  render() {
    return this.state.hasError ? null : this.props.children;
  }
}

// ---------------------------------------------------------------------------
// File picker — let the user choose which STL to preview
// ---------------------------------------------------------------------------
interface STLFile {
  id: number;
  filename: string;
  path: string;
  size_bytes: number | null;
}

interface Props {
  files: STLFile[];
  getUrl: (path: string) => string;
  modelId?: number;
  onThumbnailCaptured?: () => void;
}

const SIZE_WARN_MB = 50;

export default function STLViewer({ files, getUrl, modelId, onThumbnailCaptured }: Props) {
  const stlFiles = files.filter((f) =>
    [".stl", ".STL"].some((ext) => f.filename.endsWith(ext))
  );

  const [selected, setSelected] = useState<STLFile | null>(
    stlFiles[0] ?? null
  );
  const [key, setKey] = useState(0); // force remount on file change
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const controlsRef = useRef<any>(null);
  const glRef = useRef<WebGLRenderer | null>(null);

  const handleCapture = () => {
    if (!glRef.current || !modelId) return;
    setCapturing(true);
    glRef.current.domElement.toBlob(async (blob) => {
      if (!blob) { setCapturing(false); return; }
      try {
        const form = new FormData();
        form.append("file", blob, "capture.png");
        await fetch(`/api/models/${modelId}/thumbnail/upload`, { method: "POST", body: form });
        onThumbnailCaptured?.();
      } finally {
        setCapturing(false);
      }
    }, "image/png");
  };

  if (stlFiles.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 bg-gray-900 rounded-xl text-gray-600 text-sm">
        No STL files in this model
      </div>
    );
  }

  const sizeMB = selected?.size_bytes
    ? selected.size_bytes / 1024 / 1024
    : null;
  const isLarge = sizeMB !== null && sizeMB > SIZE_WARN_MB;

  const containerClass = fullscreen
    ? "fixed inset-0 z-50 bg-gray-950 flex flex-col"
    : "flex flex-col gap-2";

  return (
    <div className={containerClass}>
      {/* File selector */}
      {stlFiles.length > 1 && (
        <div className="flex gap-1.5 flex-wrap px-1">
          {stlFiles.map((f) => (
            <button
              key={f.id}
              onClick={() => {
                setSelected(f);
                setError(null);
                setKey((k) => k + 1);
              }}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors truncate max-w-[180px] ${
                selected?.id === f.id
                  ? "bg-indigo-600 border-indigo-500 text-white"
                  : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500"
              }`}
              title={f.filename}
            >
              {f.filename}
            </button>
          ))}
        </div>
      )}

      {/* Large file warning */}
      {isLarge && (
        <p className="text-xs text-amber-400 bg-amber-950/40 border border-amber-800 rounded px-3 py-1.5 mx-1">
          Large file ({sizeMB!.toFixed(0)} MB) — may be slow to load in browser
        </p>
      )}

      {/* Viewer canvas */}
      {selected && (
        <div
          className={`relative bg-gray-900 rounded-xl overflow-hidden ${
            fullscreen ? "flex-1" : "aspect-square"
          }`}
        >
          {error ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-500 gap-2 text-sm">
              <p>Failed to load STL</p>
              <p className="text-xs text-gray-600">{error}</p>
              <button
                onClick={() => { setError(null); setKey((k) => k + 1); }}
                className="text-xs px-3 py-1 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 mt-1"
              >
                Retry
              </button>
            </div>
          ) : (
            <Canvas
              key={key}
              shadows
              frameloop="demand"
              camera={{ position: [4, 3, 4], fov: 45 }}
              gl={{ antialias: true, powerPreference: "low-power", preserveDrawingBuffer: true }}
              onCreated={({ gl }) => {
                glRef.current = gl;
                // Let the browser recover a lost context instead of leaving a
                // dead canvas. Without preventDefault the context can't be
                // restored, and rapid navigation between model pages exhausts
                // the browser's WebGL context limit ("THREE.WebGLRenderer:
                // Context Lost").
                gl.domElement.addEventListener("webglcontextlost", (e) =>
                  e.preventDefault()
                );
              }}
            >
              <color attach="background" args={["#111318"]} />
              <ambientLight intensity={0.5} />
              <directionalLight position={[5, 10, 5]} intensity={1.2} castShadow />
              <directionalLight position={[-5, -5, -5]} intensity={0.3} />

              <Bounds margin={1.4}>
                <LoaderErrorBoundary onError={setError}>
                  <Suspense fallback={null}>
                    <STLMesh url={getUrl(selected.path)} />
                    <Environment preset="city" />
                  </Suspense>
                </LoaderErrorBoundary>
              </Bounds>

              <OrbitControls
                ref={controlsRef}
                makeDefault
                enableDamping
                dampingFactor={0.08}
                // Clamp dolly: the mesh is normalized to ~2 units and Bounds frames
                // it at ~3-4 units, so these bracket the fitted view. Without them
                // the user can zoom through the model (origin) or out to a vanishing
                // dot — Bounds only sets maxDistance via clip(), which we don't use.
                minDistance={0.5}
                maxDistance={50}
              />
            </Canvas>
          )}

          {/* Canvas overlay controls */}
          <div className="absolute top-2 right-2 flex gap-1.5">
            <button
              onClick={() => controlsRef.current?.reset()}
              title="Reset camera"
              className="p-1.5 rounded bg-black/50 hover:bg-black/70 text-gray-400 hover:text-gray-200 transition-colors"
            >
              <RotateCcw size={13} />
            </button>
            {modelId && (
              <button
                onClick={handleCapture}
                disabled={capturing}
                title="Use current view as thumbnail"
                className="p-1.5 rounded bg-black/50 hover:bg-black/70 text-gray-400 hover:text-gray-200 disabled:opacity-50 transition-colors"
              >
                {capturing
                  ? <Loader2 size={13} className="animate-spin" />
                  : <Camera size={13} />}
              </button>
            )}
            <button
              onClick={() => setFullscreen(!fullscreen)}
              title={fullscreen ? "Exit fullscreen" : "Fullscreen"}
              className="p-1.5 rounded bg-black/50 hover:bg-black/70 text-gray-400 hover:text-gray-200 transition-colors"
            >
              <Maximize2 size={13} />
            </button>
          </div>

          {/* Loading overlay */}
          <div
            id={`stl-loading-${selected.id}`}
            className="absolute inset-0 flex items-center justify-center pointer-events-none"
          >
            <Suspense
              fallback={
                <div className="text-gray-600 text-sm animate-pulse">
                  Loading…
                </div>
              }
            >
              <></>
            </Suspense>
          </div>
        </div>
      )}

      <p className="text-xs text-gray-700 px-1">
        Drag to rotate · Scroll to zoom · Right-drag to pan
      </p>
    </div>
  );
}
