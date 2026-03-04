const MAX_LOG_LINES = 7000;
const STORE_KEY = '__QA_UI_NEXT_STORE__';
const SUPPORTED_SCRIPT_KINDS = new Set([
  'python_pytest',
  'javascript_jest',
  'curl_script',
  'java_restassured'
]);
const DEFAULT_TEST_BASE_URL =
  String(process.env.NEXT_PUBLIC_TEST_BASE_URL || process.env.TEST_BASE_URL || 'http://127.0.0.1:8000')
    .trim()
    .replace(/\/$/, '');

function getStore() {
  if (!globalThis[STORE_KEY]) {
    globalThis[STORE_KEY] = {
      jobs: new Map(),
      listeners: new Map()
    };
  }
  return globalThis[STORE_KEY];
}

function sanitizeToken(value, fallback = 'default') {
  const token = String(value ?? '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_');
  return token || fallback;
}

function normalizeScriptKind(value) {
  const token = sanitizeToken(value, 'python_pytest');
  return SUPPORTED_SCRIPT_KINDS.has(token) ? token : 'python_pytest';
}

function normalizeSpecPaths(input = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return {};
  }
  const out = {};
  for (const [rawDomain, rawPath] of Object.entries(input)) {
    const domain = sanitizeToken(rawDomain);
    const specPath = String(rawPath || '').trim();
    if (!domain || !specPath) {
      continue;
    }
    out[domain] = specPath;
  }
  return out;
}

export function normalizeRequest(input = {}) {
  const specPaths = normalizeSpecPaths(input.specPaths ?? input.spec_paths ?? {});
  const rawDomains = Array.isArray(input.domains) ? input.domains : [];
  const domainsSet = new Set(rawDomains.map((d) => sanitizeToken(d)).filter(Boolean));
  for (const domain of Object.keys(specPaths)) {
    domainsSet.add(domain);
  }
  if (domainsSet.size === 0) {
    throw new Error('Provide at least one domain or one spec path mapping.');
  }
  const domains = [...domainsSet];

  return {
    domains,
    specPaths,
    tenantId: sanitizeToken(input.tenantId ?? input.tenant_id ?? 'customer_default'),
    workspaceId: sanitizeToken(input.workspaceId ?? input.workspace_id ?? input.tenantId ?? input.tenant_id ?? 'customer_default'),
    scriptKind: normalizeScriptKind(input.scriptKind ?? input.script_kind ?? 'python_pytest'),
    prompt: typeof input.prompt === 'string' && input.prompt.trim() ? input.prompt.trim() : null,
    maxScenarios: Math.min(500, Math.max(1, Number(input.maxScenarios ?? input.max_scenarios ?? 16) || 16)),
    maxRuntimeSec: (() => {
      const raw = Number(input.maxRuntimeSec ?? input.max_runtime_sec ?? 0) || 0;
      if (raw <= 0) return null;
      return Math.min(7200, Math.max(1, Math.trunc(raw)));
    })(),
    llmTokenCap: (() => {
      const raw = Number(input.llmTokenCap ?? input.llm_token_cap ?? 0) || 0;
      if (raw <= 0) return null;
      return Math.min(16000, Math.max(64, Math.trunc(raw)));
    })(),
    environmentProfile: (() => {
      const value = String(input.environmentProfile ?? input.environment_profile ?? 'mock').trim().toLowerCase();
      return ['mock', 'staging', 'prod_safe'].includes(value) ? value : 'mock';
    })(),
    passThreshold: Math.min(1, Math.max(0, Number(input.passThreshold ?? input.pass_threshold ?? 0.7) || 0.7)),
    baseUrl:
      typeof input.baseUrl === 'string' && input.baseUrl.trim()
        ? input.baseUrl.trim()
        : DEFAULT_TEST_BASE_URL,
    customerMode: input.customerMode !== false && input.customer_mode !== false,
    verifyPersistence: input.verifyPersistence !== false && input.verify_persistence !== false,
    customerRoot:
      typeof input.customerRoot === 'string' && input.customerRoot.trim()
        ? input.customerRoot.trim()
        : '~/.spec_test_pilot'
  };
}

export function createJob(request) {
  const store = getStore();
  const id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
  const now = new Date().toISOString();

  const job = {
    id,
    status: 'queued',
    createdAt: now,
    startedAt: null,
    completedAt: null,
    currentDomain: null,
    request,
    logs: [],
    results: {},
    error: null
  };

  store.jobs.set(id, job);
  emitJob(id);
  return job;
}

export function getJob(jobId) {
  return getStore().jobs.get(jobId) || null;
}

export function listJobs() {
  return Array.from(getStore().jobs.values()).map((job) => ({
    id: job.id,
    status: job.status,
    createdAt: job.createdAt,
    startedAt: job.startedAt,
    completedAt: job.completedAt,
    currentDomain: job.currentDomain,
    domains: job.request.domains,
    scriptKind: job.request.scriptKind
  }));
}

export function updateJob(jobId, patch) {
  const job = getJob(jobId);
  if (!job) {
    return null;
  }
  Object.assign(job, patch);
  emitJob(jobId);
  return job;
}

export function appendJobLog(jobId, line) {
  const job = getJob(jobId);
  if (!job) {
    return;
  }
  job.logs.push(String(line).replace(/\n$/, ''));
  if (job.logs.length > MAX_LOG_LINES) {
    job.logs.splice(0, job.logs.length - MAX_LOG_LINES);
  }
  emitJob(jobId);
}

export function setDomainResult(jobId, domain, result) {
  const job = getJob(jobId);
  if (!job) {
    return;
  }
  job.results[domain] = result;
  emitJob(jobId);
}

export function snapshotJob(jobId, tail = 800) {
  const job = getJob(jobId);
  if (!job) {
    return null;
  }

  const logTail = Math.max(50, Math.min(3000, Number(tail) || 800));
  return {
    id: job.id,
    status: job.status,
    createdAt: job.createdAt,
    startedAt: job.startedAt,
    completedAt: job.completedAt,
    currentDomain: job.currentDomain,
    request: job.request,
    results: job.results,
    logs: job.logs.slice(-logTail),
    error: job.error
  };
}

export function subscribeJob(jobId, callback) {
  const store = getStore();
  if (!store.listeners.has(jobId)) {
    store.listeners.set(jobId, new Set());
  }
  const bucket = store.listeners.get(jobId);
  bucket.add(callback);
  return () => {
    bucket.delete(callback);
    if (bucket.size === 0) {
      store.listeners.delete(jobId);
    }
  };
}

function emitJob(jobId) {
  const store = getStore();
  const bucket = store.listeners.get(jobId);
  if (!bucket || bucket.size === 0) {
    return;
  }
  const payload = snapshotJob(jobId, 1500);
  for (const cb of bucket) {
    try {
      cb(payload);
    } catch {
      // Listener errors must not break store updates.
    }
  }
}
