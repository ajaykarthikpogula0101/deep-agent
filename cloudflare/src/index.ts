import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  ASSISTANT: DurableObjectNamespace<Assistant>;
  APP_ENV: string; // secret: JSON object of every setting in .env.production (built by deploy.sh)
}

export class Assistant extends Container<Env> {
  defaultPort = 8080;
  pingEndpoint = "localhost/healthz";
  // No sleepAfter on purpose: the in-process scheduler must stay alive between visits.
  sleepAfter = "720h";
  constructor(ctx: DurableObjectState<{}>, env: Env) {
    super(ctx, env);
    this.envVars = {
      // Only this Worker can reach the container, and fetch() below rewrites X-Forwarded-For,
      // so believing forwarding headers from any peer is safe here.
      TRUSTED_PROXIES: "0.0.0.0/0,::/0",
      ...JSON.parse(env.APP_ENV || "{}"),
    };
  }
}

const one = (env: Env) => getContainer(env.ASSISTANT, "main");

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
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
