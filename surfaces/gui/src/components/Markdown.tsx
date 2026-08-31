import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";

// §34 (UX-016): the agent ends a deliverable turn with plain markdown —
// [Title](artifact:relative/path) — and the renderer turns it into a chip that opens the
// artifact viewer in place. Plumbing is a window event (the viewer lives in RightRail;
// this component renders deep inside the transcript): RightRail resolves the path against
// the session's artifact list, App un-hides the rail.
export const OPEN_ARTIFACT_EVENT = "ocw-open-artifact";

// Seventeenth pass: the lead mentions the board ONCE — [Board · 5 items](board:) — and the
// chip opens the drawer on its Board section. Same event plumbing as artifact chips: App
// un-hides the rail and bumps the key that expands the section.
export const OPEN_BOARD_EVENT = "ocw-open-board";

// The in-app manual writes [去设置 ▸ 模型](app:settings/models) and friends. Same plumbing as the two
// above: a chip that dispatches, and App — which owns openSettings/setSurface/startTour —
// resolves the spec. Markdown stays ignorant of what surfaces exist.
export const OPEN_APP_TARGET_EVENT = "ocw-open-app-target";

function AppLinkChip({ spec, label }: { spec: string; label: string }) {
  return (
    <button
      className="applink-chip"
      data-testid="app-link-chip"
      data-target={spec}
      onClick={() =>
        window.dispatchEvent(new CustomEvent(OPEN_APP_TARGET_EVENT, { detail: { spec } }))
      }
    >
      <span>{label}</span>
      <Icon name="chevronRight" size={12} />
    </button>
  );
}

function BoardChip({ label }: { label: string }) {
  const { t } = useTranslation();
  return (
    <button
      className="boardlink-chip"
      data-testid="board-chip"
      title={t("Open the board")}
      onClick={() => window.dispatchEvent(new CustomEvent(OPEN_BOARD_EVENT))}
    >
      <Icon name="table" size={12} />
      <span>{label || t("Board")}</span>
    </button>
  );
}

function ArtifactChip({ path, title }: { path: string; title: string }) {
  const { t } = useTranslation();
  const file = path.split("/").pop() || path;
  return (
    <button
      className="art-chip"
      data-testid="artifact-chip"
      title={path}
      onClick={() =>
        window.dispatchEvent(new CustomEvent(OPEN_ARTIFACT_EVENT, { detail: { path } }))
      }
    >
      <span className="art-chip-ico">
        <Icon name="file" size={14} />
      </span>
      <span className="art-chip-meta">
        <b>{title || file}</b>
        {title && title !== file && <span>{file}</span>}
      </span>
      <span className="art-chip-open">{t("Open ›")}</span>
    </button>
  );
}

// Assistant messages rendered as GitHub-flavored markdown (headings, lists, tables, code,
// links). Links open externally — never navigate the app shell — except artifact: links,
// which open the session's artifact viewer.
export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        // artifact:/board:/app: are ours — keep them through the sanitizer (everything else gets
        // the default http/https/mailto policy).
        urlTransform={(url) =>
          url.startsWith("artifact:") || url.startsWith("board:") || url.startsWith("app:")
            ? url
            : defaultUrlTransform(url)
        }
        components={{
          a: ({ node: _n, href, children, ...props }) => {
            if (href?.startsWith("artifact:")) {
              const title = Array.isArray(children) ? children.join("") : String(children ?? "");
              return <ArtifactChip path={href.slice("artifact:".length)} title={title} />;
            }
            if (href?.startsWith("board:")) {
              const label = Array.isArray(children) ? children.join("") : String(children ?? "");
              return <BoardChip label={label} />;
            }
            if (href?.startsWith("app:")) {
              const label = Array.isArray(children) ? children.join("") : String(children ?? "");
              return <AppLinkChip spec={href.slice("app:".length)} label={label} />;
            }
            return (
              <a href={href} {...props} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
