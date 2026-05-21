import { ApiClient } from "@/services";
import Cookies from "js-cookie";
import { useAuthStore } from "@/store";
import { getOrSetVisitorId } from "../utils";

const BASE_PATH = "/dingent/web";

const getBaseUrl = () => `${BASE_PATH}/api/v1`;

let clientInstance: ApiClient | null = null;
let cachedToken: string | null = null;
let cachedVisitorId: string | null = null;

export function getClientApi() {
  const state = useAuthStore.getState();
  const token = state.accessToken || Cookies.get("access_token") || null;
  let visitorId = state.visitorId || Cookies.get("visitor_id") || null;

  if (!token && !visitorId) {
    visitorId = getOrSetVisitorId();
  }

  if (
    !clientInstance ||
    token !== cachedToken ||
    visitorId !== cachedVisitorId
  ) {
    cachedToken = token;
    cachedVisitorId = visitorId;

    clientInstance = new ApiClient(
      { baseURL: getBaseUrl() },
      token,
      visitorId,
      () => {
        useAuthStore.getState().logout();
        if (typeof window !== "undefined") {
          // ✅ 3. 检查当前路径时，也要包含 BASE_PATH
          // window.location.pathname 浏览器返回的是包含 base path 的完整路径
          // 例如：/dingent/web/auth/login
          if (!window.location.pathname.startsWith(`${BASE_PATH}/auth/login`)) {
            const currentPath = encodeURIComponent(
              window.location.pathname + window.location.search,
            );

            // ✅ 4. 关键修正：手动拼接 BASE_PATH
            // 否则会跳转到域名根目录导致 404
            window.location.href = `${BASE_PATH}/auth/login?redirect=${currentPath}`;
          }
        }
      },
    );
  }

  return clientInstance;
}
