import { BASE } from "./base";

export type DatabaseHealth = {
  ok: boolean;
  status: "healthy" | "corrupt";
  detail: string;
};

export type DatabaseRepairResult = DatabaseHealth & {
  before: string;
  repaired: boolean;
  snapshot: string | null;
};

export const databaseApi = {
  backup: async () => {
    const res = await fetch(`${BASE}/database/backup`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const blob = await res.blob();
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `stl_inventory_backup_${stamp}.db`;
    a.click();
    URL.revokeObjectURL(url);
  },
  restore: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/database/restore`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<{ ok: boolean }>;
  },
  health: async () => {
    const res = await fetch(`${BASE}/database/health`);
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<DatabaseHealth>;
  },
  repair: async () => {
    const res = await fetch(`${BASE}/database/repair`, { method: "POST" });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<DatabaseRepairResult>;
  },
  reset: async () => {
    const res = await fetch(`${BASE}/database/reset`, { method: "POST" });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<{ ok: boolean }>;
  },
};
