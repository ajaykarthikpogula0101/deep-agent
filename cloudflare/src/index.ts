import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  ASSISTANT: DurableObjectNamespace<Assistant>;
  BACKUPS: R2Bucket;
  APP_ENV: string; // secret: JSON object of every setting in .env.production (built by deploy.sh)
}

const appEnv = (env: Env): Record<string, string> => JSON.parse(env.APP_ENV || "{}");

export class Assistant extends Container<Env> {
  defaultPort = 8080;
  pingEndpoint = "localhost/healthz";
  // No sleepAfter on purpose: the in-process scheduler must stay alive between visits.
  sleepAfter = "720h";
  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    const app = appEnv(env);
    this.envVars = {
      // Only this Worker can reach the container, and fetch() below rewrites X-Forwarded-For,
      // so believing forwarding headers from any peer is safe here.
      TRUSTED_PROXIES: "0.0.0.0/0,::/0",
      // Embedded Postgres snapshots go to R2 through this Worker's /__backup route.
      BACKUP_URL: `${app.PUBLIC_BASE_URL || "https://assistant.deependhq.com"}/__backup`,
      ...app,
    };
  }
  // Cloudflare shows no container stdout in wrangler; these at least put the exit code in the Worker's tail.
  override onStart() { console.log("container started"); }
  override onStop(p: { exitCode: number; reason: string }) { console.log(`container stopped exit=${p.exitCode} reason=${p.reason}`); }
  override onError(e: unknown) { console.log(`container error ${String(e)}`); }
}

const one = (env: Env) => getContainer(env.ASSISTANT, "main");

// GET/PUT /__backup/<key>: the container's snapshot store, guarded by the same admin token the app uses.
async function backup(request: Request, env: Env, key: string): Promise<Response> {
  const token = appEnv(env).ADMIN_TOKEN;
  if (!token || request.headers.get("x-admin-token") !== token || !/^[\w.-]+(\/[\w.-]+)*$/.test(key)) {
    return new Response("forbidden", { status: 403 });
  }
  if (request.method === "PUT") {
    await env.BACKUPS.put(key, request.body);
    return new Response("ok");
  }
  const obj = await env.BACKUPS.get(key);
  return obj ? new Response(obj.body) : new Response("none", { status: 404 });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/__backup/")) return backup(request, env, url.pathname.slice("/__backup/".length));
    // Replace anything the visitor sent with the one address Cloudflare vouches for.
    const headers = new Headers(request.headers);
    for (const h of ["x-forwarded-for", "x-real-ip", "forwarded"]) headers.delete(h);
    const ip = request.headers.get("cf-connecting-ip");
    if (ip) headers.set("x-forwarded-for", ip);
    return one(env).fetch(new Request(request, { headers }));
  },
  async scheduled(_c: ScheduledController, env: Env): Promise<void> {
    await one(env).fetch(new Request("http://localhost/healthz"));
  },
};
