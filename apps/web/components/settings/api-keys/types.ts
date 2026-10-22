/** Types mirroring `routers/api_keys.py`. */

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  project_id: string | null;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** Answer of `POST /api-keys`: the full key is included once. */
export interface CreatedApiKey extends ApiKey {
  key: string;
}

export const apiKeysKeys = {
  list: ["api-keys"] as const,
  scopes: ["api-keys", "scopes"] as const,
};
