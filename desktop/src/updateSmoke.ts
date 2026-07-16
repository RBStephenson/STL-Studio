export interface UpdateSmokeConfig {
  feedUrl: string;
}

export function readUpdateSmokeConfig(
  env: NodeJS.ProcessEnv,
): UpdateSmokeConfig | null {
  if (env.STL_STUDIO_UPDATE_SMOKE !== "1") return null;
  const rawUrl = env.STL_STUDIO_UPDATE_FEED_URL?.trim();
  if (!rawUrl) throw new Error("update smoke mode requires STL_STUDIO_UPDATE_FEED_URL");
  const url = new URL(rawUrl);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "::1"].includes(url.hostname)) {
    throw new Error("update smoke feed must be an HTTP loopback URL");
  }
  return { feedUrl: url.toString() };
}
