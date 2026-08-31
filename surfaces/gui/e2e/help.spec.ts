// The in-app user manual (owner ask 2026-08-31). What must hold end to end: the account
// menu reaches it, the overview's cards are the navigation, and both kinds of jump — the
// chapter's "take me there" button and an `app:` chip inside the prose — land on a real
// surface. A dead link here is invisible in unit tests (the chip still renders) but leaves
// a reader stranded, which is the whole point of the page.
import { expect } from "@playwright/test";
import { test } from "./fixtures";

async function openHelp(page) {
  await page.goto("/");
  await page.getByTestId("account-row").click();
  await page.getByRole("button", { name: "Help", exact: true }).click();
}

test("account menu → Help lands on the card overview", async ({ page }) => {
  await openHelp(page);
  await expect(page.getByTestId("help-overview")).toBeVisible();
  await expect(page.getByTestId("help-card-models")).toBeVisible();
  await expect(page.getByTestId("help-card-cost")).toBeVisible();
  await expect(page.getByTestId("help-card-examples")).toBeVisible();
});

test("a card opens its chapter, and the goto button lands on Settings ▸ Models", async ({
  page,
}) => {
  await openHelp(page);
  await page.getByTestId("help-card-models").click();
  await expect(page.getByTestId("help-chapter-models")).toBeVisible();

  await page.getByTestId("help-goto").click();
  // Settings, on the Models section — the provider gallery is unique to it.
  await expect(page.getByTestId("set-provider-openai")).toBeVisible();
});

test("an app: chip inside the prose navigates too", async ({ page }) => {
  await openHelp(page);
  await page.getByTestId("help-card-experts").click();
  // 06 links out to the Expert library from inside a paragraph.
  await page.locator('[data-testid="app-link-chip"][data-target="surface/library"]').first().click();
  await expect(page.getByTestId("library-search")).toBeVisible();
});

test("the sub-nav walks chapters and returns to the overview", async ({ page }) => {
  await openHelp(page);
  await page.getByTestId("help-nav-cost").click();
  await expect(page.getByTestId("help-chapter-cost")).toBeVisible();
  await page.getByTestId("help-nav-overview").click();
  await expect(page.getByTestId("help-overview")).toBeVisible();
});
