import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { CapsuleChoice } from "./InstructionEditor";
import { useInterfaceLocale } from "../interfaceLocale";

/**
 * The pieces both kinds of 知言报告 are built from.
 *
 * A 来源 report has seven sections and a 主题 report has six, and they say very
 * different things — but a reader is doing the same thing in both: folding
 * sections, following numbered items, opening evidence, and dropping one item
 * into a 立言指令. Those mechanics live here so the two views cannot drift into
 * looking like two products.
 */

/**
 * Which sections a reader keeps open is a lasting preference, but a per-report
 * one: each report is a different piece of reading, so the fold is stored
 * against the report's own section id and survives a remount and a reload
 * without reaching into the report beside it.
 */
const FOLD_PREFIX = "liyan.zhiyanSection.";

function foldOpen(key: string): boolean {
  return window.localStorage.getItem(`${FOLD_PREFIX}${key}`) === "open";
}

function setFoldOpen(key: string, open: boolean) {
  window.localStorage.setItem(`${FOLD_PREFIX}${key}`, open ? "open" : "closed");
}

/**
 * A report is several sections deep and each one is prose; reading the 逻辑
 * section of the second report should not mean scrolling through the 证据 list
 * of the first. Every section folds, and starts closed so a report opens as an
 * index the reader expands rather than a wall of text.
 */
export function Section({
  id,
  heading,
  children,
}: {
  /** Doubles as the fold's storage key: unique per report and per section. */
  id: string;
  heading: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(() => foldOpen(id));
  return (
    <section className="zhiyan-section" aria-labelledby={id}>
      <h4>
        <button
          className="zhiyan-section__toggle"
          id={id}
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-body`}
          onClick={() => {
            setFoldOpen(id, !open);
            setOpen(!open);
          }}
        >
          {open ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />}
          {heading}
        </button>
      </h4>
      <div id={`${id}-body`} hidden={!open}>
        {children}
      </div>
    </section>
  );
}

/** A section with no content states why, rather than disappearing. */
export function EmptyState({ items, reason }: { items: number; reason: string | null }) {
  const { t } = useInterfaceLocale();
  return items === 0 ? <p className="zhiyan-empty">{reason ?? t("本部分没有内容。")}</p> : null;
}

export function Quote({ text }: { text: string }) {
  return <blockquote className="zhiyan-quote">{text}</blockquote>;
}

export function Refs({ label, refs }: { label: string; refs: string[] }) {
  if (refs.length === 0) return null;
  return (
    <p className="zhiyan-item__refs">
      {label}
      {refs.map((ref) => (
        <span key={ref} className="zhiyan-ref">
          {ref}
        </span>
      ))}
    </p>
  );
}

/**
 * Drops one report item into the 立言指令 as a 胶囊.
 *
 * `reportKind` travels with it because the server reads a different table for
 * each: a 主题 item cited as a 来源 item would resolve to nothing, and the label
 * is what the writer sees in their instruction — so it names where the item
 * came from rather than only its number.
 */
export function CapsuleButton({
  itemId,
  reportTitle,
  taskVersionId,
  reportId,
  reportKind = "source",
  onSelect,
}: {
  itemId: string;
  reportTitle: string;
  taskVersionId?: string;
  reportId?: string;
  reportKind?: "source" | "theme";
  onSelect?: (choice: CapsuleChoice) => void;
}) {
  const { locale, t } = useInterfaceLocale();
  if (!taskVersionId || !reportId || !onSelect) return null;
  return (
    <button
      className="zhiyan-capsule-button"
      type="button"
      aria-label={locale === "en" ? `Insert ${itemId} into the Liyan instruction` : `插入 ${itemId} 到立言指令`}
      onClick={() => onSelect({
        label: `${reportTitle} · ${itemId}`,
        reference: {
          type: "capsule",
          task_version_id: taskVersionId,
          report_id: reportId,
          item_id: itemId,
          report_kind: reportKind,
        },
      })}
    >
      {t("加入指令")}
    </button>
  );
}
