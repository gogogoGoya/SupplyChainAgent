const OPERATIONS_BASE = '/operations';

const buildQuery = (params = {}) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value));
    }
  });
  const text = query.toString();
  return text ? `?${text}` : '';
};

const readOperationsJson = async (response) => {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return {
      available: false,
      data: null,
      error: `Operations endpoint returned ${contentType || 'non-json response'}`,
    };
  }

  const payload = await response.json();
  if (!response.ok || payload?.ok === false || payload?.status === 'error') {
    return {
      available: response.ok,
      data: null,
      error: payload?.error?.message || payload?.detail || payload?.message || response.statusText,
    };
  }

  return {
    available: true,
    data: payload?.data ?? payload,
    error: '',
  };
};

const requestOperations = async (path, options = {}) => {
  try {
    const response = await fetch(`${OPERATIONS_BASE}${path}`, options);
    return readOperationsJson(response);
  } catch (error) {
    return {
      available: false,
      data: null,
      error: error?.message || 'Operations endpoint is unavailable',
    };
  }
};

export const listOperationsJobs = async ({ activeOnly = false, status = '', limit = 100 } = {}) => {
  const result = await requestOperations(`/jobs${buildQuery({
    active_only: activeOnly ? 'true' : '',
    status,
    limit,
  })}`);
  return {
    available: result.available,
    jobs: Array.isArray(result.data) ? result.data : [],
    error: result.error,
  };
};

export const listArtifactRuns = async ({
  includeWorkspaceCurrent = true,
  includeWorkspaceJobs = true,
  includeSimulationRuns = true,
  includeOperationsJobs = true,
  limit = 500,
} = {}) => {
  const result = await requestOperations(`/artifacts/runs${buildQuery({
    include_workspace_current: includeWorkspaceCurrent ? 'true' : 'false',
    include_workspace_jobs: includeWorkspaceJobs ? 'true' : 'false',
    include_simulation_runs: includeSimulationRuns ? 'true' : 'false',
    include_operations_jobs: includeOperationsJobs ? 'true' : 'false',
    limit,
  })}`);
  return {
    available: result.available,
    entries: Array.isArray(result.data?.entries) ? result.data.entries : [],
    count: Number(result.data?.count || 0),
    error: result.error,
  };
};

export const resumeArtifactRun = async (payload = {}) => {
  const result = await requestOperations('/artifacts/resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return {
    available: result.available,
    job: result.data || null,
    error: result.error,
  };
};

export const getOperationsJob = async (jobId) => {
  if (!jobId) {
    return { available: false, job: null, error: 'jobId is required' };
  }
  const result = await requestOperations(`/jobs/${encodeURIComponent(jobId)}`);
  return {
    available: result.available,
    job: result.data || null,
    error: result.error,
  };
};

export const getOperationsJobSummary = async (jobId) => {
  if (!jobId) {
    return { available: false, summary: null, error: 'jobId is required' };
  }
  const result = await requestOperations(`/jobs/${encodeURIComponent(jobId)}/summary`);
  return {
    available: result.available,
    summary: result.data || null,
    error: result.error,
  };
};

export const createOperationsJob = async (payload) => {
  const result = await requestOperations('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  return {
    available: result.available,
    job: result.data || null,
    error: result.error,
  };
};

export const startOperationsJob = async (jobId, payload = {}) => {
  const result = await requestOperations(`/jobs/${encodeURIComponent(jobId)}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return {
    available: result.available,
    job: result.data || null,
    error: result.error,
  };
};

export const runOperationsJob = async (jobId, payload = {}) => {
  const result = await requestOperations(`/jobs/${encodeURIComponent(jobId)}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return {
    available: result.available,
    result: result.data || null,
    error: result.error,
  };
};

export const stopOperationsJob = async (jobId, payload = {}) => {
  const result = await requestOperations(`/jobs/${encodeURIComponent(jobId)}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return {
    available: result.available,
    job: result.data || null,
    error: result.error,
  };
};

export const resumeOperationsJob = async (jobId, payload = {}) => {
  const result = await requestOperations(`/jobs/${encodeURIComponent(jobId)}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return {
    available: result.available,
    job: result.data || null,
    error: result.error,
  };
};

export const deleteOperationsJob = async (jobId, payload = {}) => {
  if (!jobId) {
    return { available: false, job: null, error: 'jobId is required' };
  }
  const result = await requestOperations(`/jobs/${encodeURIComponent(jobId)}/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force: true, ...payload }),
  });
  return {
    available: result.available,
    job: result.data || null,
    error: result.error,
  };
};

export const listOperationScenarios = async () => {
  const result = await requestOperations('/scenarios');
  return {
    available: result.available,
    scenarios: Array.isArray(result.data) ? result.data : [],
    error: result.error,
  };
};
