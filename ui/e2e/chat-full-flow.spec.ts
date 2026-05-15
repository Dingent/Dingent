import { expect, test } from "@playwright/test";

const visitorId = "018f4d80-0000-7000-8000-000000000001";

test("guest chat completes a real browser/backend flow and can switch conversations", async ({ page, request }) => {
  await page.addInitScript((id) => {
    window.localStorage.setItem("dingent_visitor_id", id);
    window.localStorage.setItem("currentChatThreadId", "");
  }, visitorId);

  await page.goto("/dingent/web/guest/playwright-e2e/chat");

  await expect(page.getByText("New Chat").first()).toBeVisible();

  const input = page.getByRole("textbox").last();
  await input.fill("Get data and analyze it from the browser");
  await input.press("Enter");

  await expect(page.getByText("Reviewer final answer: browser e2e completed with mocked LLM output.")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Get data and analyze it from the browser")).toBeVisible();

  const state = await request.get("http://127.0.0.1:8765/api/v1/__e2e__/state");
  await expect(state).toBeOK();
  const payload = await state.json();
  expect(payload.boundToolNames).toEqual([
    ["write_todos", "transfer_to_Analyst"],
    ["write_todos", "transfer_to_Reviewer"],
    ["write_todos"],
  ]);
  expect(payload.receivedMessages).toHaveLength(3);
  expect(JSON.stringify(payload.receivedMessages[0])).toContain("Get data and analyze it from the browser");

  await page.getByText("New Chat").first().click();
  await expect(page.getByText("Reviewer final answer: browser e2e completed with mocked LLM output.")).not.toBeVisible();

  await input.fill("Start a second browser conversation");
  await input.press("Enter");
  await expect(page.getByText("Start a second browser conversation")).toBeVisible();

  await page.getByText("Get data and analyze it from the browser").first().click();
  await expect(page.getByText("Reviewer final answer: browser e2e completed with mocked LLM output.")).toBeVisible({ timeout: 30_000 });
});
