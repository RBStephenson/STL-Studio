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
  /** Whether the one-time reveal window has been shown for this key.
   *
   *  Absent on records written before STUDIO-347. A missing field means
   *  "legacy, assume already revealed" — treating it as pending would fire a
   *  surprise key window at every existing user on their next launch. Only an
   *  explicit `false` marks a reveal as still owed. */
  revealed?: boolean;
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

function readKeyFile(path: string): SecretKeyRecord | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (
      typeof parsed === "object"
      && parsed !== null
      && typeof (parsed as Partial<SecretKeyRecord>).key === "string"
    ) {
      const record = parsed as SecretKeyRecord;
      return { key: record.key, revealed: record.revealed };
    }
    return null;
  } catch {
    return null;
  }
}

function writeKeyFile(path: string, key: string, revealed: boolean): void {
  writeFileSync(
    path,
    `${JSON.stringify({ key, revealed } satisfies SecretKeyRecord, null, 2)}\n`,
    "utf8",
  );
}

export interface ResolvedSecretKey {
  key: string;
  /** Whether the one-time reveal window still owes the user a showing.
   *
   *  Driven by the persisted `revealed` bit rather than "did this call
   *  generate the key" — a boot that writes the key but never reaches the
   *  reveal (quit during the health poll, backend never becoming healthy)
   *  used to leave the key persisted and permanently unrevealed
   *  (STUDIO-347). */
  needsReveal: boolean;
}

/** Load the persisted key, or generate and persist a new one if none exists. */
export function getOrCreateSecretKey(userDataDir: string): ResolvedSecretKey {
  const path = secretKeyPath(userDataDir);
  if (existsSync(path)) {
    const existing = readKeyFile(path);
    if (existing) {
      // Missing `revealed` means a pre-STUDIO-347 record: assume revealed.
      return { key: existing.key, needsReveal: existing.revealed === false };
    }
    // File exists but is unreadable/corrupt — fall through and regenerate
    // rather than leave the app unable to encrypt anything.
  }
  const key = generateKey();
  writeKeyFile(path, key, false);
  return { key, needsReveal: true };
}

/** Record that the reveal window has been shown, so a later boot doesn't
 *  show it again. Best-effort: failing to persist this must not break a boot
 *  that has otherwise succeeded — the cost is at worst a repeated reveal. */
export function markSecretKeyRevealed(userDataDir: string): void {
  const path = secretKeyPath(userDataDir);
  const existing = readKeyFile(path);
  if (!existing) return;
  try {
    writeKeyFile(path, existing.key, true);
  } catch {
    // Losing the marker only risks showing the reveal again; never fatal.
  }
}

/** Overwrite with a freshly generated key. Callers must warn the user this
 *  invalidates every currently-stored encrypted secret (AI/Cults3D/MMF keys)
 *  and must restart the sidecar so the backend picks up the new value —
 *  secrets.py caches its Fernet instance for the life of the process. */
export function regenerateSecretKey(userDataDir: string): string {
  const key = generateKey();
  // Written unrevealed: the rotation flow reveals it immediately via
  // forceReveal, and if that boot dies first the new key is still owed.
  writeKeyFile(secretKeyPath(userDataDir), key, false);
  return key;
}
