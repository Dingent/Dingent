import { Assistant } from "@/types/entity";
import type { AxiosInstance } from "axios";

export class AssistantsApi {
  constructor(
    private http: AxiosInstance,
    private basePath: string = "",
  ) {}

  /**
   * 辅助方法：拼接 URL
   */
  private url(path: string = ""): string {
    return `${this.basePath}${path}`;
  }

  async list(): Promise<Assistant[]> {
    // 移除 try-catch，让错误抛出给 UI 处理
    const { data } = await this.http.get<Assistant[]>(this.url());
    return data;
  }

  async create(payload: {
    name: string;
    description: string;
  }): Promise<Assistant> {
    const { data } = await this.http.post<Assistant>(this.url(), payload);
    return data;
  }

  async delete(assistantId: string): Promise<void> {
    await this.http.delete(this.url(`/${assistantId}`));
  }

  async update(
    assistantId: string,
    payload: Partial<Assistant>,
  ): Promise<Assistant> {
    const transformed = this.transformConfigPayload(payload);
    const { data } = await this.http.patch(
      this.url(`/${assistantId}`),
      transformed,
    );
    return data;
  }

  /**
   * POST /:id/plugins
   * 原 addPluginToAssistant
   */
  async addPlugin(assistantId: string, pluginId: string): Promise<void> {
    await this.http.post(this.url(`/${assistantId}/plugins`), {
      registry_id: pluginId,
    });
  }

  /**
   * DELETE /:id/plugins/:pluginId
   * 原 removePluginFromAssistant
   */
  async removePlugin(assistantId: string, registryId: string): Promise<void> {
    await this.http.delete(this.url(`/${assistantId}/plugins/${registryId}`));
  }

  private transformConfigPayload(
    payload: Partial<Assistant>,
  ): Partial<Assistant> {
    const transformed = structuredClone(payload);

    if (transformed.plugins) {
      transformed.plugins.forEach((plugin: any) => {
        if (Array.isArray(plugin?.config)) {
          const configObj = (plugin.config as any[]).reduce(
            (acc, item: any) => {
              if (
                item?.name &&
                item?.value !== undefined &&
                item?.value !== null
              ) {
                acc[item.name] = item.value;
              }
              return acc;
            },
            {} as Record<string, unknown>,
          );

          plugin.config = configObj;
        }
      });
    }

    return transformed;
  }
}
