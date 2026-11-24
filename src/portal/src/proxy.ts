import { NextResponse, type NextRequest } from "next/server";

import { authConfig } from "@/lib/auth/config";
import { IAP_HEADER } from "@/lib/auth/iap";

/**
 * Early check only: in IAP mode a request without IAP's signed header never reaches a page.
 * The signature itself is verified where data is read (lib/auth/current-user.ts), as Next's
 * authentication guide recommends. The health check path has no header (load balancers).
 */
export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname === "/api/salud") return NextResponse.next();
  if (authConfig().mode === "iap" && !request.headers.get(IAP_HEADER)) {
    return new NextResponse("Acceso solo a través de Identity-Aware Proxy.", { status: 401 });
  }
  return NextResponse.next();
}

export const config = {
  // everything except Next's own assets and dev channels (/_next/static, /_next/image, /_next/hmr)
  matcher: ["/((?!_next/|favicon.ico).*)"],
};
