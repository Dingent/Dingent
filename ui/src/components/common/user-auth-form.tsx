import { useEffect, useState } from "react";
import * as z from "zod";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { Loader2, LogIn } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { ApiClient } from "@/services";
import { useAuthStore } from "@/store";
import type { AuthConfigResponse } from "@/types/entity";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "../ui/form";
import { Input } from "../ui/input";
import { PasswordInput } from "./password-input";
import { Button } from "../ui/button";

const formSchema = z.object({
  email: z.email({
    error: (iss) => (iss.input === "" ? "Please enter your email" : undefined),
  }),
  password: z
    .string()
    .min(1, "Please enter your password")
    .min(7, "Password must be at least 7 characters long"),
});

interface UserAuthFormProps extends React.HTMLAttributes<HTMLFormElement> {
  api: ApiClient;
  onLoginSuccess: (user: any, token: string) => void;
  onLoginFail?: (error: Error) => void;
}

export function UserAuthForm({
  api,
  className,
  onLoginSuccess,
  onLoginFail,
  ...props
}: UserAuthFormProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [authConfig, setAuthConfig] = useState<AuthConfigResponse | null>(null);
  const { setAuth } = useAuthStore();

  useEffect(() => {
    api.auth.getConfig().then(setAuthConfig).catch(() => setAuthConfig(null));
  }, [api]);

  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      email: "",
      password: "",
    },
  });

  function onSubmit(data: z.infer<typeof formSchema>) {
    setIsLoading(true);

    const handleLoginFlow = async () => {
      const { access_token, user } = await api.auth.login({
        email: data.email,
        password: data.password,
      });

      setAuth(access_token, user);

      return { user, access_token };
    };

    toast.promise(handleLoginFlow(), {
      loading: "正在登录并加载数据...",
      success: ({ user, access_token }) => {
        setIsLoading(false);
        // 执行跳转或其他逻辑
        onLoginSuccess(user, access_token);
        return `欢迎回来, ${user.full_name || user.email}!`;
      },
      error: (err) => {
        setIsLoading(false);
        if (onLoginFail) {
          onLoginFail(err);
        }
        // 这里既捕获登录错误，也捕获获取 Workspace 失败的错误
        return err.message || "登录过程中发生错误";
      },
    });
  }

  function handleSsoLogin() {
    const loginUrl = authConfig?.sso_login_url;
    if (!loginUrl) {
      return;
    }

    const currentPath = `${window.location.pathname}${window.location.search}`;
    const returnTo = currentPath.replace(/^\/dingent\/web/, "") || "/";
    window.location.href = `${api.http.defaults.baseURL}${loginUrl}?next=${encodeURIComponent(returnTo)}`;
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className={cn("grid gap-3", className)}
        {...props}
      >
        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Email</FormLabel>
              <FormControl>
                <Input placeholder="name@example.com" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem className="relative">
              <FormLabel>Password</FormLabel>
              <FormControl>
                <PasswordInput placeholder="********" {...field} />
              </FormControl>
              <FormMessage />
              <Link
                href="/forgot-password"
                className="text-muted-foreground absolute end-0 -top-0.5 text-sm font-medium hover:opacity-75"
              >
                Forgot password?
              </Link>
            </FormItem>
          )}
        />
        <Button className="mt-2" disabled={isLoading}>
          {isLoading ? <Loader2 className="animate-spin" /> : <LogIn />}
          Sign in
        </Button>

        <div className="relative my-2">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-background text-muted-foreground px-2">Or</span>
          </div>
        </div>

        <div className={authConfig?.sso_enabled ? "grid grid-cols-2 gap-2" : "grid gap-2"}>
          <Link href="/auth/sign-up">
            <Button
              variant="outline"
              type="button"
              disabled={isLoading}
              className="w-full" // 确保按钮填满 Link 容器的宽度
            >
              Sign up
            </Button>
          </Link>
          {authConfig?.sso_enabled && (
            <Button variant="outline" type="button" disabled={isLoading} onClick={handleSsoLogin}>
              {authConfig.sso_label || "SSO"}
            </Button>
          )}
        </div>
      </form>
    </Form>
  );
}
