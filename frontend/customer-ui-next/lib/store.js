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

function stripBearerPrefix(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^bearer\s+/i.test(raw)) {
    return raw.replace(/^bearer\s+/i, '').trim();
  }
  return raw;
}

function normalizeAuthMode(value) {
  const raw = String(value ?? '').trim().toLowerCase();
  if (raw === 'bearer') return 'bearer';
  if (raw === 'api_key' || raw === 'apikey') return 'api_key';
  if (raw === 'basic') return 'basic';
  if (raw === 'form') return 'form';
  return 'none';
}

function normalizeAuthContext(authMode, input = {}) {
  const source = input && typeof input === 'object' ? input : {};
  if (authMode === 'bearer') {
    return {
      bearerToken: stripBearerPrefix(source.bearerToken)
    };
  }
  if (authMode === 'api_key') {
    return {
      apiKeyName: String(source.apiKeyName || '').trim(),
      apiKeyValue: String(source.apiKeyValue || '').trim(),
      apiKeyIn: String(source.apiKeyIn || 'header').trim().toLowerCase() === 'query' ? 'query' : 'header'
    };
  }
  if (authMode === 'basic') {
    return {
      username: String(source.username || '').trim(),
      password: String(source.password || '')
    };
  }
  if (authMode === 'form') {
    return {
      formLoginPath: String(source.formLoginPath || '').trim(),
      formMethod: String(source.formMethod || 'POST').trim().toUpperCase(),
      usernameField: String(source.usernameField || '').trim(),
      passwordField: String(source.passwordField || '').trim(),
      username: String(source.username || '').trim(),
      password: String(source.password || ''),
      tokenPath: String(source.tokenPath || '').trim()
    };
  }
  return {};
}

function buildRuntimeSecrets(authMode, authContext) {
  if (authMode === 'bearer') {
    const token = stripBearerPrefix(authContext?.bearerToken);
    return token ? { bearerToken: token } : {};
  }
  if (authMode === 'api_key') {
    const value = String(authContext?.apiKeyValue || '').trim();
    return value ? { apiKeyValue: value } : {};
  }
  if (authMode === 'basic') {
    const password = String(authContext?.password || '');
    return password ? { basicPassword: password } : {};
  }
  if (authMode === 'form') {
    const password = String(authContext?.password || '');
    return password ? { formPassword: password } : {};
  }
  return {};
}

function redactAuthContext(authMode, authContext) {
  if (authMode === 'bearer') {
    const token = stripBearerPrefix(authContext?.bearerToken || '');
    return {
      bearerTokenProvided: Boolean(token)
    };
  }
  if (authMode === 'api_key') {
    return {
      apiKeyName: String(authContext?.apiKeyName || '').trim(),
      apiKeyIn: String(authContext?.apiKeyIn || 'header').trim().toLowerCase() === 'query' ? 'query' : 'header',
      apiKeyValueProvided: Boolean(String(authContext?.apiKeyValue || '').trim())
    };
  }
  if (authMode === 'basic') {
    return {
      username: String(authContext?.username || '').trim(),
      passwordProvided: Boolean(String(authContext?.password || ''))
    };
  }
  if (authMode === 'form') {
    return {
      formLoginPath: String(authContext?.formLoginPath || '').trim(),
      formMethod: String(authContext?.formMethod || 'POST').trim().toUpperCase(),
      usernameField: String(authContext?.usernameField || '').trim(),
      passwordField: String(authContext?.passwordField || '').trim(),
      username: String(authContext?.username || '').trim(),
      tokenPath: String(authContext?.tokenPath || '').trim(),
      passwordProvided: Boolean(String(authContext?.password || ''))
    };
  }
  return {};
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

function normalizeOperationId(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const parts = raw.split(/\s+/, 2);
  if (parts.length !== 2) return '';
  const method = String(parts[0] || '').trim().toUpperCase();
  const endpointRaw = String(parts[1] || '').trim();
  if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD', 'TRACE'].includes(method)) {
    return '';
  }
  if (!endpointRaw) return '';
  const endpoint = endpointRaw.startsWith('/') ? endpointRaw : `/${endpointRaw}`;
  return `${method} ${endpoint}`;
}

