export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  return Response.json({
    backend: 'next_proxy_local',
    service: 'qa_customer_ui_next',
    status: 'ok'
  });
}

