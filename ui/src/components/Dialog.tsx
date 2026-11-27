import { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom/client";

type Spec = { message: string; initial?: string; text: boolean; okLabel: string; danger?: boolean };

function open<T>(spec: Spec, done: (ok: boolean, value: string) => T): Promise<T> {
  return new Promise((resolve) => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = ReactDOM.createRoot(host);
    const finish = (ok: boolean, value: string) => {
      root.unmount();
      host.remove();
      resolve(done(ok, value));
    };
    root.render(<DialogBox spec={spec} onDone={finish} />);
  });
}

export function askText(message: string, initial = ""): Promise<string | null> {
  return open({ message, initial, text: true, okLabel: "OK" }, (ok, value) => (ok ? value : null));
}

export function askConfirm(message: string, okLabel = "OK", danger = false): Promise<boolean> {
  return open({ message, text: false, okLabel, danger }, (ok) => ok);
}

function DialogBox({ spec, onDone }: { spec: Spec; onDone: (ok: boolean, value: string) => void }) {
  const [value, setValue] = useState(spec.initial ?? "");
  const input = useRef<HTMLInputElement>(null);
  const okBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (spec.text) input.current?.select();
    else okBtn.current?.focus();
  }, [spec.text]);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); onDone(false, value); }
    else if (e.key === "Enter") { e.preventDefault(); onDone(true, value); }
  };
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onDone(false, value)} onKeyDown={onKey}>
      <div className="dialog" role="dialog" aria-modal="true">
        <div className="dialog-message">{spec.message}</div>
        {spec.text && (
          <input ref={input} className="input" style={{ width: "100%" }} value={value} autoFocus
            onChange={(e) => setValue(e.target.value)} />
        )}
        <div className="dialog-actions">
          <button className="btn" onClick={() => onDone(false, value)}>Cancel</button>
          <button ref={okBtn} className={`btn ${spec.danger ? "danger" : "primary"}`} onClick={() => onDone(true, value)}>{spec.okLabel}</button>
        </div>
      </div>
    </div>
  );
}
