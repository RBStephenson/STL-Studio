import { appendFile } from "node:fs/promises";
import { appendFileSync, existsSync, mkdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const DESKTOP_LOG_NAME = "desktop.log";
export const DIAGNOSTICS_MARKER = "persistent-diagnostics.enabled";
export const DESKTOP_LOG_MAX_BYTES = 2 * 1024 * 1024;
export const DESKTOP_LOG_BACKUPS = 3;

/** How long buffered lines can sit before landing on disk (STUDIO-342).
 *  Backend stdout during a large scan is chatty; batching turns hundreds of
 *  blocking per-line syscalls into one write per interval. A live `tail` of
 *  desktop.log lags by up to this much — acceptable for a debug log. */
const FLUSH_INTERVAL_MS = 1_000;

const bearer = /(bearer\s+)([^\s,;&"']+)/gi;
const namedSecret = /(["']?(?:authorization|api[_-]?key|token|password|secret)["']?\s*[:=]\s*["']?)([^"'\s,;&}]+)/gi;
const windowsPath = /[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]*/g;
const privateUnixPath = /\/(?:data|mnt|media|home|Users)\/[^\s,;]+/g;

export function sanitizeDesktopLog(value: unknown): string {
  return String(value)
    .replace(bearer, "$1<redacted>")
    .replace(namedSecret, "$1<redacted>")
    .replace(windowsPath, "<local-path>")
    .replace(privateUnixPath, "<local-path>");
}

export class PersistentLogger {
  private readonly path: string;
  /** In-memory mirror of the current file's size, seeded once from disk so
   *  the hot path never needs existsSync/statSync again (STUDIO-342). */
  private size: number;
  private buffer: string[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  /** Serializes async flushes (scheduled or explicit) onto one chain so two
   *  in-flight appends can never land out of order. */
  private pendingFlush: Promise<void> = Promise.resolve();

  constructor(directory: string) {
    mkdirSync(directory, { recursive: true });
    this.path = join(directory, DESKTOP_LOG_NAME);
    this.size = existsSync(this.path) ? statSync(this.path).size : 0;
  }

  write(level: string, values: unknown[]): void {
    try {
      const line = `${new Date().toISOString()} ${level} ${values.map(sanitizeDesktopLog).join(" ")}\n`;
      const lineBytes = Buffer.byteLength(line);
      if (this.size + lineBytes > DESKTOP_LOG_MAX_BYTES) {
        // Rotation is a rare boundary event (~every 2MB), not a per-line one,
        // so flushing synchronously here first — before renaming the file
        // out from under any buffered lines — is cheap in practice and keeps
        // those lines in the file they actually belong to.
        this.flushSync();
        this.rotate();
        this.size = 0;
      }
      this.buffer.push(line);
      this.size += lineBytes;
      this.scheduleFlush();
    } catch {
      // Diagnostics must never make the application fail to start or run.
    }
  }

  /** Flushes buffered lines and waits for the write to land. Call before
   *  quit so nothing buffered is lost when the process exits. */
  async flush(): Promise<void> {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    await this.runFlush();
  }

  private scheduleFlush(): void {
    if (this.flushTimer) return;
    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      void this.runFlush();
    }, FLUSH_INTERVAL_MS);
    this.flushTimer.unref?.();
  }

  private runFlush(): Promise<void> {
    this.pendingFlush = this.pendingFlush.then(async () => {
      if (this.buffer.length === 0) return;
      const chunk = this.buffer.join("");
      this.buffer = [];
      try {
        await appendFile(this.path, chunk, "utf8");
      } catch {
        // Diagnostics must never make the application fail to start or run.
      }
    });
    return this.pendingFlush;
  }

  /** Synchronous escape valve used only at the rare rotation boundary, where
   *  the file is about to be renamed out from under any buffered lines. */
  private flushSync(): void {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }
    if (this.buffer.length === 0) return;
    const chunk = this.buffer.join("");
    this.buffer = [];
    try {
      appendFileSync(this.path, chunk, "utf8");
    } catch {
      // Diagnostics must never make the application fail to start or run.
    }
  }

  private rotate(): void {
    rmSync(`${this.path}.${DESKTOP_LOG_BACKUPS}`, { force: true });
    for (let index = DESKTOP_LOG_BACKUPS - 1; index >= 1; index -= 1) {
      const source = `${this.path}.${index}`;
      if (existsSync(source)) renameSync(source, `${this.path}.${index + 1}`);
    }
    if (existsSync(this.path)) renameSync(this.path, `${this.path}.1`);
  }
}

/** Env var name checked alongside the marker file (STUDIO-352): the marker is
 *  only ever written by the Settings-page IPC handler, which needs a working
 *  renderer — unreachable exactly when a startup failure is what you'd want
 *  logs for. Matches the existing STL_STUDIO_USER_DATA_DIR precedent. */
export const DIAGNOSTICS_ENV_VAR = "STL_STUDIO_DIAGNOSTICS";

export function diagnosticsWereEnabled(
  userDataDir: string,
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const envValue = env[DIAGNOSTICS_ENV_VAR];
  if (envValue && envValue !== "0") return true;
  return existsSync(join(userDataDir, DIAGNOSTICS_MARKER));
}

export function persistDiagnosticsChoice(userDataDir: string, enabled: boolean): void {
  const marker = join(userDataDir, DIAGNOSTICS_MARKER);
  if (enabled) writeFileSync(marker, "enabled\n", "utf8");
  else rmSync(marker, { force: true });
}
