import { Suspense } from "react";
import SsoCallbackRoute from "./sso-callback-route";

export default function Page() {
  return (
    <Suspense fallback={<div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Completing SSO login...</div>}>
      <SsoCallbackRoute />
    </Suspense>
  );
}
