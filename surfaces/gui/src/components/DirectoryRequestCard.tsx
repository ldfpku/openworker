import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Item } from "../types";
import { chooseFolder } from "../tauri";
import { Icon } from "./Icon";
import { IconButton } from "./IconButton";
import { BTN_ACCENT, BTN_BORDERED } from "./buttons";

type DirReqItem = Extract<Item, { kind: "dirreq" }>;

// The agent asked (via request_directory) for access to a folder. The user picks/confirms a path
// and access level, or declines — mirroring the approval card, shown in the composer head.
export function DirectoryRequestCard({
  item,
  onRespond,
}: {
  item: DirReqItem;
  onRespond: (granted: boolean, path?: string, writable?: boolean) => void;
}) {
  const { t } = useTranslation();
  const [path, setPath] = useState(item.path || "");
  const [writable, setWritable] = useState(!!item.writable);

  const browse = async () => {
    const picked = await chooseFolder();
    if (picked) setPath(picked);
  };

  return (
    <div className="dirreq-card">
      <div className="dirreq-head">
        <Icon name="folderPlus" size={16} className="ico" />
        <span>
          {item.primary
            ? t("dirreq.requesting_workspace")
            : t("dirreq.requesting_access")}
        </span>
      </div>
      {item.reason && <div className="dirreq-reason">“{item.reason}”</div>}
      {item.primary && (
        <div className="dirreq-reason">
          {t("dirreq.primary_note")}
        </div>
      )}
      <div className="dirreq-pathrow">
        <input
          className="dirreq-path"
          placeholder={t("dirreq.path_placeholder")}
          value={path}
          onChange={(e) => setPath(e.target.value)}
        />
        <IconButton variant="bordered" icon="folder" size={15} onClick={browse} label={t("dirreq.choose_location")} />
      </div>
      <div className="dirreq-actions">
        {!item.primary && (
          <label className="dirreq-access">
            <input type="checkbox" checked={writable} onChange={(e) => setWritable(e.target.checked)} />
            {t("dirreq.allow_writing")}
          </label>
        )}
        <span className="spacer" />
        <button className={BTN_BORDERED} onClick={() => onRespond(false)}>
          {t("dirreq.decline")}
        </button>
        <button
          className={BTN_ACCENT}
          disabled={!path.trim()}
          onClick={() => onRespond(true, path.trim(), item.primary ? true : writable)}
        >
          {item.primary ? t("dirreq.make_workspace") : t("dirreq.grant_access")}
        </button>
      </div>
    </div>
  );
}
