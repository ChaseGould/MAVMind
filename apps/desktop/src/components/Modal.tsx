import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

export function Modal({
  title,
  children,
  onClose,
  footer,
  tone,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  footer: ReactNode;
  tone?: "danger" | "warn";
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${tone ? `modal-${tone}` : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-title">{title}</div>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">{footer}</div>
      </div>
    </div>
  );
}

export type ConfirmOptions = {
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "warn";
  /** Show a free-text input (e.g. a reject reason); its value is returned. */
  input?: { label: string; placeholder?: string };
};

export type ConfirmResult = { confirmed: boolean; value: string };

type Pending = ConfirmOptions & { resolve: (r: ConfirmResult) => void };

/**
 * Promise-based confirm dialog. Render `dialog` somewhere in the component and
 * `await confirm({...})` from event handlers.
 */
export function useConfirm(): [ReactNode, (o: ConfirmOptions) => Promise<ConfirmResult>] {
  const [pending, setPending] = useState<Pending | null>(null);
  const [value, setValue] = useState("");
  const confirmRef = useRef<HTMLButtonElement>(null);

  const confirm = useCallback(
    (o: ConfirmOptions) =>
      new Promise<ConfirmResult>((resolve) => {
        setValue("");
        setPending({ ...o, resolve });
      }),
    [],
  );

  useEffect(() => {
    if (pending && !pending.input) confirmRef.current?.focus();
  }, [pending]);

  const close = useCallback(
    (confirmed: boolean) => {
      if (!pending) return;
      setPending(null);
      pending.resolve({ confirmed, value: value.trim() });
    },
    [pending, value],
  );

  const dialog = pending ? (
    <Modal
      title={pending.title}
      tone={pending.tone}
      onClose={() => close(false)}
      footer={
        <>
          <button className="btn" onClick={() => close(false)}>
            {pending.cancelLabel ?? "Cancel"}
          </button>
          <button
            ref={confirmRef}
            className={`btn ${pending.tone === "danger" ? "btn-danger" : pending.tone === "warn" ? "btn-warn" : "btn-primary"}`}
            onClick={() => close(true)}
          >
            {pending.confirmLabel ?? "Confirm"}
          </button>
        </>
      }
    >
      <div>{pending.body}</div>
      {pending.input && (
        <label className="field">
          <span>{pending.input.label}</span>
          <input
            autoFocus
            value={value}
            placeholder={pending.input.placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && close(true)}
          />
        </label>
      )}
    </Modal>
  ) : null;

  return [dialog, confirm];
}
