export const LATEST_RUN_ID = 'latest';

export const resolveDataRoot = (runId = LATEST_RUN_ID) => (
  runId === LATEST_RUN_ID
    ? '/workspace_multi'
    : `/simulation_runs/${encodeURIComponent(runId)}`
);

export const resolveWorkspaceJobRoot = (jobWorkspaceName) => (
  `/workspace_jobs/${encodeURIComponent(jobWorkspaceName)}`
);

export const buildDataUrl = (dataRoot, relativePath) => {
  const normalizedRoot = (dataRoot || '/workspace_multi').replace(/\/$/, '');
  const normalizedRelativePath = String(relativePath || '').replace(/^\//, '');
  return `${normalizedRoot}/${normalizedRelativePath}`;
};

const DEFAULT_CACHE_TTL_MS = 60 * 1000;
const responseCache = new Map();
const pendingRequests = new Map();

const makeCacheKey = (url, options = {}) => {
  const method = options.method || 'GET';
  return `${method}:${url}`;
};

const readCachedValue = (key, cacheTtlMs) => {
  const cached = responseCache.get(key);
  if (!cached) {
    return undefined;
  }
  if (cacheTtlMs < 0 || Date.now() - cached.timestamp <= cacheTtlMs) {
    return cached.value;
  }
  responseCache.delete(key);
  return undefined;
};

const safeFetchWithCache = async (url, options = {}, parser) => {
  const {
    cacheTtlMs = DEFAULT_CACHE_TTL_MS,
    forceRefresh = false,
    ...fetchOptions
  } = options;
  const cacheKey = makeCacheKey(url, fetchOptions);

  if (!forceRefresh) {
    const cachedValue = readCachedValue(cacheKey, cacheTtlMs);
    if (cachedValue !== undefined) {
      return cachedValue;
    }
    if (pendingRequests.has(cacheKey)) {
      return pendingRequests.get(cacheKey);
    }
  }

  const request = (async () => {
    let value = null;
    try {
      const response = await fetch(url, { cache: 'default', ...fetchOptions });
      if (response.ok) {
        value = await parser(response);
      }
    } catch (error) {
      value = null;
    } finally {
      responseCache.set(cacheKey, {
        timestamp: Date.now(),
        value,
      });
      pendingRequests.delete(cacheKey);
    }
    return value;
  })();

  pendingRequests.set(cacheKey, request);
  return request;
};

export const clearDataSourceCache = () => {
  responseCache.clear();
  pendingRequests.clear();
};

export const safeFetchJson = async (url, options = {}) => {
  try {
    return await safeFetchWithCache(url, options, (response) => response.json());
  } catch (error) {
    return null;
  }
};

export const safeFetchText = async (url, options = {}) => {
  try {
    return await safeFetchWithCache(url, options, (response) => response.text());
  } catch (error) {
    return null;
  }
};