function normalizeOperationSelection(input) {
  if (!Array.isArray(input)) return [];
  const out = [];
  for (const item of input) {
    const op = normalizeOperationId(item);
    if (!op || out.includes(op)) continue;
    out.push(op);
  }
  return out;
}

function normalizeEnvironmentTargets(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return {};
  const out = {};
  const alias = {
    prod: 'prod_safe',
    production: 'prod_safe',
    prod_safe: 'prod_safe',
    staging: 'staging',
    mock: 'mock'
  };
  for (const [rawProfile, rawUrl] of Object.entries(input)) {
    const profile = alias[String(rawProfile || '').trim().toLowerCase()] || String(rawProfile || '').trim().toLowerCase();
    if (!['mock', 'staging', 'prod_safe'].includes(profile)) continue;
    const url = String(rawUrl || '').trim();
    if (!/^https?:\/\//i.test(url)) continue;
    out[profile] = url.replace(/\/$/, '');
  }
  return out;
}

function normalizeReleaseGate(input = {}, passThreshold = 0.7) {
  const payload = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
  const asNumber = (value, fallback) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    return Math.min(1, Math.max(0, num));
  };
  return {
    enabled: payload.enabled !== false,
    passFloor: asNumber(payload.passFloor, passThreshold),
    flakyThreshold: asNumber(payload.flakyThreshold, 0.15),
    maxPassDrop: asNumber(payload.maxPassDrop, 0.08),
    maxRewardDrop: asNumber(payload.maxRewardDrop, 0.10),
    minGamQuality: asNumber(payload.minGamQuality, 0.55),
    safeModeOnFail: payload.safeModeOnFail !== false
  };
}

function normalizeCriticalAssertions(input) {
  if (!Array.isArray(input)) return [];
  const out = [];
  for (const row of input) {
    if (!row || typeof row !== 'object') continue;
    const operationId = normalizeOperationId(row.operationId);
    if (!operationId) continue;
    const expectedStatus = Number.isFinite(Number(row.expectedStatus)) ? Math.trunc(Number(row.expectedStatus)) : null;
    const allowedStatuses = Array.isArray(row.allowedStatuses)
      ? [...new Set(row.allowedStatuses.map((v) => Math.trunc(Number(v))).filter((v) => Number.isFinite(v)))]
      : [];
    const minPassCount = Math.max(1, Math.trunc(Number(row.minPassCount || 1)) || 1);
    out.push({
      operationId,
      expectedStatus,
      allowedStatuses,
      minPassCount,
      note: String(row.note || '').trim().slice(0, 300)
    });
    if (out.length >= 200) break;
  }
  return out;
}

function normalizeResourceLimits(input = {}) {
  const payload = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
  const toFloat = (value, fallback, min, max) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return fallback;
    return Math.min(max, Math.max(min, num));
  };
  const toInt = (value, fallback, min, max) => {
    const num = Math.trunc(Number(value));
    if (!Number.isFinite(num)) return fallback;
    return Math.min(max, Math.max(min, num));
  };
  return {
    liveRequestTimeoutSec: toFloat(payload.liveRequestTimeoutSec, 12, 0.1, 120),
    scriptExecMaxRuntimeSec: toFloat(payload.scriptExecMaxRuntimeSec, 120, 1, 1800),
    llmTimeoutSec: toInt(payload.llmTimeoutSec, 45, 1, 600),
    llmRetries: toInt(payload.llmRetries, 1, 0, 5)
  };
}

function normalizeReportMode(value) {
  const mode = String(value || 'full').trim().toLowerCase();
  return ['full', 'executive', 'summary', 'technical'].includes(mode) ? mode : 'full';
}

function normalizeAuthProfiles(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return {};
  const out = {};
  for (const [rawOperation, rawProfile] of Object.entries(input)) {
    const operationId = normalizeOperationId(rawOperation);
    if (!operationId || !rawProfile || typeof rawProfile !== 'object') continue;
    const mode = normalizeAuthMode(rawProfile.authMode ?? rawProfile.mode ?? 'none');
    const profile = { authMode: mode };
    if (mode === 'bearer') {
      const token = stripBearerPrefix(rawProfile.bearerToken);
      if (token) profile.bearerToken = token;
    }
    if (mode === 'api_key') {
      profile.apiKeyName = String(rawProfile.apiKeyName || 'X-API-Key').trim() || 'X-API-Key';
      profile.apiKeyIn = String(rawProfile.apiKeyIn || 'header').trim().toLowerCase() === 'query' ? 'query' : 'header';
      const apiKeyValue = String(rawProfile.apiKeyValue || '').trim();
      if (apiKeyValue) profile.apiKeyValue = apiKeyValue;
    }
    out[operationId] = profile;
  }
  return out;
}

