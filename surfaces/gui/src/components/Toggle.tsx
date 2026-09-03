// A small on/off switch (mock's `.tgl` / `.knob`) as an accessible button[role=switch]. Driven by
// props so it's testable (query by role "switch", assert aria-checked, fireEvent.click to flip).
// Reused by the persona detail page (default-connection + enable toggles) and the Sources drawer.

export function Toggle({
  checked,
  onChange,
  disabled,
  title,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  /** Tooltip. Defaults to `label` so a bare switch is never mute. */
  title?: string;
  /** Accessible name — what the switch controls ("weekly-report enabled"). */
  label?: string;
}) {
  return (
    <button
      type="button"
      className={"tgl" + (checked ? " on" : "")}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      title={title ?? label}
      onClick={() => {
        if (!disabled) onChange(!checked);
      }}
    >
      <span className="knob" />
    </button>
  );
}
