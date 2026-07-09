import { Component, ReactNode, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { TrackballControls, Environment } from "@react-three/drei";
import type { TrackballControls as TrackballControlsImpl } from "three-stdlib";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Box3, Vector3, Mesh, PerspectiveCamera, WebGLRenderer } from "three";
import { Camera, ChevronDown, ChevronRight, Loader2, Maximize2, RotateCcw } from "lucide-react";

// ---------------------------------------------------------------------------
// Inner mesh — loads the STL, auto-centers, auto-scales, fits camera
// ---------------------------------------------------------------------------
function STLMesh({ url }: { url: string }) {
  const geometry = useLoader(STLLoader, url);
  const meshRef = useRef<Mesh>(null);
  const { camera, controls, invalidate } = useThree();

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

    // Fit camera to the bounding sphere of the scaled mesh. Distance that makes
    // the sphere exactly fill the vertical FOV, times a small margin for breathing
    // room. Place the camera at EXACTLY `dist` along a normalized diagonal — a raw
    // (0.8,0.6,1) offset is ~1.4x longer, which (with the margin) pushed the model
    // ~2x too far away so it didn't fill the viewer.
    meshRef.current.geometry.computeBoundingSphere();
    const radius = (meshRef.current.geometry.boundingSphere?.radius ?? 1) *
      (2 / maxDim);
    const pc = camera as PerspectiveCamera;
    const fitDist = radius / Math.sin(((pc.fov ?? 45) * Math.PI) / 360);
    const dist = fitDist * 1.3;
    camera.position.copy(new Vector3(0.8, 0.6, 1).normalize().multiplyScalar(dist));
    pc.near = dist / 100;
    pc.far = dist * 100;
    camera.lookAt(0, 0, 0);
    pc.updateProjectionMatrix();

    // Center the controls on the model and give a generous, model-relative dolly
    // range so zoom in/out always has room — a fixed maxDistance can sit right at
    // the fit distance and silently block zoom-out. TrackballControls imposes no
    // polar limit, so the model rotates freely in every direction.
    if (controls) {
      const c = controls as { target?: { set?: (...a: number[]) => void }; minDistance?: number; maxDistance?: number; update?: () => void };
      c.target?.set?.(0, 0, 0);
      c.minDistance = dist * 0.1;
      c.maxDistance = dist * 25;
      c.update?.();
    }

    invalidate();
  }, [geometry, controls, camera, invalidate]);

  return (
    <mesh ref={meshRef} geometry={geometry} castShadow receiveShadow>
      <meshStandardMaterial color="#a0a8c0" roughness={0.4} metalness={0.3} />
    </mesh>
  );
}

// ---------------------------------------------------------------------------
// Error boundary for loader failures
// ---------------------------------------------------------------------------
class LoaderErrorBoundary extends Component<
  { children: ReactNode; onError: (msg: string) => void },
  { hasError: boolean }
