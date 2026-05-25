"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { getClientApi } from "@/lib/api/client";
import { useAuthStore } from "@/store";

export default function SsoCallbackRoute() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setAuth } = useAuthStore();

  useEffect(() => {
    const token = searchParams.get("token");
    const next = searchParams.get("next") || "/";
    if (!token) {
      toast.error("SSO login did not return an access token");
      router.replace("/auth/login");
      return;
    }

    const api = getClientApi(token);
    api.auth.getMe()
      .then((user) => {
        setAuth(token, user);
        router.replace(next);
      })
      .catch((error) => {
        toast.error(error?.message || "Failed to finish SSO login");
        router.replace("/auth/login");
      });
  }, [router, searchParams, setAuth]);

  return (
    <div className="flex min-h-screen items-center justify-center gap-3 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
      Completing SSO login...
    </div>
  );
}
