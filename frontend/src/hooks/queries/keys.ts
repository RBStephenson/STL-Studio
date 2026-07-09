// Central query-key factory (STUDIO-61). One source of truth for the cache keys
// so queries and their invalidations can't drift. Keys are namespaced per domain
// (models, groups, tags, guides, paints); invalidating a domain's root key
// (e.g. queryKeys.models.all) cascades to every nested query under it.
//
// Keep keys serialisable and stable: same inputs must produce structurally equal
// arrays, since TanStack compares them by value.

export const queryKeys = {
  models: {
    all: ["models"] as const,
    detail: (id: number) => ["models", "detail", id] as const,
    listAll: ["models", "list"] as const,
    // Paginated/filtered Library grid. Keyed on the full param object so any
    // filter/page/sort change is a distinct cache entry.
    list: (params: Record<string, string | number | boolean>) =>
      ["models", "list", params] as const,
    creators: ["models", "creators"] as const,
    stats: ["models", "stats"] as const,
    // Prefix key for invalidating every variants query at once — used after an
    // in-place model refresh whose specific (creator, character, group) key is
    // unchanged but whose sibling thumbnails may have moved.
    variantsAll: ["models", "variants"] as const,
    variants: (creatorId: number, character: string, groupId?: number | null) =>
      ["models", "variants", creatorId, character, groupId ?? null] as const,
    neighbors: (id: number, params: Record<string, string | number | boolean>) =>
      ["models", "neighbors", id, params] as const,
    characters: (creatorId: number) => ["models", "characters", creatorId] as const,
    tags: () => ["models", "tags"] as const,
  },
  groups: {
    all: ["groups"] as const,
    detail: (id: number) => ["groups", "detail", id] as const,
  },
  tags: {
    all: ["tags"] as const,
  },
  guides: {
    all: ["guides"] as const,
    forModel: (modelId: number) => ["guides", "forModel", modelId] as const,
    modelIds: ["guides", "modelIds"] as const,
  },
  paints: {
    all: ["paints"] as const,
  },
  collections: {
    all: ["collections"] as const,
  },
  scan: {
    roots: ["scan", "roots"] as const,
    driveStatus: ["files", "drive-status"] as const,
  },
} as const;