> {
  constructor(props: { children: ReactNode; onError: (msg: string) => void }) {
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
// Types
// ---------------------------------------------------------------------------
interface STLFile {
  id: number;
  filename: string;
  path: string;
  size_bytes: number | null;
  part_type?: string | null;
  sup_of_id?: number | null;
}

interface Props {
  files: STLFile[];
  getUrl: (path: string, version?: string | number | null) => string;
  modelId?: number;
  onThumbnailCaptured?: () => void;
  categoriesEnabled?: boolean;
  selectedFileId?: number;
  onSelectFile?: (id: number) => void;
  hidePicker?: boolean;
}

// ---------------------------------------------------------------------------
// Category + support-pair utilities
// ---------------------------------------------------------------------------

const toPascalCase = (s: string): string =>
  s.trim().split(/\s+/).filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");

/**
 * Returns the display category for a file. Uses the assigned part_type when
 * present (already stored as Pascal case); otherwise derives from the filename
 * prefix and Pascal-cases the result.
 */
function extractCategory(file: STLFile): string {
  if (file.part_type) return file.part_type;
  const base = file.filename
    .replace(/\.(stl|STL)$/, "")
    .replace(/^Sup_/i, "");
  return toPascalCase(base.split("_")[0] || "Other");
}

/**
 * Builds a human-readable label for a part button within its category.
 * When the category came from a part_type label the filename prefix won't
 * match, so we just show the full name minus extension. Otherwise strip the
 * leading category token so "Head_3.stl" in the "Head" group shows as "3".
 */
function partLabel(file: STLFile, category: string): string {
  const withoutExt = file.filename.replace(/\.(stl|STL)$/, "");
  const withoutSup = withoutExt.replace(/^Sup_/i, "");
  if (file.part_type) return withoutSup.replace(/_/g, " ");
  const escapedCat = category.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const withoutCat = withoutSup.replace(new RegExp(`^${escapedCat}_?`, "i"), "");
  return (withoutCat || withoutSup).replace(/_/g, " ");
}

/**
 * Detects supported-variant relationships within the file list.
 * Returns base files (sup variants removed from the flat list) and a map from
 * base file id → ordered list of all its sup variants (may be more than one).
 * Explicit sup_of_id takes priority; Sup_X.stl / X.stl filename pattern is a
 * fallback for files not yet explicitly linked.
 */
function buildPairs(files: STLFile[]): {
  baseFiles: STLFile[];
  supMap: Map<number, STLFile[]>;
} {
  const byId = new Map(files.map((f) => [f.id, f]));
  const byFilename = new Map(files.map((f) => [f.filename, f]));
  const supMap = new Map<number, STLFile[]>();
  const supIds = new Set<number>();

  // Explicit sup_of_id relationships take priority.
  for (const f of files) {
    if (f.sup_of_id != null && byId.has(f.sup_of_id)) {
      if (!supMap.has(f.sup_of_id)) supMap.set(f.sup_of_id, []);
      supMap.get(f.sup_of_id)!.push(f);
      supIds.add(f.id);
    }
  }

  // Filename pattern fallback for files not yet explicitly linked.
  for (const f of files) {
    if (supIds.has(f.id)) continue;
    if (/^Sup_/i.test(f.filename)) {
      const baseName = f.filename.replace(/^Sup_/i, "");
      const base = byFilename.get(baseName);
      if (base) {
        if (!supMap.has(base.id)) supMap.set(base.id, []);
        supMap.get(base.id)!.push(f);
        supIds.add(f.id);
      }
    }
  }

  return { baseFiles: files.filter((f) => !supIds.has(f.id)), supMap };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
const SIZE_WARN_MB = 50;

export default function STLViewer({ files, getUrl, modelId, onThumbnailCaptured, categoriesEnabled = false, selectedFileId, onSelectFile, hidePicker = false }: Props) {
  const stlFiles = files.filter((f) =>
    [".stl", ".STL"].some((ext) => f.filename.endsWith(ext))
  );

  const { baseFiles, supMap } = useMemo(() => buildPairs(stlFiles), [stlFiles]);

  const categories = useMemo(() => {
    const map = new Map<string, STLFile[]>();
    for (const f of baseFiles) {
      const cat = extractCategory(f);
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(f);
    }
    return map;
  }, [baseFiles]);

  const categoryKeys = useMemo(
    () => Array.from(categories.keys()).sort(),
    [categories],
  );

  const [selected, setSelected] = useState<STLFile | null>(stlFiles[0] ?? null);
  const [key, setKey] = useState(0); // force remount on file change
  const [error, setError] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [capturing, setCapturing] = useState(false);
  // Map of base-file ID → the active sup variant's ID. Absent = base is shown.
  const [, setSupEnabled] = useState<Map<number, number>>(new Map());
  // All categories except the first start collapsed
  const [collapsed, setCollapsed] = useState<Set<string>>(
    () => new Set(categoryKeys.slice(1)),
  );
  const controlsRef = useRef<TrackballControlsImpl | null>(null);
  const glRef = useRef<WebGLRenderer | null>(null);
  // Stable handler identity (STUDIO-95) so the cleanup effect below can remove
  // exactly the listener onCreated attached — an inline arrow function can't
  // be passed to removeEventListener.
  const onContextLost = useRef((e: Event) => e.preventDefault()).current;
  useEffect(() => {
    return () => glRef.current?.domElement.removeEventListener("webglcontextlost", onContextLost);
  }, [onContextLost]);

  // Sync from external selection (file list → viewer): update state, unfold category, scroll picker.
  useEffect(() => {
    if (selectedFileId === undefined) return;
    let pickerBaseId: number | null = null;

    const base = baseFiles.find((f) => f.id === selectedFileId);
    if (base) {
      setSelected(base);
      setSupEnabled((prev) => { const n = new Map(prev); n.delete(base.id); return n; });
      setKey((k) => k + 1);
      setError(null);
      pickerBaseId = base.id;
    } else {
      for (const bf of baseFiles) {
        const sups = supMap.get(bf.id) ?? [];
        const supFile = sups.find((s) => s.id === selectedFileId);
        if (supFile) {
          setSelected(supFile);
          setSupEnabled((prev) => new Map([...prev, [bf.id, supFile.id]]));
          setKey((k) => k + 1);
          setError(null);
          pickerBaseId = bf.id;
          break;
        }
      }
    }

    if (pickerBaseId !== null) {
      const pickerBase = baseFiles.find((f) => f.id === pickerBaseId);
      if (pickerBase) {
        // Unfold the category that contains this part.
        setCollapsed((prev) => { const n = new Set(prev); n.delete(extractCategory(pickerBase)); return n; });
      }
      // Scroll the part button group into view after the fold state updates.
      const id = pickerBaseId;
      requestAnimationFrame(() => {
        document.querySelector(`[data-picker-id="${id}"]`)
          ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    }
  // baseFiles/supMap are excluded: stlFiles is computed inline so they'd change
  // every render, but this effect must only fire on external selection changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFileId]);

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

  // Load the base variant of a file (deactivates any active sup for it).
  const selectBase = (f: STLFile) => {
    setSelected(f);
    setSupEnabled((prev) => { const n = new Map(prev); n.delete(f.id); return n; });
    setError(null);
    setKey((k) => k + 1);
    onSelectFile?.(f.id);
  };

  // Load a specific sup variant for a base file.
  const selectSup = (base: STLFile, sup: STLFile) => {
    setSelected(sup);
    setSupEnabled((prev) => new Map([...prev, [base.id, sup.id]]));
    setError(null);
    setKey((k) => k + 1);
    onSelectFile?.(sup.id);
  };

  // A base button is "active" if the base itself or any of its sups is currently shown.
  const isActive = (f: STLFile) => {
    if (selected?.id === f.id) return true;
    return (supMap.get(f.id) ?? []).some((s) => s.id === selected?.id);
  };

  const toggleCollapse = (cat: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat); else next.add(cat);
      return next;
    });

  const allCollapsed = categoryKeys.length > 0 && categoryKeys.every((k) => collapsed.has(k));
  const toggleAll = () =>
    setCollapsed(allCollapsed ? new Set() : new Set(categoryKeys));

  if (stlFiles.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 bg-gray-900 rounded-xl text-gray-600 text-sm">
        No STL files in this model
      </div>
    );
  }

  const sizeMB = selected?.size_bytes ? selected.size_bytes / 1024 / 1024 : null;
  const isLarge = sizeMB !== null && sizeMB > SIZE_WARN_MB;

  const containerClass = fullscreen
    ? "fixed inset-0 z-50 bg-gray-950 flex flex-col gap-2 overflow-y-auto p-2"
    : "flex flex-col gap-2";

  return (
    <div className={containerClass}>
      {/* 1. Viewer canvas — always at the top */}
      {selected && (
        <div
          className={`relative bg-gray-900 rounded-xl overflow-hidden ${
            fullscreen ? "flex-none h-[60vh]" : "aspect-square"
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
              // TrackballControls update()s every frame and only invalidates on its
              // 'change' event — its wheel handler dispatches start/end, not change,
              // so under frameloop="demand" a scroll never schedules a render and
              // zoom silently stalls. "always" lets the controls run as designed
              // (reliable zoom + smooth damping) for this single mounted viewer.
              frameloop="always"
              camera={{ position: [4, 3, 4], fov: 45 }}
              gl={{ antialias: true, powerPreference: "low-power", preserveDrawingBuffer: true }}
              onCreated={({ gl }) => {
                glRef.current = gl;
                // Let the browser recover a lost context instead of leaving a
                // dead canvas. Without preventDefault the context can't be
                // restored, and rapid navigation between model pages exhausts
                // the browser's WebGL context limit ("THREE.WebGLRenderer:
                // Context Lost").
                gl.domElement.addEventListener("webglcontextlost", onContextLost);
              }}
            >
              <color attach="background" args={["#111318"]} />
              <ambientLight intensity={0.5} />
              <directionalLight position={[5, 10, 5]} intensity={1.2} castShadow />
              <directionalLight position={[-5, -5, -5]} intensity={0.3} />

              <LoaderErrorBoundary onError={setError}>
                <Suspense fallback={null}>
                  <STLMesh url={getUrl(selected.path, selected.size_bytes)} />
                  <Environment preset="city" />
                </Suspense>
              </LoaderErrorBoundary>

              <TrackballControls
                ref={controlsRef}
                makeDefault
                // Free-tumble rotation (no polar clamp, unlike OrbitControls).
                // min/maxDistance are set imperatively from the fit distance in
                // STLMesh so the dolly range scales with each model.
                rotateSpeed={3}
                zoomSpeed={1.2}
                dynamicDampingFactor={0.15}
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
                <div className="text-gray-600 text-sm animate-pulse">Loading…</div>
              }
            >
              <></>
            </Suspense>
          </div>
        </div>
      )}

      {/* Large file warning */}
      {isLarge && (
        <p className="text-xs text-amber-400 bg-amber-950/40 border border-amber-800 rounded px-3 py-1.5 mx-1">
          Large file ({sizeMB!.toFixed(0)} MB) — may be slow to load in browser
        </p>
      )}

      {/* 2. Part picker */}
      {!hidePicker && stlFiles.length > 1 && !categoriesEnabled && (
        <div className="flex gap-1.5 flex-wrap px-1">
          {baseFiles.map((f) => {
            const sups = supMap.get(f.id) ?? [];
            const baseActive = selected?.id === f.id;
            return (
              <div key={f.id} data-picker-id={f.id} className="flex items-stretch">
                <button
                  onClick={() => selectBase(f)}
                  title={f.filename}
                  className={`text-xs px-2.5 py-1 border transition-colors truncate max-w-[180px] ${
                    sups.length > 0 ? "rounded-l-md border-r-0" : "rounded-md"
                  } ${
                    baseActive
                      ? "bg-indigo-600 border-indigo-500 text-white"
                      : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200"
                  }`}
                >
                  {f.filename}
                </button>
                {sups.map((sup, idx) => {
                  const supActive = selected?.id === sup.id;
                  const isLast = idx === sups.length - 1;
                  return (
                    <button
                      key={sup.id}
                      onClick={() => selectSup(f, sup)}
                      title={sup.filename}
                      className={`text-[10px] px-1.5 py-1 border transition-colors ${
                        isLast ? "rounded-r-md" : "border-r-0"
                      } ${
                        supActive
                          ? "bg-indigo-800 border-indigo-600 text-indigo-200 hover:bg-indigo-700"
                          : "bg-transparent border-gray-700 text-gray-600 hover:text-gray-300 hover:border-gray-500"
                      }`}
                    >
                      {sups.length === 1 ? "sup" : `s${idx + 1}`}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
      {!hidePicker && stlFiles.length > 1 && categoriesEnabled && (
        <div className="flex flex-col gap-1">
          {categoryKeys.length > 1 && (
            <div className="flex items-center justify-between px-1 pt-1">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Parts
              </span>
              <button
                onClick={toggleAll}
                className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
              >
                {allCollapsed ? "Expand all" : "Collapse all"}
              </button>
            </div>
          )}

          {categoryKeys.map((cat) => {
            const catFiles = categories.get(cat)!;
            const isOpen = !collapsed.has(cat);
            return (
              <div key={cat} className="border border-gray-800 rounded-lg overflow-hidden">
                {/* Category header */}
                <button
                  onClick={() => toggleCollapse(cat)}
                  className="w-full flex items-center justify-between px-3 py-2 bg-gray-900 hover:bg-gray-800 transition-colors text-left"
                >
                  <span className="text-xs font-medium text-gray-300">{cat}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-600 tabular-nums">{catFiles.length}</span>
                    {isOpen
                      ? <ChevronDown size={12} className="text-gray-500" />
                      : <ChevronRight size={12} className="text-gray-500" />}
                  </div>
                </button>

                {/* Parts within category */}
                {isOpen && (
                  <div className="flex flex-wrap gap-1.5 p-2.5 bg-gray-950">
                    {catFiles.map((f) => {
                      const sups = supMap.get(f.id) ?? [];
                      const baseActive = selected?.id === f.id;
                      const label = partLabel(f, cat);

                      return (
                        <div key={f.id} data-picker-id={f.id} className="flex items-stretch">
                          {/* Base part button */}
                          <button
                            onClick={() => selectBase(f)}
                            title={f.filename}
                            className={`text-xs px-2.5 py-1 border transition-colors truncate max-w-[150px] ${
                              sups.length > 0 ? "rounded-l-md border-r-0" : "rounded-md"
                            } ${
                              baseActive
                                ? "bg-indigo-600 border-indigo-500 text-white"
                                : isActive(f)
                                  ? "bg-indigo-900/50 border-indigo-700/60 text-indigo-300"
                                  : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200"
                            }`}
                          >
                            {label}
                          </button>

                          {/* One button per sup variant */}
                          {sups.map((sup, idx) => {
                            const supActive = selected?.id === sup.id;
                            const isLast = idx === sups.length - 1;
                            return (
                              <button
                                key={sup.id}
                                onClick={() => selectSup(f, sup)}
                                title={sup.filename}
                                className={`text-[10px] px-1.5 py-1 border transition-colors ${
                                  isLast ? "rounded-r-md" : "border-r-0"
                                } ${
                                  supActive
                                    ? "bg-indigo-800 border-indigo-600 text-indigo-200 hover:bg-indigo-700"
                                    : "bg-transparent border-gray-700 text-gray-600 hover:text-gray-300 hover:border-gray-500"
                                }`}
                              >
                                {sups.length === 1 ? "sup" : `s${idx + 1}`}
                              </button>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-gray-700 px-1">
        Drag to rotate · Scroll to zoom · Right-drag to pan
      </p>
    </div>
  );
}