function redactAuthProfiles(authProfiles) {
  const out = {};
  for (const [operationId, profile] of Object.entries(authProfiles || {})) {
    const mode = normalizeAuthMode(profile?.authMode || 'none');
    const item = { authMode: mode };
    if (mode === 'bearer') {
      item.bearerTokenProvided = Boolean(stripBearerPrefix(profile?.bearerToken || ''));
    }
    if (mode === 'api_key') {
      item.apiKeyName = String(profile?.apiKeyName || '').trim();
      item.apiKeyIn = String(profile?.apiKeyIn || 'header').trim().toLowerCase() === 'query' ? 'query' : 'header';
      item.apiKeyValueProvided = Boolean(String(profile?.apiKeyValue || '').trim());
    }
    out[operationId] = item;
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
  const authMode = normalizeAuthMode(input.authMode ?? input.auth_mode ?? 'none');
  const authContext = normalizeAuthContext(authMode, input.authContext ?? input.auth_context ?? {});
  const authProfiles = normalizeAuthProfiles(input.authProfiles ?? input.auth_profiles ?? {});
  const runtimeSecrets = {
    ...buildRuntimeSecrets(authMode, authContext),
    ...(Object.keys(authProfiles).length > 0 ? { authProfiles } : {})
  };
  const redactedAuthContext = redactAuthContext(authMode, authContext);
  const redactedAuthProfiles = redactAuthProfiles(authProfiles);
  const environmentProfile = (() => {
    const value = String(input.environmentProfile ?? input.environment_profile ?? 'mock').trim().toLowerCase();
    return ['mock', 'staging', 'prod_safe'].includes(value) ? value : 'mock';
  })();
  const passThreshold = Math.min(1, Math.max(0, Number(input.passThreshold ?? input.pass_threshold ?? 0.7) || 0.7));
  const criticalAssertions = normalizeCriticalAssertions(input.criticalAssertions ?? input.critical_assertions ?? []);
  const criticalOperationSet = new Set(
    normalizeOperationSelection(input.criticalOperations ?? input.critical_operations ?? [])
  );
  for (const item of criticalAssertions) {
    if (item?.operationId) criticalOperationSet.add(String(item.operationId));
  }

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
    environmentProfile,
    environmentTargets: normalizeEnvironmentTargets(input.environmentTargets ?? input.environment_targets ?? {}),
    passThreshold,
    releaseGate: normalizeReleaseGate(input.releaseGate ?? input.release_gate ?? {}, passThreshold),
    baseUrl:
      typeof input.baseUrl === 'string' && input.baseUrl.trim()
        ? input.baseUrl.trim()
        : DEFAULT_TEST_BASE_URL,
    authMode,
    authContext: redactedAuthContext,
    authProfiles: redactedAuthProfiles,
    criticalOperations: [...criticalOperationSet],
    criticalAssertions,
    resourceLimits: normalizeResourceLimits(input.resourceLimits ?? input.resource_limits ?? {}),
    reportMode: normalizeReportMode(input.reportMode ?? input.report_mode ?? 'full'),
    customerMode: input.customerMode !== false && input.customer_mode !== false,
    verifyPersistence: input.verifyPersistence !== false && input.verify_persistence !== false,
    customerRoot:
      typeof input.customerRoot === 'string' && input.customerRoot.trim()
        ? input.customerRoot.trim()
        : '~/.spec_test_pilot',
    runtimeSecrets
  };
}

export function createJob(request) {
  const store = getStore();
  const id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
  const now = new Date().toISOString();
  const incoming = request && typeof request === 'object' ? request : {};
  const { runtimeSecrets, ...publicRequest } = incoming;

  const job = {
    id,
    status: 'queued',
    createdAt: now,
    startedAt: null,
    completedAt: null,
    currentDomain: null,
    request: publicRequest,
    runtimeSecrets: runtimeSecrets && typeof runtimeSecrets === 'object' ? { ...runtimeSecrets } : {},
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
