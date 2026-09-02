import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";

// Shared "copy to clipboard, flash Copied for 1.2s" control — extracted from the transcript
// bubble's hover meta strip so BubbleMeta, the assistant bubble's persistent BubbleFoot, and the
// Markdown code-block head can all use the same widget. `testId` is a prop (not hardcoded) so
// each caller can keep its own existing data-testid contract (e.g. "bubble-copy").
export function CopyButton({
  text,
  size = 11,
  testId,
  className,
  title,
}: {
  text: string;
  size?: number;
  testId?: string;
  className?: string;
  title?: string;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    // "Copied" only after the write actually lands — WebKit can reject outside a
    // trusted gesture, and claiming success on a silent no-op would gaslight the user.
    navigator.clipboard
      ?.writeText(text)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => {});
  };
  return (
    <button
      type="button"
      className={"flex items-center cursor-pointer hover:text-muted" + (className ? " " + className : "")}
      data-testid={testId}
      title={title ?? t("transcript.copy_message")}
      onClick={copy}
    >
      {copied ? t("transcript.copied") : <Icon name="copy" size={size} />}
    </button>
  );
}
