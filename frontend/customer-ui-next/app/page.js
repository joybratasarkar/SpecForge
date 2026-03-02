'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

const DOMAINS = ['ecommerce', 'healthcare', 'logistics', 'hr'];
const DOMAIN_LABELS = {
  ecommerce: 'E-commerce',
  healthcare: 'Healthcare',
  logistics: 'Logistics',
  hr: 'HR'
};
const STEP_MARKERS = [
  { name: 'Spec Prepared', marker: '[OK] OpenAPI spec written' },
  { name: 'Run Started', marker: '[RUN] QA specialist agent' },
  { name: 'RL Session Started', marker: 'Started observability session' },
  { name: 'RL Training Executed', marker: 'RL training executed' },
  { name: 'QA Run Complete', marker: 'QA specialist run complete' },
  { name: 'Reports Written', marker: 'JSON report:' }
];
const FLOW_STEPS = [
  {
    id: 'request_accepted',
    name: '1) Request Accepted',
    marker: '[RUN] QA specialist agent',
    input: 'domains, tenant, baseUrl, thresholds, script kind',
    output: 'job_id and queued execution'
  },
  {
    id: 'openapi_prepared',
    name: '2) OpenAPI Prepared',
    marker: '[OK] OpenAPI spec written',
    input: 'domain prompt + template',
    output: 'openapi_under_test.yaml'
  },
  {
    id: 'scenario_selection',
    name: '3) Scenario Selection',
    marker: 'selection algorithm',
    input: 'candidate scenarios + uncertainty scores',
    output: 'selected scenarios for this run'
  },
  {
    id: 'isolated_execution',
    name: '4) Isolated Execution',
    marker: 'Dynamic Mock Server initialized',
    input: 'selected scenarios + mock server',
    output: 'scenario_results[] with actual status/time'
  },
  {
    id: 'rl_training',
    name: '5) RL Training',
    marker: 'RL training executed',
    input: 'decision signals + rewards/penalties',
    output: 'updated policy and checkpoint'
  },
  {
    id: 'reports_emitted',
    name: '6) Reports Emitted',
    marker: 'qa_execution_report.json',
    input: 'summary + learning state + traces',
    output: 'JSON + Markdown report files'
  }
];
const CUSTOMER_APIS = [
  {
    method: 'POST',
    path: '/api/jobs',
    purpose: 'Start one multi-domain agent run',
    body: '{ domains[], tenantId, scriptKind, maxScenarios, passThreshold, verifyPersistence, ... }'
  },
  {
    method: 'GET',
    path: '/api/jobs',
    purpose: 'List jobs and status',
    body: '-'
  },
  {
    method: 'GET',
    path: '/api/jobs/{jobId}?tail=1200',
    purpose: 'Read current job snapshot and logs',
    body: '-'
  },
  {
    method: 'GET',
    path: '/api/jobs/{jobId}/events',
    purpose: 'Realtime SSE snapshots (interactive UI stream)',
    body: '-'
  },
  {
    method: 'GET',
    path: '/api/jobs/{jobId}/report/{domain}?format=json|md',
    purpose: 'Fetch domain report',
    body: '-'
  },
  {
    method: 'GET',
    path: '/api/jobs/{jobId}/generated-tests/{domain}',
    purpose: 'List generated test scripts for one domain',
    body: '-'
  },
  {
    method: 'GET',
    path: '/api/jobs/{jobId}/generated-tests/{domain}/{kind}',
    purpose: 'Fetch generated script content',
    body: '-'
  }
];
const API_BASE = (process.env.NEXT_PUBLIC_BACKEND_BASE_URL || '').replace(/\/$/, '');
const API_URL = (path) => `${API_BASE}${path}`;
const CONNECTION_MODE = API_BASE ? 'Direct FastAPI Backend' : 'Next.js API Proxy';
const SCRIPT_KIND_LABELS = {
  python_pytest: 'Python / Pytest',
  javascript_jest: 'JavaScript / Jest',
  curl_script: 'cURL Script',
  java_restassured: 'Java / RestAssured'
};
const SCRIPT_KINDS = ['python_pytest', 'javascript_jest', 'curl_script', 'java_restassured'];

function getField(obj, keys, fallback = null) {
  if (!obj) {
    return fallback;
  }
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key] !== undefined) {
      return obj[key];
    }
  }
  return fallback;
}

function toPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return 'n/a';
  }
  return `${(n * 100).toFixed(1)}%`;
}

function toNumberOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatBytes(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) {
    return 'n/a';
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function normalizeGeneratedTestItems(input) {
  if (!input) {
    return [];
  }
  if (Array.isArray(input)) {
    return input.map((item) => ({
      kind: String(getField(item, ['kind'], 'unknown')),
      path: String(getField(item, ['path'], '')),
      exists: Boolean(getField(item, ['exists'], false)),
      safe_to_read: Boolean(getField(item, ['safe_to_read'], false)),
      size_bytes: getField(item, ['size_bytes'], null)
    }));
  }
  if (typeof input === 'object') {
    return Object.entries(input).map(([kind, filePath]) => ({
      kind: String(kind),
      path: String(filePath || ''),
      exists: true,
      safe_to_read: true,
      size_bytes: null
    }));
  }
  return [];
}

function findLastLogMatch(lines, regex) {
  for (let idx = lines.length - 1; idx >= 0; idx -= 1) {
    const line = String(lines[idx] || '');
    const match = line.match(regex);
    if (match) {
      return match;
    }
  }
  return null;
}

function toJsonString(payload) {
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function parsePythonScriptInsights(text) {
  const lines = String(text || '').split(/\r?\n/).filter((line) => line.trim().length > 0);
  const imports = [];
  const importRegex = /^\s*import\s+([a-zA-Z_][a-zA-Z0-9_]*)/gm;
  for (const match of text.matchAll(importRegex)) {
    imports.push(match[1]);
  }

  const testNames = [];
  const testRegex = /^\s*def\s+(test_[a-zA-Z0-9_]+)\s*\(/gm;
  for (const match of text.matchAll(testRegex)) {
    testNames.push(match[1]);
  }

  const endpointPaths = [];
  const endpointRegex = /BASE_URL\s*\+\s*"([^"]+)"/g;
  for (const match of text.matchAll(endpointRegex)) {
    endpointPaths.push(match[1]);
  }

  const placeholders = endpointPaths.filter((path) => /\{[^}]+\}/.test(path));
  const placeholderNames = [];
  for (const path of placeholders) {
    const tokenMatch = path.match(/\{([^}]+)\}/g) || [];
    for (const token of tokenMatch) {
      placeholderNames.push(token);
    }
  }

  const methodCounts = { get: 0, post: 0, put: 0, patch: 0, delete: 0 };
  const methodRegex = /requests\.(get|post|put|patch|delete)\(/g;
  for (const match of text.matchAll(methodRegex)) {
    const key = String(match[1] || '').toLowerCase();
    if (Object.prototype.hasOwnProperty.call(methodCounts, key)) {
      methodCounts[key] += 1;
    }
  }
  const requestCount = Object.values(methodCounts).reduce((sum, value) => sum + value, 0);

  const statusCodes = [];
  const statusRegex = /assert\s+response\.status_code\s*==\s*(\d{3})/g;
  for (const match of text.matchAll(statusRegex)) {
    const code = Number(match[1]);
    if (Number.isFinite(code)) {
      statusCodes.push(code);
    }
  }
  const statusBuckets = { success_2xx: 0, client_4xx: 0, server_5xx: 0, other: 0 };
  for (const code of statusCodes) {
    if (code >= 200 && code < 300) {
      statusBuckets.success_2xx += 1;
    } else if (code >= 400 && code < 500) {
      statusBuckets.client_4xx += 1;
    } else if (code >= 500 && code < 600) {
      statusBuckets.server_5xx += 1;
    } else {
      statusBuckets.other += 1;
    }
  }

  let focus = 'Mixed coverage.';
  if (statusBuckets.client_4xx > 0 && statusBuckets.success_2xx === 0 && statusBuckets.server_5xx === 0) {
    focus = 'Negative testing focused (auth, validation, and error handling).';
  } else if (statusBuckets.success_2xx > 0 && statusBuckets.client_4xx === 0 && statusBuckets.server_5xx === 0) {
    focus = 'Happy-path focused.';
  } else if (statusBuckets.success_2xx > 0 && statusBuckets.client_4xx > 0) {
    focus = 'Mixed happy-path + negative testing.';
  }

  const warnings = [];
  if (placeholders.length > 0) {
    warnings.push(
      `Path template placeholders detected (${placeholders.length}): ${[...new Set(placeholderNames)].join(', ')}`
    );
  }
  if (imports.includes('pytest') && !/\bpytest\./.test(text) && !/@pytest\b/.test(text)) {
    warnings.push("`import pytest` appears unused in this script.");
  }
  if (imports.includes('json') && !/\bjson\./.test(text)) {
    warnings.push("`import json` appears unused in this script.");
  }
  if (statusBuckets.success_2xx === 0 && statusBuckets.client_4xx > 0) {
    warnings.push('No happy-path 2xx assertions found in current selected script.');
  }

  return {
    language: 'python_pytest',
    lineCount: lines.length,
    testCount: testNames.length,
    requestCount,
    endpointCount: endpointPaths.length,
    methodCounts,
    statusBuckets,
    focus,
    warnings,
    sampleEndpoints: endpointPaths.slice(0, 4)
  };
}

