import { appendFileSync, existsSync, mkdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const DESKTOP_LOG_NAME = "desktop.log";
export const DIAGNOSTICS_MARKER = "persistent-diagnostics.enabled";
export const DESKTOP_LOG_MAX_BYTES = 2 * 1024 * 1024;
export const DESKTOP_LOG_BACKUPS = 3;

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

  constructor(directory: string) {
    mkdirSync(directory, { recursive: true });
    this.path = join(directory, DESKTOP_LOG_NAME);
  }

  write(level: string, values: unknown[]): void {
    try {
      const line = `${new Date().toISOString()} ${level} ${values.map(sanitizeDesktopLog).join(" ")}\n`;
      if (existsSync(this.path) && statSync(this.path).size + Buffer.byteLength(line) > DESKTOP_LOG_MAX_BYTES) {
        this.rotate();
      }
      appendFileSync(this.path, line, "utf8");
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

export function diagnosticsWereEnabled(userDataDir: string): boolean {
  return existsSync(join(userDataDir, DIAGNOSTICS_MARKER));
}

export function persistDiagnosticsChoice(userDataDir: string, enabled: boolean): void {
  const marker = join(userDataDir, DIAGNOSTICS_MARKER);
  if (enabled) writeFileSync(marker, "enabled\n", "utf8");
  else rmSync(marker, { force: true });
}
