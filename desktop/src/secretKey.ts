/**
 * Encryption-key management for the Electron build (STUDIO-147).
 *
 * The backend (backend/app/services/secrets.py) encrypts AI/Cults3D/MMF API
 * keys at rest with a Fernet key sourced from the STL_SECRET_KEY env var. The
 * non-Electron workflow is a manual .env entry; Electron users have no .env,
 * so this module generates the key once, persists it in userData (survives
 * uninstall/upgrade — it's written by the running app, not tracked by the NSIS
 * installer/uninstaller), and main.ts injects it into the sidecar's env.
 *
 * The key format must match `cryptography.fernet.Fernet.generate_key()`
 * exactly: 32 random bytes, urlsafe-base64 WITH padding (44 chars). Node's
 * base64url encoding strips padding, so standard base64 is generated first and
 * then made urlsafe by hand.
 */
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const SECRET_KEY_FILE = "secret-key.json";

interface SecretKeyRecord {
  key: string;
}

export function secretKeyPath(userDataDir: string): string {
  return join(userDataDir, SECRET_KEY_FILE);
}

/** Generate a Fernet-compatible key: 32 random bytes, urlsafe-base64, padded. */
export function generateKey(): string {
  return randomBytes(32)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function readKeyFile(path: string): string | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (
      typeof parsed === "object"
      && parsed !== null
      && typeof (parsed as Partial<SecretKeyRecord>).key === "string"
    ) {
      return (parsed as SecretKeyRecord).key;
    }
    return null;
  } catch {
    return null;
  }
}

function writeKeyFile(path: string, key: string): void {
  writeFileSync(path, `${JSON.stringify({ key } satisfies SecretKeyRecord, null, 2)}\n`, "utf8");
}

export interface ResolvedSecretKey {
  key: string;
  /** True only the first time this key was generated — callers use this to
   *  decide whether to show the one-time reveal window. */
  isNew: boolean;
}

/** Load the persisted key, or generate and persist a new one if none exists. */
export function getOrCreateSecretKey(userDataDir: string): ResolvedSecretKey {
  const path = secretKeyPath(userDataDir);
  if (existsSync(path)) {
    const existing = readKeyFile(path);
    if (existing) {
      return { key: existing, isNew: false };
    }
    // File exists but is unreadable/corrupt — fall through and regenerate
    // rather than leave the app unable to encrypt anything.
  }
  const key = generateKey();
  writeKeyFile(path, key);
  return { key, isNew: true };
}

/** Overwrite with a freshly generated key. Callers must warn the user this
 *  invalidates every currently-stored encrypted secret (AI/Cults3D/MMF keys)
 *  and must restart the sidecar so the backend picks up the new value —
 *  secrets.py caches its Fernet instance for the life of the process. */
export function regenerateSecretKey(userDataDir: string): string {
  const key = generateKey();
  writeKeyFile(secretKeyPath(userDataDir), key);
  return key;
}
