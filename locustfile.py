from locust import HttpUser, task, between, events
import uuid
import json

RUN_ID = "f26e1be5-1ce9-423b-9d2d-652c472369ff"

WORKSPACE_SLUG = "Test Workspace"
WORKFLOW_NAME = "single-cell"


class AgentUser(HttpUser):
    # 模拟用户思考时间：1到5秒之间发一次请求
    wait_time = between(1, 5)

    def on_start(self):
        """每个模拟用户启动时执行一次，用于设置 Header"""
        self.headers = {
            "X-Visitor-ID": f"visitor-{uuid.uuid4()}",
            "Content-Type": "application/json",
        }

    @task
    def chat_workflow(self):
        thread_id = str(uuid.uuid4())

        payload = {
            "threadId": thread_id,
            "runId": RUN_ID,
            "tools": [],
            "context": [],
            "forwardedProps": {
                "workspace_slug": WORKSPACE_SLUG,
                "is_guest": True,
            },
            "state": {},
            "messages": [
                {
                    "id": str(uuid.uuid4()),
                    "role": "user",
                    "content": "加载 paul15 造血干细胞数据集...",
                }
            ],
        }

        # 发送请求
        # catch_response 用于自定义请求成功/失败的判定逻辑
        with self.client.post(
            f"/api/v1/{WORKSPACE_SLUG}/chat/agent/{WORKFLOW_NAME}/run",
            json=payload,
            headers=self.headers,
            stream=True,  # 如果是流式响应
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                # 针对流式响应，我们需要读取完数据才算请求结束
                # 否则 Locust 可能只统计了建立连接的时间
                total_size = 0
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        total_size += len(chunk)

                # 你可以在这里加简单的断言
                if total_size > 100:
                    response.success()
                else:
                    response.failure(f"Response too short: {total_size} bytes")
            else:
                response.failure(f"Status code: {response.status_code}")
