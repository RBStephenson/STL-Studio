import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  generateKey,
  getOrCreateSecretKey,
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
  it("generates and persists a new key when none exists, marking it isNew", () => {
    const dir = makeUserDataDir();
    const result = getOrCreateSecretKey(dir);
    expect(result.isNew).toBe(true);
    expect(result.key).toHaveLength(44);

    const onDisk = JSON.parse(readFileSync(secretKeyPath(dir), "utf8"));
    expect(onDisk.key).toBe(result.key);
  });

  it("loads the existing key on a second call, not generating a new one", () => {
    const dir = makeUserDataDir();
    const first = getOrCreateSecretKey(dir);
    const second = getOrCreateSecretKey(dir);
    expect(second.isNew).toBe(false);
    expect(second.key).toBe(first.key);
  });

  it("regenerates when the persisted file is corrupt rather than failing", () => {
    const dir = makeUserDataDir();
    writeFileSync(secretKeyPath(dir), "not valid json", "utf8");
    const result = getOrCreateSecretKey(dir);
    expect(result.isNew).toBe(true);
    expect(result.key).toHaveLength(44);
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
});
