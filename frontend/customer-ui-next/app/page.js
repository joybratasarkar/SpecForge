'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

const API_BASE = (process.env.NEXT_PUBLIC_BACKEND_BASE_URL || '').replace(/\/$/, '');
const DEFAULT_TEST_BASE_URL = (process.env.NEXT_PUBLIC_TEST_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const API_URL = (path) => `${API_BASE}${path}`;
const CONNECTION_MODE = API_BASE ? 'Direct backend' : 'Next.js proxy';

function sanitizeDomainToken(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
}

function inferDomainFromSpecName(value) {
  const raw = String(value || '').trim();
  if (!raw) return 'customer_api';
  const fileName = raw.split(/[\\/]/).pop() || raw;
  const withoutExt = fileName.replace(/\.[a-z0-9]+$/i, '');
  return sanitizeDomainToken(withoutExt) || 'customer_api';
}

function getField(obj, keys, fallback = null) {
  if (!obj || typeof obj !== 'object') return fallback;
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key] !== undefined) {
      return obj[key];
    }
  }
  return fallback;
}

function toNumber(value, fallback = null) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function normalizeStatus(value) {
  return String(value || 'idle').trim().toLowerCase() || 'idle';
}

function statusLabel(status) {
  const clean = normalizeStatus(status);
  if (clean === 'queued') return 'Queued';
  if (clean === 'running') return 'Running';
  if (clean === 'completed') return 'Completed';
  if (clean === 'failed') return 'Failed';
  return 'Idle';
}

function statusClass(status) {
  const clean = normalizeStatus(status);
  if (clean === 'completed') return 'pill-success';
  if (clean === 'failed') return 'pill-danger';
  if (clean === 'running' || clean === 'queued') return 'pill-warn';
  return 'pill-muted';
}

function formatDateTime(value) {
  const raw = String(value || '').trim();
  if (!raw) return 'n/a';
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(parsed);
}

function formatPercent(value) {
  const num = toNumber(value);
  if (num === null) return 'n/a';
  return new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits: 1
  }).format(num);
}

