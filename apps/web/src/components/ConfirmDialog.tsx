import * as AlertDialog from "@radix-ui/react-alert-dialog";

import { useInterfaceLocale } from "../interfaceLocale";

/**
 * The one way this workbench asks "are you sure".
 *
 * `window.confirm` is not it. Browsers are entitled to suppress native dialogs —
 * Chrome offers "prevent this page from creating additional dialogs" after a
 * repeat, embedded views disable them outright — and a suppressed confirm()
 * returns false. Every caller written as `if (!confirm(...)) return;` then
 * becomes a button that silently does nothing, which is exactly how 放弃编辑
 * failed.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  danger = false,
  onConfirm,
  onOpenChange,
}: {
  open: boolean;
  title: string;
  body?: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm(): void;
  onOpenChange(open: boolean): void;
}) {
  const { t } = useInterfaceLocale();
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="dialog-overlay" />
        <AlertDialog.Content className="dialog-content">
          <AlertDialog.Title>{title}</AlertDialog.Title>
          {body ? <AlertDialog.Description>{body}</AlertDialog.Description> : null}
          <div className="dialog-actions">
            <AlertDialog.Cancel className="button button--quiet">{t("取消")}</AlertDialog.Cancel>
            <button
              className={`button${danger ? " button--danger" : ""}`}
              type="button"
              onClick={() => {
                onOpenChange(false);
                onConfirm();
              }}
            >
              {confirmLabel}
            </button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
