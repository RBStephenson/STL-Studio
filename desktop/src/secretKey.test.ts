import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  generateKey,
  getOrCreateSecretKey,
  markSecretKeyRevealed,
  regenerateSecretKey,
  secretKeyPath,
} from "./secretKey";

const tempDirs: string[] = [];

function makeUserDataDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "stl-secret-key-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("generateKey", () => {
  it("produces a 44-char urlsafe-base64 string matching Fernet's format", () => {
    const key = generateKey();
    expect(key).toHaveLength(44);
    expect(key).toMatch(/^[A-Za-z0-9_-]{43}=$/);
  });

  it("never repeats across calls", () => {
    expect(generateKey()).not.toBe(generateKey());
  });
});

describe("getOrCreateSecretKey", () => {
  it("generates and persists a new key when none exists, marking it needsReveal", () => {
    const dir = makeUserDataDir();
    const result = getOrCreateSecretKey(dir);
    expect(result.needsReveal).toBe(true);
    expect(result.key).toHaveLength(44);

    const onDisk = JSON.parse(readFileSync(secretKeyPath(dir), "utf8"));
    expect(onDisk.key).toBe(result.key);
    expect(onDisk.revealed).toBe(false);
  });

  it("loads the existing key on a second call, not generating a new one", () => {
    const dir = makeUserDataDir();
    const first = getOrCreateSecretKey(dir);
    markSecretKeyRevealed(dir);
    const second = getOrCreateSecretKey(dir);
    expect(second.needsReveal).toBe(false);
    expect(second.key).toBe(first.key);
  });

  it("regenerates when the persisted file is corrupt rather than failing", () => {
    const dir = makeUserDataDir();
    writeFileSync(secretKeyPath(dir), "not valid json", "utf8");
    const result = getOrCreateSecretKey(dir);
    expect(result.needsReveal).toBe(true);
    expect(result.key).toHaveLength(44);
  });

  it("still owes a reveal for a key written but never revealed (STUDIO-347)", () => {
    const dir = makeUserDataDir();
    // Models a first boot that persisted the key then died before the reveal
    // (quit during the health poll, backend never healthy).
    const first = getOrCreateSecretKey(dir);
    expect(first.needsReveal).toBe(true);

    const second = getOrCreateSecretKey(dir);
    expect(second.key).toBe(first.key);
    expect(second.needsReveal).toBe(true);
  });

  it("treats a legacy record with no `revealed` field as already revealed", () => {
    const dir = makeUserDataDir();
    // Pre-STUDIO-347 on-disk shape. Treating this as pending would fire a
    // surprise key window at every existing user on their next launch.
    writeFileSync(secretKeyPath(dir), JSON.stringify({ key: "legacy-key" }), "utf8");

    const result = getOrCreateSecretKey(dir);

    expect(result.key).toBe("legacy-key");
    expect(result.needsReveal).toBe(false);
  });
});

describe("markSecretKeyRevealed", () => {
  it("stops a subsequent call from owing another reveal", () => {
    const dir = makeUserDataDir();
    const created = getOrCreateSecretKey(dir);

    markSecretKeyRevealed(dir);

    const reloaded = getOrCreateSecretKey(dir);
    expect(reloaded.key).toBe(created.key);
    expect(reloaded.needsReveal).toBe(false);
  });

  it("leaves the key itself untouched", () => {
    const dir = makeUserDataDir();
    const created = getOrCreateSecretKey(dir);

    markSecretKeyRevealed(dir);

    const onDisk = JSON.parse(readFileSync(secretKeyPath(dir), "utf8"));
    expect(onDisk.key).toBe(created.key);
    expect(onDisk.revealed).toBe(true);
  });

  it("is a no-op when no key file exists", () => {
    const dir = makeUserDataDir();
    expect(() => markSecretKeyRevealed(dir)).not.toThrow();
  });
});

describe("regenerateSecretKey", () => {
  it("overwrites the persisted key with a new one", () => {
    const dir = makeUserDataDir();
    const original = getOrCreateSecretKey(dir).key;
    const rotated = regenerateSecretKey(dir);
    expect(rotated).not.toBe(original);

    const onDisk = JSON.parse(readFileSync(secretKeyPath(dir), "utf8"));
    expect(onDisk.key).toBe(rotated);
  });

  it("leaves the rotated key owing a reveal", () => {
    const dir = makeUserDataDir();
    getOrCreateSecretKey(dir);
    markSecretKeyRevealed(dir);

    const rotated = regenerateSecretKey(dir);

    const reloaded = getOrCreateSecretKey(dir);
    expect(reloaded.key).toBe(rotated);
    expect(reloaded.needsReveal).toBe(true);
  });
});
