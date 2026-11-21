import "server-only";

/** KB_WEB_AI_SUBMIT=true in .env.local shows the "send to Claude" form on an estimate. The worker
 *  has its own switch (KB_ALLOW_WEB_AI_SUBMIT) and refuses without it, whatever the site does. */
export function aiSubmitEnabled(): boolean {
  return ["1", "true", "yes"].includes((process.env.KB_WEB_AI_SUBMIT ?? "").trim().toLowerCase());
}