function parseGeneratedScriptInsights(kind, text) {
  const raw = String(text || '').trim();
  if (!raw || raw.startsWith('Select a generated test script')) {
    return null;
  }
  if (kind === 'python_pytest') {
    return parsePythonScriptInsights(raw);
  }

  const lines = raw.split(/\r?\n/).filter((line) => line.trim().length > 0);
  const genericWarnings = [];
  if (/\{[^}]+\}/.test(raw)) {
    genericWarnings.push('Path template placeholders detected (example: {id}).');
  }
  return {
    language: kind || 'unknown',
    lineCount: lines.length,
    testCount: 0,
    requestCount: 0,
    endpointCount: 0,
    methodCounts: {},
    statusBuckets: {},
    focus: 'Preview this script content directly below.',
    warnings: genericWarnings,
    sampleEndpoints: []
  };
}

export default function HomePage() {
  const [domains, setDomains] = useState(['ecommerce']);
  const [tenantId, setTenantId] = useState('customer_default');
  const [runScriptKind, setRunScriptKind] = useState('python_pytest');
  const [prompt, setPrompt] = useState('');
  const [maxScenarios, setMaxScenarios] = useState(16);
  const [passThreshold, setPassThreshold] = useState(0.7);
  const [baseUrl, setBaseUrl] = useState('http://localhost:8000');
  const [customerRoot, setCustomerRoot] = useState('~/.spec_test_pilot');
  const [customerMode, setCustomerMode] = useState(true);
  const [verifyPersistence, setVerifyPersistence] = useState(true);

  const [job, setJob] = useState(null);
  const [reportText, setReportText] = useState('Select a domain report to inspect.');
  const [selectedReportDomain, setSelectedReportDomain] = useState('');
  const [selectedReportFormat, setSelectedReportFormat] = useState('json');
  const [reportJson, setReportJson] = useState(null);
  const [scenarioFilter, setScenarioFilter] = useState('all');
  const [scenarioSearch, setScenarioSearch] = useState('');
  const [generatedTests, setGeneratedTests] = useState([]);
  const [generatedTestsDomain, setGeneratedTestsDomain] = useState('');
  const [generatedScriptContents, setGeneratedScriptContents] = useState({});
  const [generatedScriptsLoading, setGeneratedScriptsLoading] = useState(false);
  const [generatedScriptsLoadedDomain, setGeneratedScriptsLoadedDomain] = useState('');
  const [selectedScriptKind, setSelectedScriptKind] = useState('');
  const [scriptText, setScriptText] = useState('Select a generated test script to preview.');
  const [outputDomain, setOutputDomain] = useState('');
  const [flashMessage, setFlashMessage] = useState('');
  const [running, setRunning] = useState(false);

  const timerRef = useRef(null);
  const eventSourceRef = useRef(null);
  const autoLoadedJobRef = useRef('');
  const flashTimerRef = useRef(null);

  const logText = useMemo(() => (job?.logs || []).join('\n'), [job]);
  const results = job?.results || {};
  const currentDomain = getField(job, ['currentDomain', 'current_domain'], 'none');
  const jobScriptKind = String(
    getField(job, ['request'], {})?.scriptKind ||
      getField(job, ['request'], {})?.script_kind ||
      runScriptKind
  );
  const startedAt = getField(job, ['startedAt', 'started_at'], 'n/a');
  const completedAt = getField(job, ['completedAt', 'completed_at'], 'n/a');
  const jobId = getField(job, ['id'], '');
  const reportSummary = reportJson?.summary || null;
  const generatedScriptExecution = reportJson?.generated_script_execution || {};
  const trainingStats = reportJson?.agent_lightning?.training_stats || {};
  const learningFeedback = reportJson?.learning?.feedback || {};
  const selectionPolicy = reportJson?.selection_policy || {};
  const stateSnapshot = reportJson?.learning?.state_snapshot || {};
  const scenarioResults = Array.isArray(reportJson?.scenario_results) ? reportJson.scenario_results : [];
  const topDecisions = Array.isArray(selectionPolicy?.top_decisions) ? selectionPolicy.top_decisions : [];
  const weakestPatterns = Array.isArray(stateSnapshot?.weakest_patterns) ? stateSnapshot.weakest_patterns : [];
  const rewardBreakdown = learningFeedback?.reward_breakdown || {};
  const resultSummaries = Object.values(results).map((r) => r?.summary || {});
  const resultDomains = Object.keys(results);
  const selectedDomainLabel = selectedReportDomain ? DOMAIN_LABELS[selectedReportDomain] || selectedReportDomain : 'none';
  const passedScenarioCount = scenarioResults.filter((row) => !!row?.passed).length;
  const failedScenarioCount = Math.max(0, scenarioResults.length - passedScenarioCount);
  const successDomainCount = Object.values(results).filter((result) => {
    const code = Number(getField(result, ['exitCode', 'return_code'], 1));
    return code === 0;
  }).length;
  const overallPassRate = reportJson ? toPct(getField(reportSummary, ['pass_rate'], null)) : 'n/a';

  const filteredScenarios = useMemo(() => {
    const needle = scenarioSearch.trim().toLowerCase();
    return scenarioResults.filter((row) => {
      const passed = !!row?.passed;
      if (scenarioFilter === 'pass' && !passed) {
        return false;
      }
      if (scenarioFilter === 'fail' && passed) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const blob = [
        row?.name,
        row?.test_type,
        row?.method,
        row?.endpoint_template,
        row?.endpoint_resolved,
        String(row?.actual_status ?? ''),
        String(row?.expected_status ?? '')
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return blob.includes(needle);
    });
  }, [scenarioFilter, scenarioResults, scenarioSearch]);

  const selectedScriptContent = useMemo(() => {
    if (selectedScriptKind && Object.prototype.hasOwnProperty.call(generatedScriptContents, selectedScriptKind)) {
      return String(generatedScriptContents[selectedScriptKind] || '');
    }
    return String(scriptText || '');
  }, [generatedScriptContents, scriptText, selectedScriptKind]);

  const selectedScriptInsights = useMemo(() => {
    return parseGeneratedScriptInsights(selectedScriptKind, selectedScriptContent);
  }, [selectedScriptContent, selectedScriptKind]);

  const reportSelectionSelected = toNumberOrNull(getField(selectionPolicy, ['selected_count', 'selectedCount'], null));
  const reportSelectionCandidates = toNumberOrNull(getField(selectionPolicy, ['candidate_count', 'candidateCount'], null));
  const summarySelectionSelected = resultSummaries
    .map((s) => toNumberOrNull(getField(s, ['selection_selected_count', 'selectionSelectedCount'], null)))
    .find((v) => v !== null);
  const summarySelectionCandidates = resultSummaries
    .map((s) => toNumberOrNull(getField(s, ['selection_candidate_count', 'selectionCandidateCount'], null)))
    .find((v) => v !== null);
  const selectionSelected = reportSelectionSelected ?? summarySelectionSelected;
  const selectionCandidates = reportSelectionCandidates ?? summarySelectionCandidates;
  const completedDomains = Object.keys(results).length;
  const reportReadyDomains = Object.values(results).filter((r) => {
    const jsonPath = getField(r, ['report_json', 'reportJsonPath'], '');
    const mdPath = getField(r, ['report_md', 'reportMdPath'], '');
    return Boolean(jsonPath || mdPath);
  }).length;
  const rlStepFromReport = toNumberOrNull(getField(trainingStats, ['rl_training_steps', 'rlTrainingSteps'], null));
  const rlStepFromSummary = resultSummaries
    .map((s) => toNumberOrNull(getField(s, ['rl_training_steps', 'rlTrainingSteps'], null)))
    .reduce((acc, value) => (value !== null && (acc === null || value > acc) ? value : acc), null);
  const rlStepValue = rlStepFromReport ?? rlStepFromSummary;
  const selectedStateDomain = selectedReportDomain || outputDomain || resultDomains[0] || '';
  const selectedDomainResult = selectedStateDomain ? results[selectedStateDomain] || null : null;
  const selectedDomainSummary = selectedDomainResult?.summary || {};
  const outputDirValue = getField(selectedDomainResult, ['outputDir', 'output_dir'], '');
  const checkpointValue = getField(selectedDomainResult, ['checkpointPath', 'checkpoint'], '');
  const reportJsonPathValue = getField(selectedDomainResult, ['reportJsonPath', 'report_json'], '');
  const reportMdPathValue = getField(selectedDomainResult, ['reportMdPath', 'report_md'], '');
  const openapiPathFromLog = findLastLogMatch(job?.logs || [], /OpenAPI spec written:\s*(.+)$/i)?.[1]?.trim() || '';
  const commandFromLog = findLastLogMatch(job?.logs || [], /\$\s+bash\s+(.+)$/i)?.[1]?.trim() || '';
  const reportJsonPathFromLog = findLastLogMatch(job?.logs || [], /JSON report:\s*(.+)$/i)?.[1]?.trim() || '';
  const reportMdPathFromLog = findLastLogMatch(job?.logs || [], /MD report:\s*(.+)$/i)?.[1]?.trim() || '';

  const stateTrace = useMemo(() => {
    return [
      {
        id: 'api_request',
        title: '1) API Request Payload',
        ready: Boolean(job?.request),
        payload: {
          request: job?.request || null,
          job_meta: {
            id: jobId || null,
            status: job?.status || null,
            created_at: getField(job, ['createdAt', 'created_at'], null),
            started_at: getField(job, ['startedAt', 'started_at'], null),
            completed_at: getField(job, ['completedAt', 'completed_at'], null),
            current_domain: currentDomain
          }
        }
      },
      {
        id: 'domain_command',
        title: '2) Domain Command + Runtime Paths',
        ready: Boolean(commandFromLog || selectedDomainResult),
        payload: {
          selected_domain: selectedStateDomain || null,
          command: commandFromLog || null,
          script_kind_request: jobScriptKind || null,
          script_kind_result:
            getField(selectedDomainResult, ['scriptKind', 'script_kind'], null) ||
            getField(selectedDomainSummary, ['scriptKind', 'script_kind'], null),
          output_dir: outputDirValue || null,
          checkpoint: checkpointValue || null,
          return_code: getField(selectedDomainResult, ['exitCode', 'return_code'], null),
          domain_summary: selectedDomainSummary
        }
      },
      {
        id: 'openapi_prepared',
        title: '3) OpenAPI Prepared',
        ready: Boolean(openapiPathFromLog || reportJson?.metadata),
        payload: {
          spec_path_from_log: openapiPathFromLog || null,
          spec_path_from_report: reportJson?.metadata?.spec_path || null,
          spec_title: reportJson?.metadata?.spec_title || null,
          spec_version: reportJson?.metadata?.spec_version || null
        }
      },
      {
        id: 'scenario_selection',
        title: '4) Scenario Selection Output',
        ready: Boolean(reportJson?.selection_policy),
        payload: reportJson?.selection_policy || null
      },
      {
        id: 'generated_tests',
        title: '5) Generated Test Scripts (API Output)',
        ready: generatedTests.length > 0 || Boolean(reportJson?.generated_test_files),
        payload: {
          selected_domain: generatedTestsDomain || selectedStateDomain || null,
          scripts_loading: generatedScriptsLoading,
          scripts_loaded_domain: generatedScriptsLoadedDomain || null,
          generated_test_files_report: reportJson?.generated_test_files || {},
          generated_test_files_api: generatedTests,
          generated_script_contents: generatedScriptContents,
          generated_script_execution: generatedScriptExecution
        }
      },
      {
        id: 'scenario_execution',
        title: '6) Executed Scenario Results',
        ready: scenarioResults.length > 0,
        payload: {
          total: scenarioResults.length,
          passed: passedScenarioCount,
          failed: failedScenarioCount,
          scenarios: scenarioResults
        }
      },
      {
        id: 'gam_research',
        title: '7) GAM Deep Research State',
        ready: Boolean(reportJson?.gam),
        payload: reportJson?.gam || null
      },
      {
        id: 'rl_training',
        title: '8) RL Training State',
        ready: Boolean(reportJson?.agent_lightning || reportJson?.learning),
        payload: {
          learning: reportJson?.learning || null,
          agent_lightning: reportJson?.agent_lightning || null
        }
      },
      {
        id: 'final_reports',
        title: '9) Final Report Paths + Payload',
        ready: Boolean(reportJson || reportJsonPathValue || reportMdPathValue),
        payload: {
          report_files: reportJson?.report_files || null,
          report_json_from_domain_result: reportJsonPathValue || null,
          report_md_from_domain_result: reportMdPathValue || null,
          report_json_from_log: reportJsonPathFromLog || null,
          report_md_from_log: reportMdPathFromLog || null
        }
      }
    ];
  }, [
    checkpointValue,
    commandFromLog,
    currentDomain,
    failedScenarioCount,
    generatedScriptContents,
    generatedScriptsLoadedDomain,
    generatedScriptsLoading,
    generatedTests,
    generatedTestsDomain,
    job,
    jobId,
    openapiPathFromLog,
    outputDirValue,
    passedScenarioCount,
    reportJson,
    reportJsonPathFromLog,
    reportJsonPathValue,
    reportMdPathFromLog,
    reportMdPathValue,
    generatedScriptExecution,
    scenarioResults,
    selectedDomainResult,
    selectedDomainSummary,
    selectedStateDomain
  ]);

  function isFlowStepDone(stepId) {
    if (stepId === 'request_accepted') {
      return Boolean(jobId);
    }
    if (stepId === 'openapi_prepared') {
      return logText.includes('[OK] OpenAPI spec written') || completedDomains > 0;
    }
    if (stepId === 'scenario_selection') {
      return (
        (selectionSelected !== null && selectionCandidates !== null) ||
        logText.includes('selection_policy') ||
        logText.toLowerCase().includes('selected scenarios')
      );
    }
    if (stepId === 'isolated_execution') {
      return (
        logText.includes('Dynamic Mock Server initialized') ||
        completedDomains > 0 ||
        scenarioResults.length > 0
      );
    }
    if (stepId === 'rl_training') {
      return logText.includes('RL training executed') || (rlStepValue !== null && rlStepValue > 0);
    }
    if (stepId === 'reports_emitted') {
      return logText.includes('qa_execution_report.json') || reportReadyDomains > 0;
    }
    return false;
  }

  function flowStepActual(stepId) {
    if (stepId === 'scenario_selection') {
      if (selectionSelected !== null && selectionCandidates !== null) {
        return `actual: selected=${selectionSelected} / candidates=${selectionCandidates}`;
      }
      return 'actual: waiting for selection metrics';
    }
    if (stepId === 'isolated_execution') {
      return `actual: domains_completed=${completedDomains}`;
    }
    if (stepId === 'rl_training') {
      return `actual: rl_steps=${rlStepValue === null ? 'n/a' : rlStepValue}`;
    }
    if (stepId === 'reports_emitted') {
      return `actual: report_ready_domains=${reportReadyDomains}`;
    }
    return '';
  }

  function closeRealtimeConnection() {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }

  async function pollJob(jobId) {
    try {
      const reqUrl = API_URL(`/api/jobs/${jobId}?tail=1200`);
      const res = await fetch(reqUrl, { cache: 'no-store' });
      if (!res.ok) {
        return;
      }
      const payload = await res.json();
      setJob(payload);

      if (payload.status === 'running' || payload.status === 'queued') {
        timerRef.current = setTimeout(() => pollJob(jobId), 1500);
      } else {
        setRunning(false);
        closeRealtimeConnection();
      }
    } catch {
      timerRef.current = setTimeout(() => pollJob(jobId), 2000);
    }
  }

  function connectRealtime(jobId) {
    closeRealtimeConnection();

    const source = new EventSource(API_URL(`/api/jobs/${jobId}/events`));
    eventSourceRef.current = source;

    source.addEventListener('snapshot', (event) => {
      try {
        const payload = JSON.parse(event.data);
        setJob(payload);
        if (payload.status === 'completed' || payload.status === 'failed') {
          setRunning(false);
          closeRealtimeConnection();
        }
      } catch {
        // Ignore malformed snapshot payload.
      }
    });

    source.addEventListener('done', () => {
      setRunning(false);
      closeRealtimeConnection();
    });

    source.onerror = () => {
      source.close();
      eventSourceRef.current = null;
      // Fallback to polling if SSE stream disconnects during active run.
      if (jobId && running) {
        timerRef.current = setTimeout(() => pollJob(jobId), 1500);
      }
    };
  }

  async function onRun() {
    if (!domains.length) {
      alert('Select at least one domain.');
      return;
    }

    setRunning(true);
    setReportText('Select a domain report to inspect.');
    setReportJson(null);
    setSelectedReportDomain('');
    setSelectedReportFormat('json');
    setGeneratedTests([]);
    setGeneratedTestsDomain('');
    setGeneratedScriptContents({});
    setGeneratedScriptsLoadedDomain('');
    setGeneratedScriptsLoading(false);
    setSelectedScriptKind('');
    setScriptText('Select a generated test script to preview.');
    autoLoadedJobRef.current = '';

    const body = {
      domains,
      tenantId,
      scriptKind: runScriptKind,
      prompt: prompt.trim() || null,
      maxScenarios,
      passThreshold,
      baseUrl,
      customerMode,
      verifyPersistence,
      customerRoot
    };

    const reqUrl = API_URL('/api/jobs');
    const res = await fetch(reqUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    });

    const payload = await res.json();
    if (!res.ok) {
      setRunning(false);
      alert(payload.error || 'Failed to start run');
      return;
    }

    const startedJobId = getField(payload, ['jobId', 'job_id'], '');
    if (!startedJobId) {
      setRunning(false);
      alert('Backend response missing job id');
      return;
    }
    connectRealtime(startedJobId);
  }

  async function loadAllGeneratedScripts(domain, items) {
    if (!job?.id || !domain) {
      return;
    }
    setGeneratedScriptsLoading(true);
    const next = {};
    for (const item of items) {
      const kind = String(item?.kind || '').trim();
      if (!kind) {
        continue;
      }
      if (item.exists === false || item.safe_to_read === false) {
        next[kind] = '[unavailable] file is missing or blocked by safety check';
        continue;
      }
      const reqUrl = API_URL(`/api/jobs/${job.id}/generated-tests/${domain}/${kind}`);
      try {
        const res = await fetch(reqUrl, { cache: 'no-store' });
        if (!res.ok) {
          const errText = await res.text();
          next[kind] = `[error] failed to fetch script: ${errText}`;
          continue;
        }
        next[kind] = await res.text();
      } catch (error) {
        next[kind] = `[error] failed to fetch script: ${String(error)}`;
      }
    }
    setGeneratedScriptContents(next);
    setGeneratedScriptsLoadedDomain(domain);
    setGeneratedScriptsLoading(false);
  }

  async function openReport(domain, format) {
    if (!job?.id) {
      return;
    }
    setSelectedReportDomain(domain);
    setSelectedReportFormat(format);

    const reqUrl = API_URL(`/api/jobs/${job.id}/report/${domain}?format=${format}`);
    const res = await fetch(reqUrl, {
      cache: 'no-store'
    });
    if (!res.ok) {
      setReportJson(null);
      setReportText(`Failed to open ${format.toUpperCase()} report for ${domain}`);
      return;
    }

    if (format === 'json') {
      const payload = await res.json();
      setReportJson(payload);
      setReportText(JSON.stringify(payload, null, 2));
      const fromReport = normalizeGeneratedTestItems(payload?.generated_test_files);
      setGeneratedTests(fromReport);
      setGeneratedTestsDomain(domain);
      setGeneratedScriptContents({});
      setGeneratedScriptsLoadedDomain('');
      setGeneratedScriptsLoading(false);
      setSelectedScriptKind('');
      setScriptText('Select a generated test script to preview.');
      await loadGeneratedTests(domain, fromReport);
      return;
    }
    setReportText(await res.text());
  }

  async function loadGeneratedTests(domain, fallbackItems = []) {
    if (!job?.id) {
      return;
    }
    const reqUrl = API_URL(`/api/jobs/${job.id}/generated-tests/${domain}`);
    try {
      const res = await fetch(reqUrl, { cache: 'no-store' });
      if (!res.ok) {
        if (fallbackItems.length > 0) {
          setGeneratedTests(fallbackItems);
          setGeneratedTestsDomain(domain);
          await loadAllGeneratedScripts(domain, fallbackItems);
        }
        return;
      }
      const payload = await res.json();
      const items = normalizeGeneratedTestItems(getField(payload, ['generated_tests', 'generatedTests'], []));
      setGeneratedTests(items);
      setGeneratedTestsDomain(domain);
      await loadAllGeneratedScripts(domain, items);
    } catch {
      if (fallbackItems.length > 0) {
        setGeneratedTests(fallbackItems);
        setGeneratedTestsDomain(domain);
        await loadAllGeneratedScripts(domain, fallbackItems);
      }
    }
  }

  async function openGeneratedScript(domain, kind) {
    if (!job?.id) {
      return;
    }
    setSelectedScriptKind(kind);
    if (generatedScriptsLoadedDomain === domain && Object.prototype.hasOwnProperty.call(generatedScriptContents, kind)) {
      setScriptText(generatedScriptContents[kind] || `Script ${kind} is empty.`);
      return;
    }
    const reqUrl = API_URL(`/api/jobs/${job.id}/generated-tests/${domain}/${kind}`);
    try {
      const res = await fetch(reqUrl, { cache: 'no-store' });
      if (!res.ok) {
        const errText = await res.text();
        setScriptText(`Failed to load script ${kind}: ${errText}`);
        return;
      }
      const raw = await res.text();
      setGeneratedScriptContents((prev) => ({ ...prev, [kind]: raw }));
      setGeneratedScriptsLoadedDomain(domain);
      setScriptText(raw || `Script ${kind} is empty.`);
    } catch (error) {
      setScriptText(`Failed to load script ${kind}: ${String(error)}`);
    }
  }

  function setFlash(text) {
    setFlashMessage(text);
    if (flashTimerRef.current) {
      window.clearTimeout(flashTimerRef.current);
    }
    flashTimerRef.current = window.setTimeout(() => {
      setFlashMessage('');
    }, 1800);
  }

  async function copyText(label, value) {
    const content = String(value || '').trim();
    if (!content) {
      setFlash(`No ${label} content to copy`);
      return;
    }
    try {
      await navigator.clipboard.writeText(content);
      setFlash(`${label} copied`);
    } catch {
      setFlash(`Failed to copy ${label}`);
    }
  }

  async function openSelectedDomainOutput(format = 'json') {
    if (!outputDomain) {
      setFlash('Select a domain first');
      return;
    }
    await openReport(outputDomain, format);
  }

  function toggleDomain(domain) {
    setDomains((prev) => {
      if (prev.includes(domain)) {
        return prev.filter((d) => d !== domain);
      }
      return [...prev, domain];
    });
  }

  useEffect(() => {
    if (!jobId || selectedReportDomain || resultDomains.length === 0) {
      return;
    }
    if (autoLoadedJobRef.current === jobId) {
      return;
    }
    autoLoadedJobRef.current = jobId;
    const firstDomain = resultDomains[0];
    void openReport(firstDomain, 'json');
  }, [jobId, selectedReportDomain, resultDomains.length]);

  useEffect(() => {
    if (resultDomains.length === 0) {
      if (outputDomain) {
        setOutputDomain('');
      }
      return;
    }
    if (!outputDomain || !resultDomains.includes(outputDomain)) {
      setOutputDomain(resultDomains[0]);
    }
  }, [resultDomains, outputDomain]);

  useEffect(() => {
    return () => {
      closeRealtimeConnection();
      if (flashTimerRef.current) {
        window.clearTimeout(flashTimerRef.current);
      }
    };
  }, []);

  return (
    <main className="page">
      <header className="header">
        <div className="header-row">
          <div>
            <h1>SpecTestPilot QA Workspace</h1>
            <p className="header-subtitle">Run QA agent, review scripts, inspect tested cases, and deliver reports.</p>
          </div>
          <div className="header-badges">
            <span className="header-badge">status={job?.status || 'idle'}</span>
            <span className="header-badge">domains={resultDomains.length}</span>
            <span className="header-badge">success={successDomainCount}</span>
            <span className="header-badge">pass_rate={overallPassRate}</span>
          </div>
        </div>
        {flashMessage && <div className="toast">{flashMessage}</div>}
      </header>

      <div className="layout">
        <section className="card">
          <h2>Run Configuration</h2>

          <div className="field">
            <label>Domains</label>
            <div className="domains">
              {DOMAINS.map((domain) => (
                <label className="domain" key={domain}>
                  <input
                    type="checkbox"
                    checked={domains.includes(domain)}
                    onChange={() => toggleDomain(domain)}
                  />{' '}
                  {domain}
                </label>
              ))}
            </div>
          </div>

          <div className="field">
            <label>Tenant ID</label>
            <input value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
          </div>

          <div className="field">
            <label>Script Language</label>
            <select value={runScriptKind} onChange={(e) => setRunScriptKind(e.target.value)}>
              {SCRIPT_KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {SCRIPT_KIND_LABELS[kind] || kind}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Max Scenarios</label>
            <input
              type="number"
              min={1}
              max={500}
              value={maxScenarios}
              onChange={(e) => setMaxScenarios(Number(e.target.value || 16))}
            />
          </div>

          <div className="field">
            <label>Pass Threshold (0..1)</label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.01}
              value={passThreshold}
              onChange={(e) => setPassThreshold(Number(e.target.value || 0.7))}
            />
          </div>

          <div className="field">
            <label>Base URL</label>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>

          <div className="field">
            <label>Customer Root</label>
            <input value={customerRoot} onChange={(e) => setCustomerRoot(e.target.value)} />
          </div>

          <div className="field">
            <label>Prompt (optional)</label>
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </div>

          <div className="checks">
            <label>
              <input
                type="checkbox"
                checked={customerMode}
                onChange={(e) => setCustomerMode(e.target.checked)}
              />{' '}
              customer mode (persistent workspace/checkpoint)
            </label>
            <label>
              <input
                type="checkbox"
                checked={verifyPersistence}
                onChange={(e) => setVerifyPersistence(e.target.checked)}
              />{' '}
              verify persistence (auto second pass)
            </label>
          </div>

          <button className="primary" disabled={running} onClick={onRun}>
            {running ? 'Running...' : 'Run QA Agent'}
          </button>
        </section>

        <section className="right">
          <div className="card">
            <h2>Runtime Status</h2>
            <div className="status">
              <span className={`dot ${job?.status || ''}`} />
              <strong>{job?.status || 'idle'}</strong>
            </div>
            <div className="meta">
              {job
                ? `job=${jobId} | current_domain=${currentDomain} | script_kind=${jobScriptKind} | started=${startedAt} | completed=${completedAt}`
                : 'No run started yet.'}
            </div>
            <div className="steps">
              {STEP_MARKERS.map((step) => {
                const done = logText.includes(step.marker);
                return (
                  <div key={step.name} className={`step ${done ? 'done' : ''}`}>
                    {done ? '✓' : '•'} {step.name}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card">
            <details className="advanced">
              <summary>How It Works (API + Agent Flow)</summary>
              <div className="small">
                mode={CONNECTION_MODE}
                <br />
                backend={API_BASE || 'same-origin Next.js API routes'}
              </div>
              <div className="api-list">
                {CUSTOMER_APIS.map((item) => (
                  <div key={`${item.method}-${item.path}`} className="api-item">
                    <div className="api-head">
                      <span className={`method ${item.method.toLowerCase()}`}>{item.method}</span>
                      <code>{item.path}</code>
                    </div>
                    <div className="small">{item.purpose}</div>
                    <div className="small">payload: {item.body}</div>
                  </div>
                ))}
              </div>
              <div className="flow-list">
                {FLOW_STEPS.map((step) => {
                  const done = isFlowStepDone(step.id);
                  const actual = flowStepActual(step.id);
                  return (
                    <div key={step.name} className={`flow-item ${done ? 'done' : ''}`}>
                      <div className="flow-name">{step.name}</div>
                      <div className="small">input: {step.input}</div>
                      <div className="small">output: {step.output}</div>
                      {actual && <div className="small">{actual}</div>}
                    </div>
                  );
                })}
              </div>
            </details>
          </div>

          <div className="card">
            <h2>Domain Results</h2>
            <div className="results">
              {Object.keys(results).length === 0 && <div className="small">No domain results yet.</div>}
              {Object.entries(results).map(([domain, result]) => {
                const code = Number(getField(result, ['exitCode', 'return_code'], 1));
                const ok = code === 0;
                const s = result.summary || {};
                const generatedCount = normalizeGeneratedTestItems(
                  getField(result, ['generated_tests', 'generatedTests'], [])
                ).length;
                const passRate = getField(s, ['passRate', 'pass_rate'], null);
                const totalScenarios = getField(s, ['totalScenarios', 'total_scenarios'], 'n/a');
                const passedScenarios = getField(s, ['passedScenarios', 'passed_scenarios'], 'n/a');
                const failedScenarios = getField(s, ['failedScenarios', 'failed_scenarios'], 'n/a');
                const rlSteps = getField(s, ['rlTrainingSteps', 'rl_training_steps'], 'n/a');
                const rlBuffer = getField(s, ['rlBufferSize', 'rl_buffer_size'], 'n/a');
                const scriptKindValue =
                  getField(result, ['scriptKind', 'script_kind'], null) ||
                  getField(s, ['scriptKind', 'script_kind'], null) ||
                  runScriptKind;
                return (
                  <div className="result" key={domain}>
                    <h3>
                      {DOMAIN_LABELS[domain] || domain}
                      <span className={`pill ${ok ? 'ok' : 'bad'}`}>{ok ? 'ok' : 'failed'}</span>
                    </h3>
                    <div className="small">
                      pass_rate={toPct(passRate)}
                      <br />
                      total={String(totalScenarios)} passed={String(passedScenarios)} failed={String(failedScenarios)}
                      <br />
                      rl_steps={String(rlSteps)} rl_buffer={String(rlBuffer)}
                      <br />
                      script_kind={String(scriptKindValue)}
                      <br />
                      return_code={String(code)}
                      <br />
                      generated_scripts={String(generatedCount)}
                    </div>
                    <button onClick={() => openReport(domain, 'json')}>Open Customer Output</button>
                    <button onClick={() => openReport(domain, 'md')}>Open Markdown Report</button>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card">
            <details className="advanced" open>
              <summary>Customer Output (Click to Open/Close)</summary>
              <div className="small">
                selected_domain={selectedDomainLabel}
                <br />
                output_flow=1_scripts {'->'} 2_cases_tested {'->'} 3_final_report
              </div>
              <div className="output-toolbar">
                <select
                  value={outputDomain}
                  onChange={(e) => setOutputDomain(e.target.value)}
                  disabled={resultDomains.length === 0}
                >
                  {resultDomains.length === 0 && <option value="">No domains yet</option>}
                  {resultDomains.map((domain) => (
                    <option key={domain} value={domain}>
                      {DOMAIN_LABELS[domain] || domain}
                    </option>
                  ))}
                </select>
                <button disabled={!outputDomain} onClick={() => openSelectedDomainOutput('json')}>
                  Load Output
                </button>
                <button disabled={!outputDomain} onClick={() => openSelectedDomainOutput('md')}>
                  Load Markdown
                </button>
                <button onClick={() => copyText('report', reportText)}>Copy Report Text</button>
              </div>
              {!selectedReportDomain && resultDomains.length > 0 && (
                <button onClick={() => openReport(resultDomains[0], 'json')}>Load First Domain Output</button>
              )}
            </details>
          </div>

          <div className="card">
            <details className="advanced" open>
              <summary>State-by-State API Output (Glass Box) (Click to Open/Close)</summary>
              <div className="small">
                selected_domain={selectedStateDomain || 'none'} | states={stateTrace.length} | scripts_loading=
                {String(generatedScriptsLoading)}
              </div>
              <div className="state-trace-list">
                {stateTrace.map((state) => (
                  <details key={state.id} className={`state-trace-item ${state.ready ? 'done' : ''}`} open={state.ready}>
                    <summary>
                      <span className="state-trace-title">{state.ready ? '✓' : '•'} {state.title}</span>
                      <span className={`pill ${state.ready ? 'ok' : 'bad'}`}>{state.ready ? 'ready' : 'waiting'}</span>
                    </summary>
                    <pre>{toJsonString(state.payload)}</pre>
                  </details>
                ))}
              </div>
            </details>
          </div>

          <div className="card">
            <h2>1) Test Scripts Generated By Agent</h2>
            <div className="script-summary-grid">
              <div className="script-summary-item">
                <span>Selected Domain</span>
                <strong>{generatedTestsDomain || 'none'}</strong>
              </div>
              <div className="script-summary-item">
                <span>Scripts Returned</span>
                <strong>{String(generatedTests.length)}</strong>
              </div>
              <div className="script-summary-item">
                <span>Loading</span>
                <strong>{generatedScriptsLoading ? 'yes' : 'no'}</strong>
              </div>
              <div className="script-summary-item">
                <span>Execution Status</span>
                <strong>{String(getField(generatedScriptExecution, ['status'], 'n/a'))}</strong>
              </div>
              <div className="script-summary-item">
                <span>Executed Tests</span>
                <strong>{String(getField(generatedScriptExecution, ['total_tests'], 'n/a'))}</strong>
              </div>
              <div className="script-summary-item">
                <span>Passed / Failed</span>
                <strong>
                  {String(getField(generatedScriptExecution, ['passed_tests'], 'n/a'))} /{' '}
                  {String(getField(generatedScriptExecution, ['failed_tests'], 'n/a'))}
                </strong>
              </div>
            </div>
            {generatedTests.length === 0 && (
              <div className="small">Load customer output for a domain to view generated scripts.</div>
            )}
            {generatedTests.length > 0 && (
              <div className="inline-actions">
                <button
                  onClick={() => loadGeneratedTests(generatedTestsDomain || selectedStateDomain, generatedTests)}
                  disabled={generatedScriptsLoading || !(generatedTestsDomain || selectedStateDomain)}
                >
                  Reload Script Bundle From API
                </button>
              </div>
            )}
            {generatedTests.length > 0 && (
              <div className="script-table-wrap">
                <table className="script-table">
                  <thead>
                    <tr>
                      <th>Language</th>
                      <th>Kind</th>
                      <th>Path</th>
                      <th>Status</th>
                      <th>Readable</th>
                      <th>Size</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {generatedTests.map((item) => (
                      <tr key={`${generatedTestsDomain}-${item.kind}`}>
                        <td>{SCRIPT_KIND_LABELS[item.kind] || item.kind}</td>
                        <td><code>{item.kind}</code></td>
                        <td className="script-path-cell"><code>{item.path || 'n/a'}</code></td>
                        <td>{item.exists ? 'ready' : 'missing'}</td>
                        <td>{item.safe_to_read ? 'yes' : 'no'}</td>
                        <td>{formatBytes(item.size_bytes)}</td>
                        <td>
                          <button
                            disabled={!item.exists || !item.safe_to_read || !generatedTestsDomain}
                            onClick={() => openGeneratedScript(generatedTestsDomain, item.kind)}
                          >
                            Preview
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {selectedScriptInsights && (
              <div className="script-insight-panel">
                <div className="script-insight-head">
                  <h3>Script Explanation</h3>
                  <span className="small">language={SCRIPT_KIND_LABELS[selectedScriptInsights.language] || selectedScriptInsights.language}</span>
                </div>
                <div className="script-summary-grid">
                  <div className="script-summary-item">
                    <span>Non-empty Lines</span>
                    <strong>{String(selectedScriptInsights.lineCount)}</strong>
                  </div>
                  <div className="script-summary-item">
                    <span>Test Functions</span>
                    <strong>{String(selectedScriptInsights.testCount)}</strong>
                  </div>
                  <div className="script-summary-item">
                    <span>HTTP Calls</span>
                    <strong>{String(selectedScriptInsights.requestCount)}</strong>
                  </div>
                  <div className="script-summary-item">
                    <span>Endpoint Mentions</span>
                    <strong>{String(selectedScriptInsights.endpointCount)}</strong>
                  </div>
                  <div className="script-summary-item">
                    <span>2xx / 4xx / 5xx</span>
                    <strong>
                      {String(selectedScriptInsights.statusBuckets.success_2xx || 0)} /{' '}
                      {String(selectedScriptInsights.statusBuckets.client_4xx || 0)} /{' '}
                      {String(selectedScriptInsights.statusBuckets.server_5xx || 0)}
                    </strong>
                  </div>
                  <div className="script-summary-item">
                    <span>Primary Focus</span>
                    <strong>{selectedScriptInsights.focus}</strong>
                  </div>
                </div>
                {Object.keys(selectedScriptInsights.methodCounts || {}).length > 0 && (
                  <div className="small">
                    methods: GET={String(selectedScriptInsights.methodCounts.get || 0)} POST=
                    {String(selectedScriptInsights.methodCounts.post || 0)} PUT=
                    {String(selectedScriptInsights.methodCounts.put || 0)} PATCH=
                    {String(selectedScriptInsights.methodCounts.patch || 0)} DELETE=
                    {String(selectedScriptInsights.methodCounts.delete || 0)}
                  </div>
                )}
                {selectedScriptInsights.sampleEndpoints.length > 0 && (
                  <div className="small script-endpoints">
                    endpoint samples: {selectedScriptInsights.sampleEndpoints.join(' | ')}
                  </div>
                )}
                {selectedScriptInsights.warnings.length > 0 && (
                  <div className="script-warning-box">
                    {selectedScriptInsights.warnings.map((warning) => (
                      <div key={warning} className="small">
                        ! {warning}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="script-preview-head">
              <div className="small">Selected Script: {selectedScriptKind || 'none'}</div>
              <div className="inline-actions">
                <button onClick={() => copyText('script', scriptText)}>Copy Script</button>
              </div>
            </div>
            <pre className="script-preview">{scriptText}</pre>
          </div>

          <div className="card">
            <h2>2) Cases Tested By Agent</h2>
            <div className="small">
              selected_domain={selectedDomainLabel} | total={scenarioResults.length} | passed={passedScenarioCount} |
              failed={failedScenarioCount}
            </div>
            {!reportJson && (
              <div className="small">Open customer output for a domain to view tested cases.</div>
            )}
            {reportJson && (
              <div className="scenario-panel">
                <div className="scenario-head">
                  <h3>Scenario Results</h3>
                  <div className="scenario-controls">
                    <select value={scenarioFilter} onChange={(e) => setScenarioFilter(e.target.value)}>
                      <option value="all">all</option>
                      <option value="pass">passed</option>
                      <option value="fail">failed</option>
                    </select>
                    <input
                      placeholder="Search scenario name, endpoint, method..."
                      value={scenarioSearch}
                      onChange={(e) => setScenarioSearch(e.target.value)}
                    />
                  </div>
                </div>
                <div className="inline-actions">
                  <button onClick={() => setScenarioFilter('all')}>Show All</button>
                  <button onClick={() => setScenarioFilter('pass')}>Show Passed</button>
                  <button onClick={() => setScenarioFilter('fail')}>Show Failed</button>
                </div>
                <div className="small">showing {filteredScenarios.length} / {scenarioResults.length}</div>
                <div className="scenario-table-wrap">
                  <table className="scenario-table">
                    <thead>
                      <tr>
                        <th>status</th>
                        <th>name</th>
                        <th>type</th>
                        <th>endpoint</th>
                        <th>expected</th>
                        <th>actual</th>
                        <th>ms</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredScenarios.map((row) => (
                        <tr key={String(row.name)}>
                          <td>{row.passed ? 'pass' : 'fail'}</td>
                          <td>{row.name}</td>
                          <td>{row.test_type}</td>
                          <td>{`${row.method || ''} ${row.endpoint_template || ''}`.trim()}</td>
                          <td>{String(row.expected_status ?? 'n/a')}</td>
                          <td>{String(row.actual_status ?? 'n/a')}</td>
                          <td>{String(row.duration_ms ?? 'n/a')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <div className="card">
            <h2>3) Final QA Report</h2>
            <div className="small">
              selected_domain={selectedDomainLabel} | format={selectedReportFormat}
            </div>
            {selectedReportDomain && (
              <div className="inline-actions">
                <button onClick={() => openReport(selectedReportDomain, 'json')}>JSON View</button>
                <button onClick={() => openReport(selectedReportDomain, 'md')}>Markdown View</button>
                <button onClick={() => copyText('report', reportText)}>Copy Current Report</button>
              </div>
            )}
            {reportJson && (
              <div className="report-grid">
                <div className="report-metric">
                  <span>Total</span>
                  <strong>{String(getField(reportSummary, ['total_scenarios'], 'n/a'))}</strong>
                </div>
                <div className="report-metric">
                  <span>Pass Rate</span>
                  <strong>{toPct(getField(reportSummary, ['pass_rate'], null))}</strong>
                </div>
                <div className="report-metric">
                  <span>Quality Gate</span>
                  <strong>{String(getField(reportSummary, ['meets_quality_gate'], 'n/a'))}</strong>
                </div>
                <div className="report-metric">
                  <span>RL Steps</span>
                  <strong>{String(getField(trainingStats, ['rl_training_steps'], 'n/a'))}</strong>
                </div>
                <div className="report-metric">
                  <span>RL Buffer</span>
                  <strong>{String(getField(trainingStats, ['rl_buffer_size'], 'n/a'))}</strong>
                </div>
                <div className="report-metric">
                  <span>Run Reward</span>
                  <strong>{String(getField(learningFeedback, ['run_reward'], 'n/a'))}</strong>
                </div>
              </div>
            )}
            <pre>{reportText}</pre>
          </div>

          <div className="card">
            <h2>Live Process Log</h2>
            <pre>{logText || 'No logs yet.'}</pre>
          </div>

          <div className="card">
            <details className="advanced">
              <summary>Advanced Agent R&D (optional)</summary>
              {!reportJson && (
                <div className="small">Load a JSON report to inspect decision policy and learning internals.</div>
              )}
              {reportJson && (
                <>
                <div className="report-grid">
                  <div className="report-metric">
                    <span>Policy</span>
                    <strong>{String(getField(selectionPolicy, ['algorithm'], 'n/a'))}</strong>
                  </div>
                  <div className="report-metric">
                    <span>Candidates</span>
                    <strong>{String(getField(selectionPolicy, ['candidate_count'], 'n/a'))}</strong>
                  </div>
                  <div className="report-metric">
                    <span>Selected</span>
                    <strong>{String(getField(selectionPolicy, ['selected_count'], 'n/a'))}</strong>
                  </div>
                  <div className="report-metric">
                    <span>Uncertain Selected</span>
                    <strong>{String(getField(selectionPolicy, ['uncertain_selected_count'], 'n/a'))}</strong>
                  </div>
                  <div className="report-metric">
                    <span>Rewarded Decisions</span>
                    <strong>{String(getField(learningFeedback, ['rewarded_decisions'], 'n/a'))}</strong>
                  </div>
                  <div className="report-metric">
                    <span>Penalized Decisions</span>
                    <strong>{String(getField(learningFeedback, ['penalized_decisions'], 'n/a'))}</strong>
                  </div>
                  <div className="report-metric">
                    <span>Run Count</span>
                    <strong>{String(getField(stateSnapshot, ['run_count'], 'n/a'))}</strong>
                  </div>
                  <div className="report-metric">
                    <span>Tracked Patterns</span>
                    <strong>{String(getField(stateSnapshot, ['scenario_patterns_tracked'], 'n/a'))}</strong>
                  </div>
                </div>

                <div className="reward-grid">
                  <div className="reward-box">
                    <span>Pass Rate Component</span>
                    <strong>{String(getField(rewardBreakdown, ['pass_rate_component'], 'n/a'))}</strong>
                  </div>
                  <div className="reward-box">
                    <span>Coverage Component</span>
                    <strong>{String(getField(rewardBreakdown, ['coverage_component'], 'n/a'))}</strong>
                  </div>
                  <div className="reward-box">
                    <span>Failure Component</span>
                    <strong>{String(getField(rewardBreakdown, ['failure_component'], 'n/a'))}</strong>
                  </div>
                  <div className="reward-box">
                    <span>Latency Penalty</span>
                    <strong>{String(getField(rewardBreakdown, ['latency_penalty_component'], 'n/a'))}</strong>
                  </div>
                </div>

                <div className="scenario-panel">
                  <div className="scenario-head">
                    <h3>Top Selection Decisions</h3>
                  </div>
                  <div className="small">showing {Math.min(topDecisions.length, 15)} / {topDecisions.length}</div>
                  <div className="scenario-table-wrap">
                    <table className="scenario-table">
                      <thead>
                        <tr>
                          <th>name</th>
                          <th>type</th>
                          <th>reason</th>
                          <th>score</th>
                          <th>uncertainty</th>
                          <th>expected_reward</th>
                        </tr>
                      </thead>
                      <tbody>
                        {topDecisions.slice(0, 15).map((row) => (
                          <tr key={String(row.name)}>
                            <td>{row.name}</td>
                            <td>{row.test_type}</td>
                            <td>{row.selection_reason}</td>
                            <td>{String(row.score ?? 'n/a')}</td>
                            <td>{String(row.uncertainty ?? 'n/a')}</td>
                            <td>{String(row.expected_reward ?? 'n/a')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="scenario-panel">
                  <div className="scenario-head">
                    <h3>Weakest Patterns (Needs Improvement)</h3>
                  </div>
                  <div className="small">showing {Math.min(weakestPatterns.length, 12)} / {weakestPatterns.length}</div>
                  <div className="scenario-table-wrap">
                    <table className="scenario-table">
                      <thead>
                        <tr>
                          <th>fingerprint</th>
                          <th>failure_rate</th>
                          <th>attempts</th>
                          <th>avg_reward</th>
                        </tr>
                      </thead>
                      <tbody>
                        {weakestPatterns.slice(0, 12).map((row) => (
                          <tr key={String(row.fingerprint)}>
                            <td>{row.fingerprint}</td>
                            <td>{String(row.failure_rate ?? 'n/a')}</td>
                            <td>{String(row.attempts ?? 'n/a')}</td>
                            <td>{String(row.avg_reward ?? 'n/a')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                </>
              )}
            </details>
          </div>
        </section>
      </div>
    </main>
  );
}
