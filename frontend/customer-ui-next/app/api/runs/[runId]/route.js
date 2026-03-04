export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

import { snapshotJob } from '@/lib/store';

export async function GET(request, { params }) {
  const { searchParams } = new URL(request.url);
  const tail = Number(searchParams.get('tail') || 800);
  const job = snapshotJob(params.runId, tail);
  if (!job) {
    return Response.json({ error: 'run not found' }, { status: 404 });
  }
  return Response.json({ ...job, runId: job.id });
}
