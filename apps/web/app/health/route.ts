/** Liveness endpoint of the web service, polled by the status checker (scheduler `service_health` task). */
export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json(
    { status: "ok", service: "web", time: new Date().toISOString() },
    { headers: { "Cache-Control": "no-store" } },
  );
}
