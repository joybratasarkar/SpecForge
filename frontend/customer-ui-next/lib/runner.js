import { spawn } from 'node:child_process';
import { promises as fs } from 'node:fs';
import path from 'node:path';

import { appendJobLog, getJob, setDomainResult, updateJob } from '@/lib/store';

const RUN_ROOT = '/tmp/qa_ui_next_runs';
const CHECKPOINT_ROOT = '/tmp/qa_ui_next_checkpoints';
const PRESET_DOMAINS = new Set(['ecommerce', 'healthcare', 'logistics', 'hr']);

function safeToken(value, fallback = 'token') {
  const token = String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_');
  return token || fallback;
}

function buildScriptPath() {
  return path.resolve(process.cwd(), '..', '..', 'backend', 'run_qa_domain.sh');
}

function buildRepoRoot() {
  return path.resolve(process.cwd(), '..', '..', 'backend');
}

async function ensureDirs() {
  await fs.mkdir(RUN_ROOT, { recursive: true });
  await fs.mkdir(CHECKPOINT_ROOT, { recursive: true });
}

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function streamProcessOutput(proc, onLine) {
  let buffer = '';

  const flush = (chunk) => {
    buffer += chunk;
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() || '';
    for (const line of lines) {
      onLine(line);
    }
  };

  proc.stdout?.setEncoding('utf-8');
  proc.stderr?.setEncoding('utf-8');
  proc.stdout?.on('data', flush);
  proc.stderr?.on('data', flush);

  return () => {
    if (buffer.trim()) {
      onLine(buffer);
    }
  };
}

async function readSummary(reportJsonPath) {
  try {
    const raw = await fs.readFile(reportJsonPath, 'utf-8');
    const payload = JSON.parse(raw);
    const summary = payload?.summary || {};
    const trainingStats = payload?.agent_lightning?.training_stats || {};
    const generatedRaw = payload?.generated_test_files || {};
    const generatedTests = {};
    if (generatedRaw && typeof generatedRaw === 'object') {
      for (const [kind, filePath] of Object.entries(generatedRaw)) {
        if (typeof filePath === 'string' && filePath.trim()) {
          generatedTests[String(kind)] = filePath;
        }
      }
    }

    return {
      summary: {
        totalScenarios: summary.total_scenarios ?? null,
        passedScenarios: summary.passed_scenarios ?? null,
        failedScenarios: summary.failed_scenarios ?? null,
        passRate: summary.pass_rate ?? null,
        meetsQualityGate: summary.meets_quality_gate ?? null,
        scriptKind: payload?.metadata?.script_kind ?? null,
        rlTrainingSteps: trainingStats.rl_training_steps ?? null,
        rlBufferSize: trainingStats.rl_buffer_size ?? null,
        selectionAlgorithm: payload?.selection_policy?.algorithm ?? null,
        selectionSelectedCount: payload?.selection_policy?.selected_count ?? null,
        selectionCandidateCount: payload?.selection_policy?.candidate_count ?? null,
        runReward: payload?.learning?.feedback?.run_reward ?? null
      },
      generatedTests
    };
  } catch {
    return { summary: {}, generatedTests: {} };
  }
}

