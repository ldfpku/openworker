import { expect } from "@playwright/test";
import { test, sendSessionEvent } from "./fixtures";

// While an ask_user question is open, the composer answers it (owner-hit 2026-10-06):
// before, Enter did nothing, and a question with allow_text false left nowhere to type.
for (const allowText of [false, true]) {
  test(`a typed composer reply answers an open question (allow_text ${allowText})`, async ({ page }) => {
    await page.goto("/");
    await sendSessionEvent(page, { type: "turn_start", data: {} });
    await sendSessionEvent(page, {
      type: "question_requested",
      data: { question: "Which color theme?", options: ["Light", "Dark"], allow_text: allowText, multi: false },
    });
    await expect(page.getByText("Which color theme?")).toBeVisible();
    const composer = page.getByPlaceholder("Type your answer — or pick an option above");
    await expect(composer).toBeVisible();
    await composer.fill("Something warm, like sepia");
    await composer.press("Enter");
    await expect(page.getByText("Got your answer: Something warm, like sepia")).toBeVisible();
    await expect(composer).toHaveCount(0);
    await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveValue("");
  });
}

// A grouped card (the fork's 开工前核对 card is one) answers its CURRENT step with the typed
// text and advances — it must not resolve the whole card with the text filed under step 1.
test("a typed composer reply answers the current step of a grouped question", async ({ page }) => {
  await page.goto("/");
  await sendSessionEvent(page, { type: "turn_start", data: {} });
  await sendSessionEvent(page, {
    type: "question_requested",
    data: {
      question: "Chart style?",
      options: ["Bar", "Line"],
      allow_text: false,
      multi: false,
      header: "Chart style",
      questions: [
        { question: "Chart style?", header: "Chart style", options: ["Bar", "Line"], allow_text: false, multi: false },
        { question: "Which palette?", header: "Palette", options: ["Warm", "Cool"], allow_text: false, multi: false },
      ],
    },
  });
  await expect(page.getByText("Chart style?")).toBeVisible();
  const composer = page.getByPlaceholder("Type your answer — or pick an option above");
  await composer.fill("Pie, actually");
  await composer.press("Enter");
  // Step 1 took the typed answer; the card is still open on step 2.
  await expect(page.getByTestId("question-stepper")).toContainText("2 of 2");
  await expect(page.getByText(/Got your answer/)).toHaveCount(0);
  await composer.fill("Cool");
  await composer.press("Enter");
  await expect(
    page.getByText(`Got your answer: ${JSON.stringify({ "Chart style": "Pie, actually", Palette: "Cool" })}`),
  ).toBeVisible();
  await expect(page.getByPlaceholder(/Ask the coworker/)).toHaveValue("");
});