function formatBytes(value) {
  const num = toNumber(value);
  if (num === null || num < 0) return 'n/a';
  if (num < 1024) return `${num} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
  return `${(num / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDomainLabel(value) {
  const clean = String(value || '').trim();
  if (!clean) return 'n/a';
  return clean
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatReasonLabel(value) {
  const clean = String(value || '')
    .trim()
    .replace(/[_-]+/g, ' ');
  if (!clean) return 'n/a';
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function formatOwnerLabel(value) {
  const clean = String(value || '').trim().toLowerCase();
  if (clean === 'service_or_spec_issue') return 'Service / Spec';
  if (clean === 'agent_or_test_issue') return 'Agent / Test Logic';
  if (clean === 'environment_or_policy') return 'Environment / Policy';
  if (clean === 'unknown') return 'Unknown';
  if (!clean) return 'n/a';
  return formatReasonLabel(clean);
}

function stripPossibleBearerPrefix(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^bearer\s+/i.test(raw)) {
    return raw.replace(/^bearer\s+/i, '').trim();
  }
  return raw;
}

function buildSpecSummaryPayload({
  title = '',
  version = '',
  serverUrl = '',
  operations = []
} = {}) {
  const normalizedOperations = Array.isArray(operations)
    ? operations
      .map((item) => {
        if (!item || typeof item !== 'object') return null;
        const method = String(item.method || '').trim().toUpperCase();
        const path = String(item.path || '').trim();
        if (!method || !path) return null;
        const contentTypesRaw = Array.isArray(item.contentTypes) ? item.contentTypes : [];
        const contentTypes = Array.from(
          new Set(contentTypesRaw.map((ct) => String(ct || '').trim()).filter(Boolean))
        );
        const isForm = contentTypes.some((ct) => (
          ct === 'multipart/form-data' || ct === 'application/x-www-form-urlencoded'
        ));
        return {
          id: `${method} ${path}`,
          method,
          path,
          contentTypes,
          isForm
        };
      })
      .filter(Boolean)
    : [];

  normalizedOperations.sort((a, b) => {
    const byPath = a.path.localeCompare(b.path);
    if (byPath !== 0) return byPath;
    return a.method.localeCompare(b.method);
  });

  const endpointCount = new Set(normalizedOperations.map((item) => item.path)).size;

  return {
    title: String(title || '').trim(),
    version: String(version || '').trim(),
    serverUrl: String(serverUrl || '').trim(),
    endpointCount,
    operations: normalizedOperations
  };
}

function parseSpecFromJsonObject(specObj) {
  if (!specObj || typeof specObj !== 'object') {
    return buildSpecSummaryPayload();
  }
  const info = specObj.info && typeof specObj.info === 'object' ? specObj.info : {};
  const servers = Array.isArray(specObj.servers) ? specObj.servers : [];
  const serverUrl = servers.find((item) => item && typeof item.url === 'string')?.url || '';
  const paths = specObj.paths && typeof specObj.paths === 'object' ? specObj.paths : {};
  const methods = new Set(['get', 'post', 'put', 'patch', 'delete', 'options', 'head']);

  const operations = [];
  for (const [pathKey, pathValue] of Object.entries(paths)) {
    if (!pathValue || typeof pathValue !== 'object') continue;
    for (const [methodKey, operation] of Object.entries(pathValue)) {
      const method = String(methodKey || '').trim().toLowerCase();
      if (!methods.has(method)) continue;
      const operationObj = operation && typeof operation === 'object' ? operation : {};
      const requestBody = operationObj.requestBody && typeof operationObj.requestBody === 'object'
        ? operationObj.requestBody
        : {};
      const content = requestBody.content && typeof requestBody.content === 'object'
        ? requestBody.content
        : {};
      const contentTypes = Object.keys(content);
      operations.push({
        method: method.toUpperCase(),
        path: String(pathKey || ''),
        contentTypes
      });
    }
  }

  return buildSpecSummaryPayload({
    title: String(info.title || ''),
    version: String(info.version || ''),
    serverUrl: String(serverUrl || ''),
    operations
  });
}

function parseSpecFromYamlText(rawText) {
  const text = String(rawText || '');
  const lines = text.split(/\r?\n/);

  const titleMatch = text.match(/^[ \t]*title:[ \t]*(.+)$/im);
  const versionMatch = text.match(/^[ \t]*version:[ \t]*(.+)$/im);
  const serverMatch = text.match(/^[ \t]*url:[ \t]*(.+)$/im);

  const operations = [];
  const methods = new Set(['get', 'post', 'put', 'patch', 'delete', 'options', 'head']);

  let inPaths = false;
  let pathsIndent = -1;
  let currentPath = '';
  let currentPathIndent = -1;
  let currentMethod = '';
  let currentMethodIndent = -1;
  let methodBlockLines = [];

  const flushMethod = () => {
    if (!currentPath || !currentMethod) return;
    const blockText = methodBlockLines.join('\n').toLowerCase();
    const contentTypes = [];
    if (blockText.includes('multipart/form-data')) contentTypes.push('multipart/form-data');
    if (blockText.includes('application/x-www-form-urlencoded')) contentTypes.push('application/x-www-form-urlencoded');
    if (blockText.includes('application/json')) contentTypes.push('application/json');
    operations.push({
      method: currentMethod.toUpperCase(),
      path: currentPath,
      contentTypes
    });
    currentMethod = '';
    currentMethodIndent = -1;
    methodBlockLines = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const indent = (line.match(/^\s*/) || [''])[0].length;
    if (!trimmed || trimmed.startsWith('#')) continue;

    if (!inPaths) {
      if (/^paths:\s*$/i.test(trimmed)) {
        inPaths = true;
        pathsIndent = indent;
      }
      continue;
    }

    if (indent <= pathsIndent && !/^paths:\s*$/i.test(trimmed)) {
      flushMethod();
      break;
    }

    const pathMatch = line.match(/^\s*(\/[^:]*):\s*$/);
    if (pathMatch && indent > pathsIndent) {
      flushMethod();
      currentPath = String(pathMatch[1] || '').trim();
      currentPathIndent = indent;
      continue;
    }

    const methodMatch = line.match(/^\s*(get|post|put|patch|delete|options|head):\s*$/i);
    if (methodMatch && indent > currentPathIndent) {
      flushMethod();
      currentMethod = String(methodMatch[1] || '').toLowerCase();
      currentMethodIndent = indent;
      continue;
    }

    if (currentPath && currentMethod && indent > currentMethodIndent) {
      methodBlockLines.push(trimmed);
      continue;
    }

    if (currentPath && currentMethod && indent <= currentMethodIndent) {
      flushMethod();
    }
  }
  flushMethod();

  const filteredOperations = operations.filter((item) => methods.has(String(item.method || '').toLowerCase()));
  return buildSpecSummaryPayload({
    title: titleMatch ? String(titleMatch[1] || '').replace(/^['"]|['"]$/g, '') : '',
    version: versionMatch ? String(versionMatch[1] || '').replace(/^['"]|['"]$/g, '') : '',
    serverUrl: serverMatch ? String(serverMatch[1] || '').replace(/^['"]|['"]$/g, '') : '',
    operations: filteredOperations
  });
}

function parseSpecContent(rawText) {
  const raw = String(rawText || '').trim();
  if (!raw) return buildSpecSummaryPayload();

  try {
    const parsed = JSON.parse(raw);
    return parseSpecFromJsonObject(parsed);
  } catch {
    return parseSpecFromYamlText(raw);
  }
}

async function readErrorResponse(response) {
  try {
    const payload = await response.clone().json();
    const detail = payload?.detail || payload?.error || payload?.message;
    if (detail) return String(detail);
  } catch {
    // Fall through to text.
  }
  try {
    const text = await response.text();
    if (text.trim()) return text.trim();
  } catch {
    // Ignore.
  }
  return `${response.status} ${response.statusText}`.trim();
}

function summarizeAuthModeForPrompt(authMode, authContext) {
  const mode = String(authMode || 'none').trim().toLowerCase();
  const ctx = authContext && typeof authContext === 'object' ? authContext : {};
  if (mode === 'bearer') {
    return 'Bearer token is provided securely by customer at runtime.';
  }
  if (mode === 'api_key') {
    const keyName = String(ctx.apiKeyName || '').trim() || 'api_key';
    const keyIn = String(ctx.apiKeyIn || 'header').trim().toLowerCase() === 'query' ? 'query' : 'header';
    return `API key auth is required (${keyName} in ${keyIn}); value is provided securely at runtime.`;
  }
  return 'No explicit auth credentials supplied by customer.';
}

function buildPromptFromIntent(intent) {
  const lines = [];
  lines.push('Customer QA Intent');
  lines.push(`Intent: ${intent.customerIntent || 'n/a'}`);
  lines.push(`Auth mode: ${intent.authMode || 'none'}`);
  lines.push(`Auth context: ${summarizeAuthModeForPrompt(intent.authMode, intent.authContext)}`);
  const scopeMode = String(intent.scopeMode || 'full_spec').trim().toLowerCase();
  lines.push(
    `Scope mode: ${
      scopeMode === 'advanced'
        ? 'Advanced endpoint/mutation controls provided by customer.'
        : 'Full OpenAPI spec (all operations).'
    }`
  );
  const selectedOps = Array.isArray(intent.selectedOperations) ? intent.selectedOperations : [];
  const excludedOps = Array.isArray(intent.excludedOperations) ? intent.excludedOperations : [];
  const mutationRules = Array.isArray(intent.mutationRules) ? intent.mutationRules : [];
  if (scopeMode === 'advanced') {
    lines.push(`Selected operations: ${selectedOps.length}`);
    if (selectedOps.length > 0) {
      lines.push(`Operation shortlist: ${selectedOps.slice(0, 20).join(' | ')}`);
    }
    lines.push(`Excluded operations: ${excludedOps.length}`);
    lines.push(`Mutation rules: ${mutationRules.length}`);
    if (mutationRules.length > 0) {
      const compact = mutationRules
        .slice(0, 20)
        .map((row) => `${row.operationId} -> ${row.action}(${row.fieldName})`);
      lines.push(`Mutation shortlist: ${compact.join(' | ')}`);
    }
  }
  lines.push('Generate realistic, high-value API test scenarios using this intent.');
  return lines.join('\n');
}

function StatusTimeline({ status }) {
  const clean = normalizeStatus(status);
  const queued = clean === 'queued' || clean === 'running' || clean === 'completed' || clean === 'failed';
  const running = clean === 'running' || clean === 'completed' || clean === 'failed';
  const completed = clean === 'completed';
  const failed = clean === 'failed';

  const steps = [
    { id: 'queued', label: 'Run accepted', done: queued, active: clean === 'queued' },
    { id: 'running', label: 'Scenario execution', done: running, active: clean === 'running' },
    { id: 'done', label: failed ? 'Run failed' : 'Run completed', done: completed || failed, active: false }
  ];

  return (
    <ol className="timeline">
      {steps.map((step) => (
        <li
          key={step.id}
          className={`${step.done ? 'is-done' : ''} ${step.active ? 'is-active' : ''} ${failed && step.id === 'done' ? 'is-failed' : ''}`}
        >
          <span>{step.label}</span>
        </li>
      ))}
    </ol>
  );
}

function SpecUploadModal({ open, onClose, onSelectFile, uploading, error, currentFile }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Upload OpenAPI spec file">
      <div className="modal-card">
        <div className="modal-head">
          <h3>Upload OpenAPI File</h3>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="modal-subtitle">Accepted formats: .yaml, .yml, .json</p>
        <div className="modal-body">
          <label className="field">
            <span>Choose file</span>
            <input
              type="file"
              accept=".yaml,.yml,.json"
              onChange={onSelectFile}
              disabled={uploading}
            />
          </label>
          {uploading ? <p className="help">Uploading...</p> : null}
          {currentFile ? <p className="help">Current file: <code>{currentFile}</code></p> : null}
          {error ? <p className="error-text">{error}</p> : null}
        </div>
      </div>
    </div>
  );
}

function SpecTextModal({
  open,
  draft,
  onDraftChange,
  onClose,
  onSave,
  saving,
  error
}) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Paste OpenAPI spec text">
      <div className="modal-card">
        <div className="modal-head">
          <h3>Paste OpenAPI Text</h3>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="modal-subtitle">Paste YAML or JSON. We will store it as a temporary spec file for this run.</p>
        <div className="modal-body">
          <label className="field">
            <span>OpenAPI text</span>
            <textarea
              rows={16}
              value={draft}
              onChange={(event) => onDraftChange(event.target.value)}
              placeholder="openapi: 3.0.3&#10;info:&#10;  title: Example API&#10;  version: 1.0.0"
              disabled={saving}
            />
          </label>
          {error ? <p className="error-text">{error}</p> : null}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={onSave} disabled={saving}>
            {saving ? 'Saving...' : 'Use This Spec'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function HomePage() {
  const [customerIntent, setCustomerIntent] = useState('');

  const [authMode, setAuthMode] = useState('none');
  const [authBearerToken, setAuthBearerToken] = useState('');
  const [authApiKeyName, setAuthApiKeyName] = useState('X-API-Key');
  const [authApiKeyValue, setAuthApiKeyValue] = useState('');
  const [authApiKeyIn, setAuthApiKeyIn] = useState('header');

  const [uploadedSpec, setUploadedSpec] = useState({
    path: '',
    name: '',
    sizeBytes: 0,
    source: ''
  });
  const [specSummary, setSpecSummary] = useState(buildSpecSummaryPayload());
  const [selectedOperations, setSelectedOperations] = useState([]);
  const [endpointSearch, setEndpointSearch] = useState('');
  const [endpointMethodFilter, setEndpointMethodFilter] = useState('all');
  const [showOnlyFormEndpoints, setShowOnlyFormEndpoints] = useState(false);

  const [mutationRules, setMutationRules] = useState([]);
  const [advancedControlsOpen, setAdvancedControlsOpen] = useState(false);
  const [specUploadModalOpen, setSpecUploadModalOpen] = useState(false);
  const [specTextModalOpen, setSpecTextModalOpen] = useState(false);
  const [specTextDraft, setSpecTextDraft] = useState('');
  const [specUploading, setSpecUploading] = useState(false);
  const [specUploadError, setSpecUploadError] = useState('');

  const [job, setJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [jobIdInput, setJobIdInput] = useState('');

  const [connection, setConnection] = useState({
    status: 'idle',
    detail: CONNECTION_MODE
  });
  const [flash, setFlash] = useState({
    type: '',
    text: ''
  });

  const [reportDomain, setReportDomain] = useState('');
  const [reportJson, setReportJson] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  const [rawFormat, setRawFormat] = useState('json');
  const [rawReport, setRawReport] = useState('Start a run to view report content.');
  const [rawLoading, setRawLoading] = useState(false);

  const [generatedTests, setGeneratedTests] = useState([]);
  const [generatedTestsLoading, setGeneratedTestsLoading] = useState(false);
  const [selectedScriptKind, setSelectedScriptKind] = useState('');
  const [selectedScriptBody, setSelectedScriptBody] = useState('Select a generated script to preview.');
  const [scriptLoading, setScriptLoading] = useState(false);

  const eventSourceRef = useRef(null);
  const pollTimerRef = useRef(null);
  const jobsTimerRef = useRef(null);
  const flashTimerRef = useRef(null);
  const fallbackPollingRef = useRef(false);

  const inferredDomain = useMemo(() => {
    if (uploadedSpec.source === 'text') return 'customer_api';
    return inferDomainFromSpecName(uploadedSpec.name || uploadedSpec.path);
  }, [uploadedSpec.name, uploadedSpec.path, uploadedSpec.source]);

  const operationOptions = useMemo(() => {
    return Array.isArray(specSummary.operations) ? specSummary.operations : [];
  }, [specSummary.operations]);

  const visibleOperations = useMemo(() => {
    const query = String(endpointSearch || '').trim().toLowerCase();
    return operationOptions.filter((item) => {
      const method = String(item.method || '').toUpperCase();
      const path = String(item.path || '');
      const isForm = Boolean(item.isForm);
      if (endpointMethodFilter !== 'all' && method !== endpointMethodFilter) return false;
      if (showOnlyFormEndpoints && !isForm) return false;
      if (!query) return true;
      return `${method} ${path}`.toLowerCase().includes(query);
    });
  }, [endpointMethodFilter, endpointSearch, operationOptions, showOnlyFormEndpoints]);

  const selectedOperationsSet = useMemo(() => {
    return new Set(Array.isArray(selectedOperations) ? selectedOperations : []);
  }, [selectedOperations]);

  const authContext = useMemo(() => {
    const mode = String(authMode || '').trim().toLowerCase();
    if (mode === 'bearer') {
      return { bearerToken: stripPossibleBearerPrefix(authBearerToken) };
    }
    if (mode === 'api_key') {
      return {
        apiKeyName: String(authApiKeyName || '').trim(),
        apiKeyValue: String(authApiKeyValue || '').trim(),
        apiKeyIn: String(authApiKeyIn || 'header').trim().toLowerCase() === 'query' ? 'query' : 'header'
      };
    }
    return {};
  }, [
    authApiKeyIn,
    authApiKeyName,
    authApiKeyValue,
    authBearerToken,
    authMode
  ]);

  const authValidationError = useMemo(() => {
    const mode = String(authMode || '').trim().toLowerCase();
    if (mode === 'bearer' && !String(authBearerToken || '').trim()) {
      return 'Bearer token is required for Bearer auth.';
    }
    if (mode === 'api_key') {
      if (!String(authApiKeyName || '').trim()) return 'API key name is required.';
      if (!String(authApiKeyValue || '').trim()) return 'API key value is required.';
    }
    return '';
  }, [
    authApiKeyName,
    authApiKeyValue,
    authBearerToken,
    authMode
  ]);

  const validationError = useMemo(() => {
    if (!String(customerIntent || '').trim()) return 'Customer intent is required.';
    if (!String(uploadedSpec.path || '').trim()) return 'OpenAPI spec is required. Upload file or paste text.';
    if (authValidationError) return authValidationError;
    return '';
  }, [authValidationError, customerIntent, uploadedSpec.path]);

  const currentStatus = normalizeStatus(getField(job, ['status'], 'idle'));
  const currentJobId = String(getField(job, ['id'], '') || '');
  const currentDomain = String(getField(job, ['currentDomain', 'current_domain'], '') || '');
  const startedAt = getField(job, ['startedAt', 'started_at'], '');
  const completedAt = getField(job, ['completedAt', 'completed_at'], '');

  const resultsMap = useMemo(() => {
    const raw = getField(job, ['results'], {});
    return raw && typeof raw === 'object' ? raw : {};
  }, [job]);
  const resultEntries = useMemo(() => Object.entries(resultsMap), [resultsMap]);

  const summaryMetrics = useMemo(() => {
    let scenariosTotal = 0;
    let scenariosPassed = 0;
    let domainsFailed = 0;
    for (const [, result] of resultEntries) {
      const exitCode = toNumber(getField(result, ['exitCode', 'return_code'], 0), 0);
      if (exitCode !== 0) domainsFailed += 1;
      const summary = getField(result, ['summary'], {}) || {};
      const total = toNumber(getField(summary, ['totalScenarios', 'total_scenarios'], 0), 0);
      const passed = toNumber(getField(summary, ['passedScenarios', 'passed_scenarios'], 0), 0);
      scenariosTotal += Math.max(0, total);
      scenariosPassed += Math.max(0, Math.min(total, passed));
    }
    return {
      domainsDone: resultEntries.length,
      domainsFailed,
      scenariosTotal,
      scenariosPassed,
      passRate: scenariosTotal > 0 ? scenariosPassed / scenariosTotal : null
    };
  }, [resultEntries]);

  const summary = useMemo(() => {
    const raw = reportJson?.summary;
    return raw && typeof raw === 'object' ? raw : {};
  }, [reportJson]);

  const summaryCards = useMemo(() => {
    return [
      { label: 'Total scenarios', value: toNumber(getField(summary, ['total_scenarios', 'totalScenarios'], 0), 0) },
      { label: 'Passed', value: toNumber(getField(summary, ['passed_scenarios', 'passedScenarios'], 0), 0) },
      { label: 'Failed', value: toNumber(getField(summary, ['failed_scenarios', 'failedScenarios'], 0), 0) },
      { label: 'Pass rate', value: formatPercent(getField(summary, ['pass_rate', 'passRate'], null)) },
      { label: 'Flaky scenarios', value: toNumber(getField(summary, ['flaky_scenarios', 'flakyScenarios'], 0), 0) },
      {
        label: 'Quality gate',
        value: getField(summary, ['meets_quality_gate', 'meetsQualityGate'], null) === true ? 'Pass' : getField(summary, ['meets_quality_gate', 'meetsQualityGate'], null) === false ? 'Fail' : 'n/a'
      }
    ];
  }, [summary]);

  const failedExamples = useMemo(() => {
    const raw = getField(summary, ['failed_examples', 'failedExamples'], []);
    return Array.isArray(raw) ? raw : [];
  }, [summary]);

  const qualityFailReasons = useMemo(() => {
    const raw = getField(summary, ['quality_gate_fail_reasons', 'qualityGateFailReasons'], []);
    return Array.isArray(raw) ? raw : [];
  }, [summary]);

  const qualityWarnings = useMemo(() => {
    const raw = getField(summary, ['quality_gate_warnings', 'qualityGateWarnings'], []);
    return Array.isArray(raw) ? raw : [];
  }, [summary]);

  const failureTaxonomyRows = useMemo(() => {
    const raw = getField(summary, ['failure_taxonomy_breakdown', 'failureTaxonomyBreakdown'], {});
    if (!raw || typeof raw !== 'object') return [];
    return Object.entries(raw)
      .map(([name, count]) => ({ name, count: toNumber(count, 0) || 0 }))
      .sort((a, b) => b.count - a.count);
  }, [summary]);

  const testTypeRows = useMemo(() => {
    const raw = getField(summary, ['test_type_breakdown', 'testTypeBreakdown'], {});
    if (!raw || typeof raw !== 'object') return [];
    return Object.entries(raw).map(([name, stats]) => {
      const item = stats && typeof stats === 'object' ? stats : {};
      return {
        name,
        total: toNumber(getField(item, ['total'], 0), 0),
        passed: toNumber(getField(item, ['passed'], 0), 0),
        failed: toNumber(getField(item, ['failed'], 0), 0),
        suspect: toNumber(getField(item, ['suspect'], 0), 0),
        blocked: toNumber(getField(item, ['blocked'], 0), 0)
      };
    });
  }, [summary]);

  const failureDiagnosis = useMemo(() => {
    const raw = getField(summary, ['failure_diagnosis', 'failureDiagnosis'], {});
    return raw && typeof raw === 'object' ? raw : {};
  }, [summary]);

  const diagnosisAssessment = useMemo(() => {
    const raw = getField(failureDiagnosis, ['agent_assessment', 'agentAssessment'], {});
    return raw && typeof raw === 'object' ? raw : {};
  }, [failureDiagnosis]);

  const diagnosisOwnerRows = useMemo(() => {
    const rawChart = getField(failureDiagnosis, ['owner_chart', 'ownerChart'], []);
    if (Array.isArray(rawChart) && rawChart.length > 0) {
      return rawChart
        .map((item) => {
          const row = item && typeof item === 'object' ? item : {};
          const count = toNumber(getField(row, ['count'], 0), 0) || 0;
          const ratio = toNumber(getField(row, ['ratio'], 0), 0) || 0;
          return {
            owner: String(getField(row, ['owner'], '') || ''),
            count,
            ratio: Math.max(0, Math.min(1, ratio))
          };
        })
        .filter((row) => row.count > 0)
        .sort((a, b) => b.count - a.count);
    }

    const rawBreakdown = getField(failureDiagnosis, ['owner_breakdown', 'ownerBreakdown'], {});
    if (!rawBreakdown || typeof rawBreakdown !== 'object') return [];
    const total = Object.values(rawBreakdown).reduce((sum, item) => sum + (toNumber(item, 0) || 0), 0);
    return Object.entries(rawBreakdown)
      .map(([owner, countRaw]) => {
        const count = toNumber(countRaw, 0) || 0;
        return {
          owner,
          count,
          ratio: total > 0 ? count / total : 0
        };
      })
      .filter((row) => row.count > 0)
      .sort((a, b) => b.count - a.count);
  }, [failureDiagnosis]);

  const diagnosisRootCauseRows = useMemo(() => {
    const raw = getField(failureDiagnosis, ['root_cause_top', 'rootCauseTop'], []);
    if (!Array.isArray(raw)) return [];
    return raw
      .map((item) => {
        const row = item && typeof item === 'object' ? item : {};
        return {
          category: String(getField(row, ['category'], '') || ''),
          reason: String(getField(row, ['reason'], '') || ''),
          owner: String(getField(row, ['owner'], '') || ''),
          count: toNumber(getField(row, ['count'], 0), 0) || 0,
          ratio: toNumber(getField(row, ['ratio'], 0), 0) || 0
        };
      })
      .sort((a, b) => b.count - a.count);
  }, [failureDiagnosis]);

  const diagnosisEndpointRows = useMemo(() => {
    const raw = getField(failureDiagnosis, ['endpoint_diagnosis', 'endpointDiagnosis'], []);
    if (!Array.isArray(raw)) return [];
    return raw
      .map((item) => {
        const row = item && typeof item === 'object' ? item : {};
        const total = toNumber(getField(row, ['total'], 0), 0) || 0;
        const passed = toNumber(getField(row, ['passed'], 0), 0) || 0;
        const hardFailed = toNumber(getField(row, ['hard_failed', 'hardFailed'], 0), 0) || 0;
        const suspect = toNumber(getField(row, ['suspect'], 0), 0) || 0;
        const blocked = toNumber(getField(row, ['blocked'], 0), 0) || 0;
        const nonPass = hardFailed + suspect + blocked;
        const passRate = toNumber(getField(row, ['pass_rate', 'passRate'], null), null);
        const nonPassRate = toNumber(getField(row, ['non_pass_rate', 'nonPassRate'], null), null);
        const improvementsRaw = getField(row, ['improvements'], []);
        const reasonsRaw = getField(row, ['top_reasons', 'topReasons'], []);
        return {
          operationKey: String(getField(row, ['operation_key', 'operationKey'], '') || ''),
          method: String(getField(row, ['method'], '') || ''),
          endpoint: String(getField(row, ['endpoint'], '') || ''),
          status: String(getField(row, ['status'], '') || ''),
          total,
          passed,
          hardFailed,
          suspect,
          blocked,
          nonPass,
          passRate: passRate === null ? (total > 0 ? passed / total : 0) : passRate,
          nonPassRate: nonPassRate === null ? (total > 0 ? nonPass / total : 0) : nonPassRate,
          dominantOwner: String(getField(row, ['dominant_owner', 'dominantOwner'], '') || ''),
          dominantCategory: String(getField(row, ['dominant_category', 'dominantCategory'], '') || ''),
          improvements: Array.isArray(improvementsRaw) ? improvementsRaw.map((item) => String(item || '').trim()).filter(Boolean) : [],
          topReasons: Array.isArray(reasonsRaw)
            ? reasonsRaw.map((entry) => {
              const item = entry && typeof entry === 'object' ? entry : {};
              return {
                reason: String(getField(item, ['reason'], '') || ''),
                count: toNumber(getField(item, ['count'], 0), 0) || 0
              };
            }).filter((item) => item.reason)
            : []
        };
      })
      .sort((a, b) => b.nonPass - a.nonPass);
  }, [failureDiagnosis]);

  const diagnosisBacklogRows = useMemo(() => {
    const raw = getField(failureDiagnosis, ['improvement_backlog', 'improvementBacklog'], []);
    if (!Array.isArray(raw)) return [];
    return raw
      .map((item) => {
        const row = item && typeof item === 'object' ? item : {};
        const actions = getField(row, ['suggested_actions', 'suggestedActions'], []);
        return {
          priority: String(getField(row, ['priority'], '') || ''),
          category: String(getField(row, ['category'], '') || ''),
          owner: String(getField(row, ['owner'], '') || ''),
          count: toNumber(getField(row, ['count'], 0), 0) || 0,
          actions: Array.isArray(actions) ? actions.map((entry) => String(entry || '').trim()).filter(Boolean) : []
        };
      })
      .sort((a, b) => b.count - a.count);
  }, [failureDiagnosis]);

  const diagnosisOwnerMax = useMemo(
    () => diagnosisOwnerRows.reduce((acc, item) => Math.max(acc, toNumber(item?.count, 0) || 0), 0),
    [diagnosisOwnerRows]
  );
  const diagnosisRootCauseMax = useMemo(
    () => diagnosisRootCauseRows.reduce((acc, item) => Math.max(acc, toNumber(item?.count, 0) || 0), 0),
    [diagnosisRootCauseRows]
  );

  const setFlashMessage = useCallback((type, text, ttlMs = 5000) => {
    setFlash({
      type: String(type || ''),
      text: String(text || '')
    });
    if (flashTimerRef.current) {
      clearTimeout(flashTimerRef.current);
      flashTimerRef.current = null;
    }
    if (ttlMs > 0) {
      flashTimerRef.current = setTimeout(() => {
        setFlash({ type: '', text: '' });
        flashTimerRef.current = null;
      }, ttlMs);
    }
  }, []);

  const closeStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const loadJobs = useCallback(
    async ({ quiet = false } = {}) => {
      if (!quiet) setJobsLoading(true);
      try {
        const response = await fetch(API_URL('/api/jobs'), { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(await readErrorResponse(response));
        }
        const payload = await response.json();
        const list = Array.isArray(payload) ? payload : [];
        list.sort((a, b) => {
          const aTs = Date.parse(String(getField(a, ['createdAt', 'created_at'], '') || '')) || 0;
          const bTs = Date.parse(String(getField(b, ['createdAt', 'created_at'], '') || '')) || 0;
          return bTs - aTs;
        });
        setJobs(list);
        return list;
      } catch (error) {
        if (!quiet) {
          setFlashMessage('error', `Failed to load runs: ${String(error?.message || error)}`, 7000);
        }
        return [];
      } finally {
        if (!quiet) setJobsLoading(false);
      }
    },
    [setFlashMessage]
  );

  const loadJobSnapshot = useCallback(
    async (jobId, { quiet = false, tail = 1500 } = {}) => {
      const cleanJobId = String(jobId || '').trim();
      if (!cleanJobId) return null;
      try {
        const response = await fetch(API_URL(`/api/jobs/${encodeURIComponent(cleanJobId)}?tail=${tail}`), {
          cache: 'no-store'
        });
        if (!response.ok) throw new Error(await readErrorResponse(response));
        const payload = await response.json();
        setJob(payload);
        return payload;
      } catch (error) {
        if (!quiet) {
          setFlashMessage('error', `Failed to load run: ${String(error?.message || error)}`, 7000);
        }
        return null;
      }
    },
    [setFlashMessage]
  );

  const startPolling = useCallback(
    (jobId) => {
      const cleanJobId = String(jobId || '').trim();
      if (!cleanJobId) return;
      stopPolling();
      pollTimerRef.current = setInterval(() => {
        void loadJobSnapshot(cleanJobId, { quiet: true }).then((snapshot) => {
          const status = normalizeStatus(getField(snapshot, ['status'], 'idle'));
          if (status === 'completed' || status === 'failed') {
            stopPolling();
            void loadJobs({ quiet: true });
          }
        });
      }, 5000);
    },
    [loadJobSnapshot, loadJobs, stopPolling]
  );

  const attachRunStream = useCallback(
    (jobId) => {
      const cleanJobId = String(jobId || '').trim();
      if (!cleanJobId || typeof window === 'undefined') return;
      closeStream();
      stopPolling();
      fallbackPollingRef.current = false;

      if (typeof EventSource === 'undefined') {
        startPolling(cleanJobId);
        return;
      }

      const source = new EventSource(API_URL(`/api/jobs/${encodeURIComponent(cleanJobId)}/events`));
      eventSourceRef.current = source;

      source.addEventListener('snapshot', (event) => {
        try {
          const payload = JSON.parse(event.data);
          setJob(payload);
          const status = normalizeStatus(getField(payload, ['status'], 'idle'));
          if (status === 'completed' || status === 'failed') {
            closeStream();
            stopPolling();
            void loadJobs({ quiet: true });
          }
        } catch {
          // Ignore malformed event payload.
        }
      });

      source.addEventListener('done', () => {
        closeStream();
        stopPolling();
        void loadJobs({ quiet: true });
      });

      source.addEventListener('error', () => {
        if (!fallbackPollingRef.current) {
          fallbackPollingRef.current = true;
          startPolling(cleanJobId);
          setFlashMessage('warning', 'Realtime stream disconnected. Switched to polling.', 4500);
        }
      });
    },
    [closeStream, loadJobs, setFlashMessage, startPolling, stopPolling]
  );

  const connectToRun = useCallback(
    async (jobId, { quiet = false } = {}) => {
      const cleanJobId = String(jobId || '').trim();
      if (!cleanJobId) return;
      setJobIdInput(cleanJobId);
      const snapshot = await loadJobSnapshot(cleanJobId, { quiet });
      if (snapshot) attachRunStream(cleanJobId);
    },
    [attachRunStream, loadJobSnapshot]
  );

  const probeConnection = useCallback(async () => {
    setConnection({ status: 'checking', detail: CONNECTION_MODE });
    try {
      const response = await fetch(API_URL('/api/ping'), { cache: 'no-store' });
      if (!response.ok) throw new Error(await readErrorResponse(response));
      const payload = await response.json();
      const backend = String(payload?.backend || '').trim() || CONNECTION_MODE;
      setConnection({ status: 'ok', detail: backend });
    } catch (error) {
      setConnection({ status: 'error', detail: String(error?.message || error) });
    }
  }, []);

  const uploadSpecFile = useCallback(
    async (
      file,
      {
        source = 'upload',
        closeUploadModal = false,
        closeTextModal = false,
        quietSuccess = false,
        parsedSummary = null
      } = {}
    ) => {
      if (!file) return null;
      setSpecUploading(true);
      setSpecUploadError('');
      try {
        let summary = parsedSummary;
        if (!summary || typeof summary !== 'object') {
          try {
            const fileText = await file.text();
            summary = parseSpecContent(fileText);
          } catch {
            summary = buildSpecSummaryPayload();
          }
        }

        const form = new FormData();
        form.append('file', file);
        const response = await fetch(API_URL('/api/spec-upload'), {
          method: 'POST',
          body: form
        });
        if (!response.ok) throw new Error(await readErrorResponse(response));

        const payload = await response.json();
        const specPath = String(getField(payload, ['spec_path', 'specPath', 'path'], '')).trim();
        const originalName = String(getField(payload, ['original_filename', 'originalFilename', 'filename'], file.name || 'openapi.yaml')).trim();
        const sizeBytes = toNumber(getField(payload, ['size_bytes', 'sizeBytes'], file.size), file.size) || 0;
        if (!specPath) throw new Error('Upload did not return a spec path.');

        setUploadedSpec({
          path: specPath,
          name: originalName,
          sizeBytes,
          source: String(source || 'upload')
        });
        setSpecSummary(summary || buildSpecSummaryPayload());
        const operationIds = Array.isArray(summary?.operations)
          ? summary.operations.map((item) => String(item.id || '').trim()).filter(Boolean)
          : [];
        setSelectedOperations(operationIds);
        setEndpointSearch('');
        setEndpointMethodFilter('all');
        setShowOnlyFormEndpoints(false);
        setMutationRules([]);
        if (closeUploadModal) setSpecUploadModalOpen(false);
        if (closeTextModal) setSpecTextModalOpen(false);
        if (!quietSuccess) {
          setFlashMessage('success', `Spec ready: ${originalName}`, 4500);
        }
        return { path: specPath, name: originalName, sizeBytes };
      } catch (error) {
        const message = String(error?.message || error);
        setSpecUploadError(message);
        setFlashMessage('error', `Spec upload failed: ${message}`, 7000);
        return null;
      } finally {
        setSpecUploading(false);
      }
    },
    [setFlashMessage]
  );

  const onSpecFilePicked = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      void uploadSpecFile(file, { source: 'upload', closeUploadModal: true });
      event.target.value = '';
    },
    [uploadSpecFile]
  );

  const saveSpecFromTextModal = useCallback(async () => {
    const rawText = String(specTextDraft || '').trim();
    if (!rawText) {
      setSpecUploadError('OpenAPI text is required.');
      return;
    }
    const parsedSummary = parseSpecContent(rawText);
    const looksJson = rawText.startsWith('{');
    const ext = looksJson ? 'json' : 'yaml';
    const mime = looksJson ? 'application/json' : 'application/yaml';
    const virtualFile = new File([rawText], `openapi_manual.${ext}`, { type: mime });
    const uploaded = await uploadSpecFile(virtualFile, {
      source: 'text',
      closeTextModal: true,
      parsedSummary
    });
    if (uploaded) {
      setSpecTextDraft(rawText);
    }
  }, [specTextDraft, uploadSpecFile]);

  const clearSpecState = useCallback(() => {
    setUploadedSpec({ path: '', name: '', sizeBytes: 0, source: '' });
    setSpecSummary(buildSpecSummaryPayload());
    setSelectedOperations([]);
    setEndpointSearch('');
    setEndpointMethodFilter('all');
    setShowOnlyFormEndpoints(false);
    setMutationRules([]);
    setAdvancedControlsOpen(false);
    setSpecUploadError('');
  }, []);

  const toggleOperationSelection = useCallback((operationId) => {
    const cleanId = String(operationId || '').trim();
    if (!cleanId) return;
    setSelectedOperations((prev) => {
      const set = new Set(Array.isArray(prev) ? prev : []);
      if (set.has(cleanId)) {
        set.delete(cleanId);
      } else {
        set.add(cleanId);
      }
      return Array.from(set);
    });
  }, []);

  const selectAllVisibleOperations = useCallback(() => {
    const ids = visibleOperations.map((item) => String(item.id || '').trim()).filter(Boolean);
    setSelectedOperations(ids);
  }, [visibleOperations]);

  const selectOnlyFormOperations = useCallback(() => {
    const ids = operationOptions
      .filter((item) => Boolean(item?.isForm))
      .map((item) => String(item.id || '').trim())
      .filter(Boolean);
    setSelectedOperations(ids);
    setShowOnlyFormEndpoints(true);
  }, [operationOptions]);

  const addMutationRule = useCallback(() => {
    const firstOperation = selectedOperations[0] || operationOptions[0]?.id || '';
    const rowId = `rule_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    setMutationRules((prev) => [
      ...(Array.isArray(prev) ? prev : []),
      {
        id: rowId,
        operationId: String(firstOperation || ''),
        requestMode: 'auto',
        fieldName: '',
        action: 'delete',
        value: '',
        note: ''
      }
    ]);
  }, [operationOptions, selectedOperations]);

  const removeMutationRule = useCallback((rowId) => {
    const cleanId = String(rowId || '').trim();
    setMutationRules((prev) => (
      Array.isArray(prev) ? prev.filter((item) => String(item?.id || '') !== cleanId) : []
    ));
  }, []);

  const updateMutationRule = useCallback((rowId, key, value) => {
    const cleanId = String(rowId || '').trim();
    const cleanKey = String(key || '').trim();
    if (!cleanId || !cleanKey) return;
    setMutationRules((prev) => (
      Array.isArray(prev)
        ? prev.map((item) => (
          String(item?.id || '') === cleanId ? { ...item, [cleanKey]: value } : item
        ))
        : []
    ));
  }, []);

  const loadReportJson = useCallback(
    async (domain, { quiet = false } = {}) => {
      const cleanDomain = String(domain || '').trim();
      if (!currentJobId || !cleanDomain) return null;
      setReportLoading(true);
      try {
        const response = await fetch(
          API_URL(`/api/jobs/${encodeURIComponent(currentJobId)}/report/${encodeURIComponent(cleanDomain)}?format=json`),
          { cache: 'no-store' }
        );
        if (!response.ok) throw new Error(await readErrorResponse(response));
        const payload = await response.json();
        setReportJson(payload);
        if (rawFormat === 'json') {
          setRawReport(JSON.stringify(payload, null, 2));
        }
        return payload;
      } catch (error) {
        setReportJson(null);
        if (rawFormat === 'json') {
          setRawReport(`Unable to load JSON report.\n${String(error?.message || error)}`);
        }
        if (!quiet) {
          setFlashMessage('error', `Failed to load report: ${String(error?.message || error)}`, 7000);
        }
        return null;
      } finally {
        setReportLoading(false);
      }
    },
    [currentJobId, rawFormat, setFlashMessage]
  );

  const loadRawReport = useCallback(
    async (domain, format, { quiet = false } = {}) => {
      const cleanDomain = String(domain || '').trim();
      const cleanFormat = String(format || 'json').trim().toLowerCase();
      if (!currentJobId || !cleanDomain) return null;

      if (cleanFormat === 'json' && reportJson) {
        const pretty = JSON.stringify(reportJson, null, 2);
        setRawReport(pretty);
        return pretty;
      }

      setRawLoading(true);
      try {
        const response = await fetch(
          API_URL(`/api/jobs/${encodeURIComponent(currentJobId)}/report/${encodeURIComponent(cleanDomain)}?format=${encodeURIComponent(cleanFormat)}`),
          { cache: 'no-store' }
        );
        if (!response.ok) throw new Error(await readErrorResponse(response));
        if (cleanFormat === 'json') {
          const payload = await response.json();
          const pretty = JSON.stringify(payload, null, 2);
          setRawReport(pretty);
          if (!reportJson) setReportJson(payload);
          return pretty;
        }
        const text = await response.text();
        setRawReport(text);
        return text;
      } catch (error) {
        const message = String(error?.message || error);
        setRawReport(`Unable to load report.\n${message}`);
        if (!quiet) {
          setFlashMessage('error', `Failed to load raw report: ${message}`, 7000);
        }
        return null;
      } finally {
        setRawLoading(false);
      }
    },
    [currentJobId, reportJson, setFlashMessage]
  );

  const loadGeneratedScript = useCallback(
    async (domain, kind, { quiet = false } = {}) => {
      const cleanDomain = String(domain || '').trim();
      const cleanKind = String(kind || '').trim();
      if (!currentJobId || !cleanDomain || !cleanKind) return null;
      setScriptLoading(true);
      try {
        const response = await fetch(
          API_URL(`/api/jobs/${encodeURIComponent(currentJobId)}/generated-tests/${encodeURIComponent(cleanDomain)}/${encodeURIComponent(cleanKind)}`),
          { cache: 'no-store' }
        );
        if (!response.ok) throw new Error(await readErrorResponse(response));
        const text = await response.text();
        setSelectedScriptBody(text || 'Script file is empty.');
        return text;
      } catch (error) {
        const message = String(error?.message || error);
        setSelectedScriptBody(`Unable to load script.\n${message}`);
        if (!quiet) {
          setFlashMessage('error', `Failed to load script: ${message}`, 7000);
        }
        return null;
      } finally {
        setScriptLoading(false);
      }
    },
    [currentJobId, setFlashMessage]
  );

  const loadGeneratedTests = useCallback(
    async (domain, { quiet = false } = {}) => {
      const cleanDomain = String(domain || '').trim();
      if (!currentJobId || !cleanDomain) return [];
      setGeneratedTestsLoading(true);
      try {
        const response = await fetch(
          API_URL(`/api/jobs/${encodeURIComponent(currentJobId)}/generated-tests/${encodeURIComponent(cleanDomain)}`),
          { cache: 'no-store' }
        );
        if (!response.ok) throw new Error(await readErrorResponse(response));
        const payload = await response.json();
        const items = getField(payload, ['generated_tests', 'generatedTests'], []);
        const list = Array.isArray(items) ? items : [];
        setGeneratedTests(list);

        if (list.length === 0) {
          setSelectedScriptKind('');
          setSelectedScriptBody('No generated scripts available for this run.');
          return [];
        }

        const availableKinds = list.map((item) => String(getField(item, ['kind'], '')).trim()).filter(Boolean);
        const nextKind = availableKinds.includes(selectedScriptKind) ? selectedScriptKind : availableKinds[0];
        setSelectedScriptKind(nextKind);
        await loadGeneratedScript(cleanDomain, nextKind, { quiet: true });
        return list;
      } catch (error) {
        setGeneratedTests([]);
        setSelectedScriptKind('');
        setSelectedScriptBody('Unable to load generated scripts.');
        if (!quiet) {
          setFlashMessage('error', `Failed to load generated scripts: ${String(error?.message || error)}`, 7000);
        }
        return [];
      } finally {
        setGeneratedTestsLoading(false);
      }
    },
    [currentJobId, loadGeneratedScript, selectedScriptKind, setFlashMessage]
  );

  const startRun = useCallback(
    async (event) => {
      event.preventDefault();
      if (validationError) {
        setFlashMessage('error', validationError);
        return;
      }

      setSubmitting(true);
      try {
        const allOperationIds = operationOptions
          .map((item) => String(item.id || '').trim())
          .filter(Boolean);
        const useAdvancedScope = Boolean(advancedControlsOpen);
        let selectedOps = allOperationIds;
        let excludedOps = [];
        let normalizedMutationRules = [];

        if (useAdvancedScope) {
          const advancedSelected = allOperationIds.filter((id) => selectedOperationsSet.has(id));
          selectedOps = advancedSelected.length > 0 ? advancedSelected : allOperationIds;
          excludedOps = allOperationIds.filter((id) => !selectedOps.includes(id));
          normalizedMutationRules = (Array.isArray(mutationRules) ? mutationRules : [])
            .map((row) => ({
              operationId: String(row?.operationId || '').trim(),
              requestMode: String(row?.requestMode || 'auto').trim(),
              fieldName: String(row?.fieldName || '').trim(),
              action: String(row?.action || 'delete').trim(),
              value: String(row?.value || ''),
              note: String(row?.note || '').trim()
            }))
            .filter((row) => row.operationId && row.fieldName && row.action);
        }

        const intent = {
          customerIntent: String(customerIntent || '').trim(),
          authMode: String(authMode || '').trim(),
          authContext,
          scopeMode: useAdvancedScope ? 'advanced' : 'full_spec',
          selectedOperations: selectedOps,
          excludedOperations: excludedOps,
          mutationRules: normalizedMutationRules
        };

        const domainToken = inferredDomain || 'customer_api';
        const payload = {
          domains: [domainToken],
          specPaths: { [domainToken]: uploadedSpec.path },
          tenantId: 'customer_default',
          workspaceId: 'customer_default',
          scriptKind: 'python_pytest',
          maxScenarios: 96,
          passThreshold: 0.7,
          baseUrl: DEFAULT_TEST_BASE_URL,
          environmentProfile: 'mock',
          verifyPersistence: true,
          customerMode: true,
          prompt: buildPromptFromIntent(intent),
          authMode: intent.authMode,
          authContext: intent.authContext,
          ...(useAdvancedScope
            ? {
                includeOperations: intent.selectedOperations,
                excludeOperations: intent.excludedOperations,
                requestMutationRules: intent.mutationRules
              }
            : {})
        };

        const response = await fetch(API_URL('/api/jobs'), {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!response.ok) throw new Error(await readErrorResponse(response));

        const data = await response.json();
        const jobId = String(getField(data, ['jobId', 'job_id'], '')).trim();
        if (!jobId) throw new Error('Run created but job id is missing in response.');

        setActiveTab('overview');
        setRawFormat('json');
        setRawReport('Loading report...');
        setReportJson(null);
        setGeneratedTests([]);
        setSelectedScriptKind('');
        setSelectedScriptBody('Select a generated script to preview.');

        await loadJobs({ quiet: true });
        await connectToRun(jobId, { quiet: true });
        setFlashMessage('success', `Run started: ${jobId}`, 5000);
      } catch (error) {
        setFlashMessage('error', `Failed to start run: ${String(error?.message || error)}`, 7000);
      } finally {
        setSubmitting(false);
      }
    },
    [
      authMode,
      authContext,
      customerIntent,
      advancedControlsOpen,
      connectToRun,
      inferredDomain,
      loadJobs,
      mutationRules,
      operationOptions,
      selectedOperationsSet,
      setFlashMessage,
      uploadedSpec.path,
      validationError
    ]
  );

  useEffect(() => {
    void probeConnection();
    void loadJobs();
    jobsTimerRef.current = setInterval(() => {
      void loadJobs({ quiet: true });
    }, 15000);

    return () => {
      if (jobsTimerRef.current) {
        clearInterval(jobsTimerRef.current);
        jobsTimerRef.current = null;
      }
      if (flashTimerRef.current) {
        clearTimeout(flashTimerRef.current);
        flashTimerRef.current = null;
      }
      closeStream();
      stopPolling();
    };
  }, [closeStream, loadJobs, probeConnection, stopPolling]);

  useEffect(() => {
    if (job) return;
    const running = jobs.find((item) => {
      const status = normalizeStatus(getField(item, ['status'], 'idle'));
      return status === 'running' || status === 'queued';
    });
    if (!running) return;
    const id = String(getField(running, ['id'], '')).trim();
    if (id) {
      void connectToRun(id, { quiet: true });
    }
  }, [connectToRun, job, jobs]);

  useEffect(() => {
    const domains = resultEntries.map(([domain]) => domain);
    if (domains.length === 0) {
      setReportDomain('');
      setReportJson(null);
      setRawReport('Start a run to view report content.');
      setGeneratedTests([]);
      setSelectedScriptKind('');
      setSelectedScriptBody('Select a generated script to preview.');
      return;
    }
    if (!domains.includes(reportDomain)) {
      setReportDomain(domains[0]);
    }
  }, [reportDomain, resultEntries]);

  useEffect(() => {
    if (!currentJobId || !reportDomain) return;
    void loadReportJson(reportDomain, { quiet: true });
    void loadGeneratedTests(reportDomain, { quiet: true });
  }, [currentJobId, loadGeneratedTests, loadReportJson, reportDomain]);

  useEffect(() => {
    if (!currentJobId || !reportDomain) return;
    void loadRawReport(reportDomain, rawFormat, { quiet: true });
  }, [currentJobId, loadRawReport, rawFormat, reportDomain]);

  useEffect(() => {
    const validOperationIds = new Set(
      operationOptions.map((item) => String(item.id || '').trim()).filter(Boolean)
    );
    setSelectedOperations((prev) => {
      const list = Array.isArray(prev) ? prev : [];
      const filtered = list.filter((id) => validOperationIds.has(String(id || '').trim()));
      if (filtered.length === list.length) return list;
      return filtered;
    });
    setMutationRules((prev) => {
      if (!Array.isArray(prev)) return [];
      return prev.filter((row) => validOperationIds.has(String(row?.operationId || '').trim()));
    });
  }, [operationOptions]);

  return (
    <div className="page-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">SpecForge QA Studio</p>
          <h1>Customer Intent + API QA</h1>
          <p className="subtitle">
            Add OpenAPI, configure auth and endpoint scope, then run negative-first QA with interactive reporting.
          </p>
        </div>
        <div className="connection-block">
          <span className={`pill ${connection.status === 'ok' ? 'pill-success' : connection.status === 'error' ? 'pill-danger' : 'pill-muted'}`}>
            {connection.status === 'checking' ? 'Checking' : connection.status === 'ok' ? 'Connected' : connection.status === 'error' ? 'Connection Error' : 'Idle'}
          </span>
          <span className="mono-chip">{connection.detail}</span>
          <button type="button" className="btn btn-ghost" onClick={probeConnection}>
            Recheck
          </button>
        </div>
      </header>

      {flash.text ? <div className={`alert alert-${flash.type || 'info'}`}>{flash.text}</div> : null}

      <main className="layout">
        <aside className="left-column">
          <section className="panel">
            <div className="panel-head">
              <h2>1. Customer Intent</h2>
            </div>
            <form onSubmit={startRun}>
              <label className="field">
                <span>Customer intent</span>
                <textarea
                  rows={6}
                  value={customerIntent}
                  onChange={(event) => setCustomerIntent(event.target.value)}
                  placeholder="Example: Validate checkout and payment APIs for auth abuse, invalid payloads, boundary conditions, and order-state dependency failures. Include PCI-related negative checks."
                />
                <p className="help">
                  Include business-critical flows, compliance constraints, and known risky endpoints in one intent block.
                </p>
              </label>

              <div className="field">
                <span>OpenAPI specification</span>
                <div className="intent-upload-box">
                  <div className="actions">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => {
                        setSpecUploadError('');
                        setSpecUploadModalOpen(true);
                      }}
                      disabled={specUploading}
                    >
                      Upload Spec File
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => {
                        setSpecUploadError('');
                        setSpecTextModalOpen(true);
                      }}
                      disabled={specUploading}
                    >
                      Paste Spec Text
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={clearSpecState}
                      disabled={specUploading || !uploadedSpec.path}
                    >
                      Clear
                    </button>
                  </div>
                  {specUploading ? <p className="help">Saving spec...</p> : null}
                  {specUploadError ? <p className="error-text">{specUploadError}</p> : null}
                  {uploadedSpec.path ? (
                    <div className="help-list">
                      <p className="help">Active spec: <code>{uploadedSpec.name || uploadedSpec.path}</code> ({formatBytes(uploadedSpec.sizeBytes)})</p>
                      <p className="help">Source: <strong>{uploadedSpec.source === 'text' ? 'Pasted text' : 'File upload'}</strong> | Domain token: <code>{inferredDomain}</code></p>
                      <p className="help">Parsed: <strong>{specSummary.title || 'Untitled API'}</strong> {specSummary.version ? `(v${specSummary.version})` : ''}</p>
                      <p className="help">Endpoints: <strong>{specSummary.endpointCount}</strong> | Operations: <strong>{operationOptions.length}</strong> | First server: <code>{specSummary.serverUrl || 'n/a'}</code></p>
                    </div>
                  ) : (
                    <p className="help">No spec selected yet.</p>
                  )}
                </div>
              </div>

              <label className="field">
                <span>Auth mode</span>
                <select value={authMode} onChange={(event) => setAuthMode(event.target.value)}>
                  <option value="none">None</option>
                  <option value="bearer">Bearer token</option>
                  <option value="api_key">API key</option>
                </select>
              </label>

              {authMode === 'bearer' ? (
                <label className="field">
                  <span>Bearer token</span>
                  <input
                    type="password"
                    value={authBearerToken}
                    onChange={(event) => setAuthBearerToken(event.target.value)}
                    placeholder="Paste bearer token"
                    autoComplete="off"
                  />
                  <p className="help">Token is sent securely and redacted in run metadata.</p>
                </label>
              ) : null}

              {authMode === 'api_key' ? (
                <div className="field-grid">
                  <label className="field">
                    <span>API key name</span>
                    <input
                      value={authApiKeyName}
                      onChange={(event) => setAuthApiKeyName(event.target.value)}
                      placeholder="X-API-Key"
                    />
                  </label>
                  <label className="field">
                    <span>API key value</span>
                    <input
                      type="password"
                      value={authApiKeyValue}
                      onChange={(event) => setAuthApiKeyValue(event.target.value)}
                      placeholder="Paste API key"
                      autoComplete="off"
                    />
                  </label>
                  <label className="field">
                    <span>API key location</span>
                    <select value={authApiKeyIn} onChange={(event) => setAuthApiKeyIn(event.target.value)}>
                      <option value="header">Header</option>
                      <option value="query">Query</option>
                    </select>
                  </label>
                </div>
              ) : null}

              <div className="field">
                <span>Scope mode</span>
                <p className="help">
                  Default run uses the full OpenAPI spec contract (all operations). Advanced scope and mutation overrides are optional.
                </p>
                <div className="actions">
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => setAdvancedControlsOpen((prev) => !prev)}
                    disabled={operationOptions.length === 0}
                  >
                    {advancedControlsOpen ? 'Hide Advanced Controls' : 'Show Advanced Controls'}
                  </button>
                </div>
              </div>

              {advancedControlsOpen ? (
                <>
                  <div className="field">
                    <span>Endpoint scope (advanced)</span>
                    {operationOptions.length === 0 ? (
                      <div className="empty-box">Upload/paste an OpenAPI spec to choose endpoints.</div>
                    ) : (
                      <div className="scope-box">
                        <div className="scope-actions">
                          <button type="button" className="btn btn-ghost" onClick={selectAllVisibleOperations}>
                            Select Visible
                          </button>
                          <button type="button" className="btn btn-ghost" onClick={selectOnlyFormOperations}>
                            Select Form Endpoints
                          </button>
                          <button type="button" className="btn btn-ghost" onClick={() => setSelectedOperations([])}>
                            Clear Selection
                          </button>
                        </div>
                        <div className="scope-filters">
                          <input
                            value={endpointSearch}
                            onChange={(event) => setEndpointSearch(event.target.value)}
                            placeholder="Search method or path..."
                          />
                          <select
                            value={endpointMethodFilter}
                            onChange={(event) => setEndpointMethodFilter(event.target.value)}
                          >
                            <option value="all">All methods</option>
                            <option value="GET">GET</option>
                            <option value="POST">POST</option>
                            <option value="PUT">PUT</option>
                            <option value="PATCH">PATCH</option>
                            <option value="DELETE">DELETE</option>
                          </select>
                          <label className="check-inline">
                            <input
                              type="checkbox"
                              checked={showOnlyFormEndpoints}
                              onChange={(event) => setShowOnlyFormEndpoints(event.target.checked)}
                            />
                            <span>Form only</span>
                          </label>
                        </div>
                        <div className="scope-list">
                          {visibleOperations.length === 0 ? (
                            <div className="empty-box">No operations match current filter.</div>
                          ) : (
                            visibleOperations.map((item) => (
                              <label key={item.id} className="scope-item">
                                <input
                                  type="checkbox"
                                  checked={selectedOperationsSet.has(item.id)}
                                  onChange={() => toggleOperationSelection(item.id)}
                                />
                                <span className="scope-item-main">
                                  <strong>{item.method}</strong> <code>{item.path}</code>
                                </span>
                                <span className="scope-item-meta">
                                  {item.isForm ? 'Form-data capable' : 'JSON/other'}
                                </span>
                              </label>
                            ))
                          )}
                        </div>
                        <p className="help">
                          Selected: <strong>{selectedOperationsSet.size}</strong> / {operationOptions.length}
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="field">
                    <span>Request mutation rules (advanced)</span>
                    {operationOptions.length === 0 ? (
                      <div className="empty-box">Add OpenAPI first to create field-level mutation rules.</div>
                    ) : (
                      <div className="mutation-box">
                        <div className="scope-actions">
                          <button type="button" className="btn btn-ghost" onClick={addMutationRule}>
                            Add Rule
                          </button>
                        </div>
                        {mutationRules.length === 0 ? (
                          <p className="help">No mutation rules yet. Add rules to force delete/modify/invalid field tests.</p>
                        ) : (
                          <div className="mutation-list">
                            {mutationRules.map((rule) => (
                              <div key={rule.id} className="mutation-row">
                                <select
                                  value={rule.operationId}
                                  onChange={(event) => updateMutationRule(rule.id, 'operationId', event.target.value)}
                                >
                                  {operationOptions.map((op) => (
                                    <option key={op.id} value={op.id}>
                                      {op.id}
                                    </option>
                                  ))}
                                </select>
                                <select
                                  value={rule.requestMode}
                                  onChange={(event) => updateMutationRule(rule.id, 'requestMode', event.target.value)}
                                >
                                  <option value="auto">Auto</option>
                                  <option value="json">JSON</option>
                                  <option value="multipart/form-data">Form-data</option>
                                  <option value="application/x-www-form-urlencoded">x-www-form-urlencoded</option>
                                </select>
                                <input
                                  value={rule.fieldName}
                                  onChange={(event) => updateMutationRule(rule.id, 'fieldName', event.target.value)}
                                  placeholder="field name"
                                />
                                <select
                                  value={rule.action}
                                  onChange={(event) => updateMutationRule(rule.id, 'action', event.target.value)}
                                >
                                  <option value="delete">Delete field</option>
                                  <option value="set_empty">Set empty</option>
                                  <option value="invalid_type">Invalid type</option>
                                  <option value="override_value">Override value</option>
                                </select>
                                <input
                                  value={rule.value}
                                  onChange={(event) => updateMutationRule(rule.id, 'value', event.target.value)}
                                  placeholder="override value"
                                />
                                <input
                                  value={rule.note}
                                  onChange={(event) => updateMutationRule(rule.id, 'note', event.target.value)}
                                  placeholder="note"
                                />
                                <button
                                  type="button"
                                  className="btn btn-ghost"
                                  onClick={() => removeMutationRule(rule.id)}
                                >
                                  Remove
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </>
              ) : null}

              {validationError ? <p className="error-text">{validationError}</p> : null}

              <div className="actions">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={submitting || Boolean(validationError)}
                >
                  {submitting ? 'Starting...' : 'Start QA Run'}
                </button>
              </div>
            </form>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Run History</h2>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => void loadJobs()}
                disabled={jobsLoading}
              >
                {jobsLoading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>

            <div className="load-row">
              <input
                value={jobIdInput}
                onChange={(event) => setJobIdInput(event.target.value)}
                placeholder="Load run id"
              />
              <button type="button" className="btn btn-secondary" onClick={() => void connectToRun(jobIdInput)}>
                Load
              </button>
            </div>

            <div className="run-list">
              {jobs.length === 0 ? (
                <div className="empty-box">No runs yet.</div>
              ) : (
                jobs.slice(0, 20).map((item) => {
                  const id = String(getField(item, ['id'], '') || '');
                  const status = getField(item, ['status'], 'idle');
                  return (
                    <button
                      key={id}
                      type="button"
                      className={`run-item ${id === currentJobId ? 'is-active' : ''}`}
                      onClick={() => void connectToRun(id)}
                    >
                      <div className="run-item-head">
                        <code>{id}</code>
                        <span className={`pill ${statusClass(status)}`}>{statusLabel(status)}</span>
                      </div>
                      <p>{formatDateTime(getField(item, ['createdAt', 'created_at'], ''))}</p>
                    </button>
                  );
                })
              )}
            </div>
          </section>
        </aside>

        <section className="right-column">
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Run Snapshot</h2>
                <p className="muted-text">{currentJobId ? `Run ${currentJobId}` : 'No run selected'}</p>
              </div>
              <span className={`pill ${statusClass(currentStatus)}`}>{statusLabel(currentStatus)}</span>
            </div>

            <StatusTimeline status={currentStatus} />

            <div className="metric-grid">
              <div className="metric">
                <span>Domains done</span>
                <strong>{summaryMetrics.domainsDone}</strong>
              </div>
              <div className="metric">
                <span>Domain failures</span>
                <strong>{summaryMetrics.domainsFailed}</strong>
              </div>
              <div className="metric">
                <span>Scenarios</span>
                <strong>{summaryMetrics.scenariosTotal}</strong>
              </div>
              <div className="metric">
                <span>Pass rate</span>
                <strong>{formatPercent(summaryMetrics.passRate)}</strong>
              </div>
            </div>

            <div className="meta-row">
              <span>Current domain: <strong>{currentDomain ? formatDomainLabel(currentDomain) : 'n/a'}</strong></span>
              <span>Started: <strong>{formatDateTime(startedAt)}</strong></span>
              <span>Completed: <strong>{formatDateTime(completedAt)}</strong></span>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head panel-head-wrap">
              <div>
                <h2>2. Results and Report</h2>
                <p className="muted-text">Human-readable report with failures, quality gate reasons, and generated tests.</p>
              </div>
              <div className="toolbar">
                <select
                  value={reportDomain}
                  onChange={(event) => setReportDomain(event.target.value)}
                  disabled={resultEntries.length === 0}
                >
                  {resultEntries.length === 0 ? (
                    <option value="">No domains</option>
                  ) : (
                    resultEntries.map(([domain]) => (
                      <option key={domain} value={domain}>
                        {formatDomainLabel(domain)}
                      </option>
                    ))
                  )}
                </select>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={!reportDomain || reportLoading}
                  onClick={() => {
                    if (!reportDomain) return;
                    void loadReportJson(reportDomain);
                    void loadRawReport(reportDomain, rawFormat, { quiet: true });
                    void loadGeneratedTests(reportDomain, { quiet: true });
                  }}
                >
                  {reportLoading ? 'Loading...' : 'Refresh'}
                </button>
              </div>
            </div>

            {resultEntries.length === 0 ? (
              <div className="empty-box">Run a test job to view report details.</div>
            ) : (
              <>
                <nav className="tab-row" aria-label="Report sections">
                  <button
                    type="button"
                    className={`tab-btn ${activeTab === 'overview' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('overview')}
                  >
                    Overview
                  </button>
                  <button
                    type="button"
                    className={`tab-btn ${activeTab === 'failures' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('failures')}
                  >
                    Failures
                  </button>
                  <button
                    type="button"
                    className={`tab-btn ${activeTab === 'scripts' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('scripts')}
                  >
                    Test Scripts
                  </button>
                  <button
                    type="button"
                    className={`tab-btn ${activeTab === 'raw' ? 'is-active' : ''}`}
                    onClick={() => setActiveTab('raw')}
                  >
                    Raw
                  </button>
                </nav>

                {activeTab === 'overview' ? (
                  <div className="tab-content">
                    {reportLoading ? <p className="muted-text">Loading report...</p> : null}

                    <div className="summary-grid">
                      {summaryCards.map((card) => (
                        <div className="summary-card" key={card.label}>
                          <span>{card.label}</span>
                          <strong>{String(card.value)}</strong>
                        </div>
                      ))}
                    </div>

                    <div className="quality-block">
                      <h3>Quality Gate Signals</h3>
                      <div className="chip-row">
                        {qualityFailReasons.length === 0 ? (
                          <span className="chip chip-success">No blocking quality gate failures</span>
                        ) : (
                          qualityFailReasons.map((reason) => (
                            <span key={reason} className="chip chip-danger">{formatReasonLabel(reason)}</span>
                          ))
                        )}
                        {qualityWarnings.map((warning) => (
                          <span key={warning} className="chip chip-warn">{formatReasonLabel(warning)}</span>
                        ))}
                      </div>
                    </div>

                    <div className="quality-block">
                      <h3>Failure Taxonomy</h3>
                      {failureTaxonomyRows.length === 0 ? (
                        <p className="muted-text">No taxonomy data in current report.</p>
                      ) : (
                        <div className="chip-row">
                          {failureTaxonomyRows.map((item) => (
                            <span key={item.name} className="chip chip-muted">
                              {formatReasonLabel(item.name)}: <strong>{item.count}</strong>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="quality-block">
                      <h3>Failure Diagnosis</h3>
                      {Object.keys(failureDiagnosis).length === 0 ? (
                        <p className="muted-text">No deep diagnosis in this report. Re-run with latest agent build.</p>
                      ) : (
                        <div className="diagnosis-stack">
                          <div className="chip-row">
                            <span className="chip chip-muted">
                              Assessment: <strong>{formatReasonLabel(getField(diagnosisAssessment, ['assessment'], 'n/a'))}</strong>
                            </span>
                            <span className="chip chip-muted">
                              Dominant owner: <strong>{formatOwnerLabel(getField(diagnosisAssessment, ['dominant_owner', 'dominantOwner'], ''))}</strong>
                            </span>
                            <span className="chip chip-muted">
                              Confidence: <strong>{formatPercent(getField(diagnosisAssessment, ['confidence'], 0))}</strong>
                            </span>
                            <span className="chip chip-danger">
                              Non-pass: <strong>{toNumber(getField(failureDiagnosis, ['non_pass_total', 'nonPassTotal'], 0), 0)}</strong>
                            </span>
                            <span className="chip chip-danger">
                              Hard fail: <strong>{toNumber(getField(failureDiagnosis, ['hard_fail_total', 'hardFailTotal'], 0), 0)}</strong>
                            </span>
                            <span className="chip chip-warn">
                              Suspect: <strong>{toNumber(getField(failureDiagnosis, ['suspect_total', 'suspectTotal'], 0), 0)}</strong>
                            </span>
                          </div>

                          <div className="chart-grid">
                            <section className="chart-card">
                              <h4>Failure Ownership</h4>
                              {diagnosisOwnerRows.length === 0 ? (
                                <p className="muted-text">No ownership data.</p>
                              ) : (
                                <div className="bar-chart">
                                  {diagnosisOwnerRows.map((row) => {
                                    const count = toNumber(row.count, 0) || 0;
                                    const width = diagnosisOwnerMax > 0 ? Math.max(6, (count / diagnosisOwnerMax) * 100) : 0;
                                    return (
                                      <div key={`${row.owner}-${count}`} className="bar-row">
                                        <div className="bar-label">
                                          <span>{formatOwnerLabel(row.owner)}</span>
                                          <span>{count}</span>
                                        </div>
                                        <div className="bar-track">
                                          <div className="bar-fill" style={{ width: `${width}%` }} />
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </section>

                            <section className="chart-card">
                              <h4>Top Root Causes</h4>
                              {diagnosisRootCauseRows.length === 0 ? (
                                <p className="muted-text">No root-cause clusters.</p>
                              ) : (
                                <div className="bar-chart">
                                  {diagnosisRootCauseRows.slice(0, 8).map((row) => {
                                    const count = toNumber(row.count, 0) || 0;
                                    const width = diagnosisRootCauseMax > 0 ? Math.max(6, (count / diagnosisRootCauseMax) * 100) : 0;
                                    return (
                                      <div key={`${row.category}-${row.reason}-${count}`} className="bar-row">
                                        <div className="bar-label">
                                          <span>{formatReasonLabel(row.reason || row.category)}</span>
                                          <span>{count}</span>
                                        </div>
                                        <div className="bar-track">
                                          <div className="bar-fill bar-fill-warn" style={{ width: `${width}%` }} />
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </section>
                          </div>

                          <section className="chart-card">
                            <h4>Endpoint Hotspots</h4>
                            {diagnosisEndpointRows.length === 0 ? (
                              <p className="muted-text">No endpoint diagnosis available.</p>
                            ) : (
                              <div className="table-wrap">
                                <table className="data-table">
                                  <thead>
                                    <tr>
                                      <th>Operation</th>
                                      <th>Status</th>
                                      <th>Pass Rate</th>
                                      <th>Hard Fail</th>
                                      <th>Suspect</th>
                                      <th>Dominant Owner</th>
                                      <th>Dominant Cause</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {diagnosisEndpointRows.slice(0, 12).map((row) => (
                                      <tr key={row.operationKey}>
                                        <td><code>{row.operationKey || `${row.method} ${row.endpoint}`}</code></td>
                                        <td>{formatReasonLabel(row.status)}</td>
                                        <td>{formatPercent(row.passRate)}</td>
                                        <td>{row.hardFailed}</td>
                                        <td>{row.suspect}</td>
                                        <td>{formatOwnerLabel(row.dominantOwner)}</td>
                                        <td>{formatReasonLabel(row.dominantCategory)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </section>
                        </div>
                      )}
                    </div>

                    <div className="quality-block">
                      <h3>Improvement Backlog</h3>
                      {diagnosisBacklogRows.length === 0 ? (
                        <p className="muted-text">No prioritized improvement backlog in this report.</p>
                      ) : (
                        <div className="failure-list">
                          {diagnosisBacklogRows.slice(0, 8).map((item, idx) => (
                            <article key={`${item.priority}-${item.category}-${idx}`} className="failure-item">
                              <div className="failure-head">
                                <h3>{formatReasonLabel(item.category)}</h3>
                                <span className={`pill ${item.priority === 'P0' ? 'pill-danger' : item.priority === 'P1' ? 'pill-warn' : 'pill-muted'}`}>
                                  {item.priority || 'P2'}
                                </span>
                              </div>
                              <p className="failure-meta">Owner: <strong>{formatOwnerLabel(item.owner)}</strong> | Evidence: <strong>{item.count}</strong></p>
                              {item.actions.map((action) => (
                                <p className="failure-action" key={action}>{action}</p>
                              ))}
                            </article>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="quality-block">
                      <h3>Scenario Type Breakdown</h3>
                      {testTypeRows.length === 0 ? (
                        <p className="muted-text">No scenario type breakdown available.</p>
                      ) : (
                        <div className="table-wrap">
                          <table className="data-table">
                            <thead>
                              <tr>
                                <th>Type</th>
                                <th>Total</th>
                                <th>Passed</th>
                                <th>Failed</th>
                                <th>Suspect</th>
                                <th>Blocked</th>
                              </tr>
                            </thead>
                            <tbody>
                              {testTypeRows.map((row) => (
                                <tr key={row.name}>
                                  <td>{formatReasonLabel(row.name)}</td>
                                  <td>{row.total}</td>
                                  <td>{row.passed}</td>
                                  <td>{row.failed}</td>
                                  <td>{row.suspect}</td>
                                  <td>{row.blocked}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}

                {activeTab === 'failures' ? (
                  <div className="tab-content">
                    {diagnosisEndpointRows.length > 0 ? (
                      <div className="quality-block">
                        <h3>Where It Failed and Why</h3>
                        <div className="failure-list">
                          {diagnosisEndpointRows.slice(0, 10).map((row) => (
                            <article key={`diag-${row.operationKey}`} className="failure-item">
                              <div className="failure-head">
                                <h3><code>{row.operationKey || `${row.method} ${row.endpoint}`}</code></h3>
                                <span className={`pill ${row.status === 'critical' ? 'pill-danger' : row.status === 'needs_attention' ? 'pill-warn' : 'pill-success'}`}>
                                  {formatReasonLabel(row.status)}
                                </span>
                              </div>
                              <p className="failure-meta">
                                Pass: <strong>{formatPercent(row.passRate)}</strong> | Hard fail: <strong>{row.hardFailed}</strong> | Suspect: <strong>{row.suspect}</strong> | Blocked: <strong>{row.blocked}</strong>
                              </p>
                              <p className="failure-meta">
                                Likely owner: <strong>{formatOwnerLabel(row.dominantOwner)}</strong> | Dominant cause: <strong>{formatReasonLabel(row.dominantCategory)}</strong>
                              </p>
                              {row.topReasons.map((reason) => (
                                <p className="failure-action" key={`${row.operationKey}-${reason.reason}`}>
                                  Cause: {formatReasonLabel(reason.reason)} ({reason.count})
                                </p>
                              ))}
                              {row.improvements.slice(0, 2).map((improvement) => (
                                <p className="failure-action" key={`${row.operationKey}-${improvement}`}>
                                  Improvement: {improvement}
                                </p>
                              ))}
                            </article>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {failedExamples.length === 0 ? (
                      <div className="empty-box">No failed examples recorded in this report.</div>
                    ) : (
                      <div className="failure-list">
                        {failedExamples.map((item, idx) => {
                          const method = String(getField(item, ['method'], '') || '').toUpperCase();
                          const endpoint = String(getField(item, ['endpoint', 'endpoint_template'], '') || '');
                          const expected = getField(item, ['expected_status', 'expectedStatus'], 'n/a');
                          const actual = getField(item, ['actual_status', 'actualStatus'], 'n/a');
                          const action = String(getField(item, ['recommended_action', 'recommendedAction'], '') || '').trim();
                          const title = String(getField(item, ['display_name', 'name'], '') || `Failure ${idx + 1}`);
                          const verdict = String(getField(item, ['verdict'], 'fail') || 'fail');
                          const error = String(getField(item, ['error'], '') || '');
                          return (
                            <article key={`${title}-${idx}`} className="failure-item">
                              <div className="failure-head">
                                <h3>{title}</h3>
                                <span className={`pill ${verdict === 'pass' ? 'pill-success' : verdict === 'suspect' ? 'pill-warn' : 'pill-danger'}`}>
                                  {formatReasonLabel(verdict)}
                                </span>
                              </div>
                              <p className="failure-route"><code>{method || 'METHOD'}</code> <code>{endpoint || '/path'}</code></p>
                              <p className="failure-meta">Expected: <strong>{String(expected)}</strong> | Actual: <strong>{String(actual)}</strong></p>
                              {action ? <p className="failure-action">Recommended action: {action}</p> : null}
                              {error ? <p className="failure-error">Error: {error}</p> : null}
                            </article>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ) : null}

                {activeTab === 'scripts' ? (
                  <div className="tab-content">
                    {generatedTestsLoading ? <p className="muted-text">Loading generated scripts...</p> : null}
                    {generatedTests.length === 0 ? (
                      <div className="empty-box">No generated scripts found for this run/domain.</div>
                    ) : (
                      <div className="scripts-layout">
                        <div className="scripts-list">
                          {generatedTests.map((item) => {
                            const kind = String(getField(item, ['kind'], '') || '');
                            const exists = Boolean(getField(item, ['exists'], false));
                            const safeToRead = Boolean(getField(item, ['safe_to_read', 'safeToRead'], false));
                            const sizeBytes = getField(item, ['size_bytes', 'sizeBytes'], null);
                            return (
                              <button
                                key={kind}
                                type="button"
                                className={`script-item ${selectedScriptKind === kind ? 'is-active' : ''}`}
                                onClick={() => {
                                  setSelectedScriptKind(kind);
                                  void loadGeneratedScript(reportDomain, kind);
                                }}
                              >
                                <div className="script-item-head">
                                  <span>{kind}</span>
                                  <span className={`pill ${exists && safeToRead ? 'pill-success' : 'pill-danger'}`}>
                                    {exists && safeToRead ? 'ready' : 'blocked'}
                                  </span>
                                </div>
                                <p>{formatBytes(sizeBytes)}</p>
                              </button>
                            );
                          })}
                        </div>
                        <pre className="report-box">
                          {scriptLoading ? 'Loading script...' : selectedScriptBody}
                        </pre>
                      </div>
                    )}
                  </div>
                ) : null}

                {activeTab === 'raw' ? (
                  <div className="tab-content">
                    <div className="toolbar">
                      <select value={rawFormat} onChange={(event) => setRawFormat(event.target.value)}>
                        <option value="json">JSON</option>
                        <option value="md">Markdown</option>
                      </select>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={!reportDomain || rawLoading}
                        onClick={() => void loadRawReport(reportDomain, rawFormat)}
                      >
                        {rawLoading ? 'Loading...' : 'Reload Raw'}
                      </button>
                    </div>
                    <pre className="report-box">{rawReport}</pre>
                  </div>
                ) : null}
              </>
            )}
          </section>
        </section>
      </main>

      <SpecUploadModal
        open={specUploadModalOpen}
        onClose={() => setSpecUploadModalOpen(false)}
        onSelectFile={onSpecFilePicked}
        uploading={specUploading}
        error={specUploadError}
        currentFile={uploadedSpec.name}
      />

      <SpecTextModal
        open={specTextModalOpen}
        draft={specTextDraft}
        onDraftChange={setSpecTextDraft}
        onClose={() => setSpecTextModalOpen(false)}
        onSave={saveSpecFromTextModal}
        saving={specUploading}
        error={specUploadError}
      />
    </div>
  );
}
