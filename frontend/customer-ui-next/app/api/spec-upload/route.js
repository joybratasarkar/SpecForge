export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

import crypto from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';

const SPEC_UPLOAD_ROOT = '/tmp/qa_ui_next_uploaded_specs';
const SPEC_UPLOAD_MAX_BYTES = Math.max(
  32 * 1024,
  Number(process.env.QA_UI_SPEC_UPLOAD_MAX_BYTES || 5 * 1024 * 1024) || 5 * 1024 * 1024
);
const ALLOWED_EXTENSIONS = new Set(['.yaml', '.yml', '.json']);

function sanitizeStem(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64) || 'openapi_spec';
}

export async function POST(request) {
  let formData;
  try {
    formData = await request.formData();
  } catch {
    return Response.json({ error: 'invalid multipart payload' }, { status: 400 });
  }

  const file = formData.get('file');
  if (!(file instanceof File)) {
    return Response.json({ error: 'file field is required' }, { status: 400 });
  }

  const originalFilename = String(file.name || '').trim();
  if (!originalFilename) {
    return Response.json({ error: 'uploaded file name is empty' }, { status: 400 });
  }

  const ext = path.extname(originalFilename).toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    return Response.json({ error: 'unsupported file extension (allowed: .yaml, .yml, .json)' }, { status: 400 });
  }

  if (!Number.isFinite(file.size) || file.size <= 0) {
    return Response.json({ error: 'uploaded file is empty' }, { status: 400 });
  }
  if (file.size > SPEC_UPLOAD_MAX_BYTES) {
    return Response.json(
      { error: `uploaded file exceeds max size (${SPEC_UPLOAD_MAX_BYTES} bytes)` },
      { status: 413 }
    );
  }

  const bytes = Buffer.from(await file.arrayBuffer());
  if (bytes.length <= 0) {
    return Response.json({ error: 'uploaded file is empty' }, { status: 400 });
  }
  if (bytes.length > SPEC_UPLOAD_MAX_BYTES) {
    return Response.json(
      { error: `uploaded file exceeds max size (${SPEC_UPLOAD_MAX_BYTES} bytes)` },
      { status: 413 }
    );
  }

  await fs.mkdir(SPEC_UPLOAD_ROOT, { recursive: true });
  const stem = sanitizeStem(path.basename(originalFilename, ext));
  const token = crypto.randomBytes(6).toString('hex');
  const targetPath = path.join(SPEC_UPLOAD_ROOT, `${Date.now()}_${token}_${stem}${ext}`);
  await fs.writeFile(targetPath, bytes);

  return Response.json({
    spec_path: targetPath,
    original_filename: originalFilename,
    size_bytes: bytes.length
  });
}