async function runDomain(jobId, domain) {
  const job = getJob(jobId);
  if (!job) {
    return;
  }

  const tenant = safeToken(job.request.tenantId, 'customer_default');
  const jobStamp = job.createdAt.replace(/[^0-9]/g, '').slice(0, 14);
  const outputDir = path.join(RUN_ROOT, `${jobStamp}_${jobId}_${domain}`);
  const checkpointPath = path.join(CHECKPOINT_ROOT, `${tenant}_${domain}.pt`);
  const specPathOverride = String(job.request.specPaths?.[domain] || '').trim();
  const scriptPath = buildScriptPath();
  const repoRoot = buildRepoRoot();

  await fs.mkdir(outputDir, { recursive: true });

  const args = [
    scriptPath,
    '--domain',
    domain,
    '--tenant-id',
    tenant,
    '--base-url',
    job.request.baseUrl,
    '--output-dir',
    outputDir,
    '--max-scenarios',
    String(job.request.maxScenarios),
    '--pass-threshold',
    String(job.request.passThreshold),
    '--script-kind',
    String(job.request.scriptKind || 'python_pytest'),
    '--environment-profile',
    String(job.request.environmentProfile || 'mock'),
    '--rl-checkpoint',
    checkpointPath
  ];
  if (job.request.workspaceId) {
    args.push('--workspace-id', String(job.request.workspaceId));
  }
  if (job.request.maxRuntimeSec && Number(job.request.maxRuntimeSec) > 0) {
    args.push('--max-runtime-sec', String(job.request.maxRuntimeSec));
  }
  if (job.request.llmTokenCap && Number(job.request.llmTokenCap) > 0) {
    args.push('--llm-token-cap', String(job.request.llmTokenCap));
  }

  if (specPathOverride) {
    args.push('--action', 'run', '--spec-path', specPathOverride);
  } else if (PRESET_DOMAINS.has(domain)) {
    args.push('--action', 'both');
  } else {
    appendJobLog(
      jobId,
      `[${domain}] Unsupported custom domain without spec path. Provide specPaths.${domain}=/path/to/openapi.yaml`
    );
    setDomainResult(jobId, domain, {
      domain,
      exitCode: 2,
      scriptKind: String(job.request.scriptKind || 'python_pytest'),
      outputDir,
      checkpointPath,
      specPath: '',
      reportJsonPath: '',
      reportMdPath: '',
      firstPassReportJsonPath: '',
      firstPassReportMdPath: '',
      secondPassReportJsonPath: null,
      secondPassReportMdPath: null,
      summary: { error: 'missing_spec_path_for_custom_domain' },
      generatedTests: {}
    });
    return 2;
  }

  if (job.request.prompt) {
    args.push('--prompt', job.request.prompt);
  }
  if (job.request.customerMode) {
    args.push('--customer-mode', '--customer-root', job.request.customerRoot);
  }
  if (job.request.verifyPersistence) {
    args.push('--verify-persistence');
  }

  appendJobLog(jobId, '');
  appendJobLog(jobId, `===== DOMAIN ${domain} =====`);
  appendJobLog(jobId, `$ bash ${args.map((v) => (v.includes(' ') ? JSON.stringify(v) : v)).join(' ')}`);

  updateJob(jobId, { currentDomain: domain });

  const proc = spawn('bash', args, {
    cwd: repoRoot,
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe']
  });

  const finishStream = streamProcessOutput(proc, (line) => appendJobLog(jobId, `[${domain}] ${line}`));

  const exitCode = await new Promise((resolve) => {
    proc.on('close', (code) => {
      finishStream();
      resolve(code ?? 1);
    });
  });

  const reportJsonPath = path.join(outputDir, 'qa_execution_report.json');
  const reportMdPath = path.join(outputDir, 'qa_execution_report.md');
  const persistenceDir = `${outputDir}_persistence_check`;
  const persistenceReportJsonPath = path.join(persistenceDir, 'qa_execution_report.json');
  const persistenceReportMdPath = path.join(persistenceDir, 'qa_execution_report.md');
  const hasPersistenceReport =
    job.request.verifyPersistence && (await fileExists(persistenceReportJsonPath));

  const finalReportJsonPath = hasPersistenceReport ? persistenceReportJsonPath : reportJsonPath;
  const finalReportMdPath = hasPersistenceReport ? persistenceReportMdPath : reportMdPath;
  const reportData = await readSummary(finalReportJsonPath);

  setDomainResult(jobId, domain, {
    domain,
    exitCode,
    scriptKind: String(job.request.scriptKind || 'python_pytest'),
    outputDir,
    checkpointPath,
    specPath: specPathOverride || '',
    reportJsonPath: finalReportJsonPath,
    reportMdPath: finalReportMdPath,
    firstPassReportJsonPath: reportJsonPath,
    firstPassReportMdPath: reportMdPath,
    secondPassReportJsonPath: hasPersistenceReport ? persistenceReportJsonPath : null,
    secondPassReportMdPath: hasPersistenceReport ? persistenceReportMdPath : null,
    summary: reportData.summary,
    generatedTests: reportData.generatedTests
  });

  return exitCode;
}

export async function runJob(jobId) {
  const job = getJob(jobId);
  if (!job) {
    return;
  }

  await ensureDirs();

  updateJob(jobId, {
    status: 'running',
    startedAt: new Date().toISOString(),
    completedAt: null,
    currentDomain: null,
    error: null
  });

  let failed = false;

  for (const domain of job.request.domains) {
    const exitCode = await runDomain(jobId, domain);
    if ((exitCode ?? 1) !== 0) {
      failed = true;
    }
  }

  updateJob(jobId, {
    status: failed ? 'failed' : 'completed',
    completedAt: new Date().toISOString(),
    currentDomain: null
  });
}

export async function markJobFailed(jobId, message) {
  appendJobLog(jobId, `[error] ${message}`);
  updateJob(jobId, {
    status: 'failed',
    completedAt: new Date().toISOString(),
    currentDomain: null,
    error: message
  });
}
