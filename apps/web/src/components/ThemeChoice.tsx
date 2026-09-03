import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

import {
  getThemeProposal,
  proposeSessionThemes,
  refusalWithoutTiming,
  type AccessToken,
  type SourceInput,
  type ThemeCandidate,
} from "../api/client";
import { useInterfaceLocale } from "../interfaceLocale";
import { BuyCreditsLink } from "./BuyCreditsLink";
import { isCreditRefusal } from "./creditRefusal";
import { EXECUTION_POLL_MS } from "./pollIntervals";
import { MAX_THEME_CHARACTERS } from "./themeLimits";

const PROPOSE_FAILED = "主题提炼失败，请重试，或自己写一个主题。";

/**
 * Whether 提炼主题 is offered at all.
 *
 * Off: the assistant is hidden, and with it the only way to press. Nothing can
 * reach `propose`, so no 额度 can be spent on a press the interface no longer
 * shows. The server side is untouched — flipping this back on is the whole of
 * re-enabling it.
 */
const PROPOSAL_OFFERED: boolean = false;

/**
 * 确认主题, between capturing 来源 and creating the task.
 *
 * Two ways in, and the typed one is not the lesser: pressing 提炼主题 asks an
 * Agent what the 来源 have in common and offers three answers, and typing over
 * them — or instead of them — is a complete way to confirm. So is leaving the
 * box empty, which is why nothing here gates 创建任务.
 *
 * 提炼主题 is currently not offered — see `PROPOSAL_OFFERED` — so typing is the
 * only way in, and the rules below describe the assistant as it behaves when it
 * is offered again.
 *
 * The rules that look like details and are not:
 *
 * - The button is live only once every 来源 is captured. A press costs 额度 and
 *   reads whatever is in the session, so pressing over an unfinished 来源 buys
 *   an answer about material the user has not finished adding.
 * - Pressing replaces the three candidates and never the box. Text the user
 *   typed is theirs; a button that erased it would make trying the Agent risky.
 * - A 来源 changing does nothing here. The candidates on screen stay pressable,
 *   because re-deriving them silently would spend 额度 nobody asked to spend.
 */
export function ThemeChoice({
  accessToken,
  clientSessionId,
  theme,
  onThemeChange,
  canPropose,
  disabledReason,
  /** The drafts to propose from, when this is a 来源编辑会话 rather than a new task. */
  sources = null,
  /** One line only this surface needs — what clearing or changing it will do. */
  footnote = null,
  inputId = "task-theme",
  pollIntervalMs = EXECUTION_POLL_MS,
}: {
  accessToken: AccessToken;
  clientSessionId: string;
  theme: string;
  onThemeChange(theme: string): void;
  canPropose: boolean;
  disabledReason: string | null;
  sources?: SourceInput[] | null;
  footnote?: string | null;
  inputId?: string;
  pollIntervalMs?: number;
}) {
  const { t, domainMessage } = useInterfaceLocale();
  const [candidates, setCandidates] = useState<ThemeCandidate[]>([]);
  const [proposalId, setProposalId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!proposalId || !running) return;
    let stopped = false;
    let timer: number;
    const poll = async () => {
      try {
        const proposal = await getThemeProposal(accessToken, proposalId);
        if (stopped) return;
        if (proposal.status === "succeeded") {
          setCandidates(proposal.candidates);
          setRunning(false);
          return;
        }
        if (proposal.status !== "running") {
          setRunning(false);
          setError(PROPOSE_FAILED);
          return;
        }
      } catch {
        // A failed poll is not a failed run: keep waiting and try again.
      }
      if (!stopped) timer = window.setTimeout(() => void poll(), pollIntervalMs);
    };
    timer = window.setTimeout(() => void poll(), pollIntervalMs);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [accessToken, proposalId, running, pollIntervalMs]);

  async function propose() {
    setError(null);
    setRunning(true);
    try {
      const proposal = await proposeSessionThemes(accessToken, clientSessionId, sources);
      // The previous three are gone the moment a new press starts. They were an
      // answer about 来源 this press is re-reading, and keeping them beside the
      // new ones would make the user compare two answers to one question.
      setCandidates([]);
      setProposalId(proposal.id);
    } catch (thrown) {
      setRunning(false);
      setError(refusalWithoutTiming(thrown) ?? PROPOSE_FAILED);
    }
  }

  const tooLong = theme.length > MAX_THEME_CHARACTERS;

  return (
    /*
      The same card a 来源 is, because 主题 is a special 来源 and the pane it
      shares with them should not look like two products. What differs is the
      summary row: the 来源 are numbered, and there is one 主题.
    */
    <article className="source-operation source-operation--theme">
      <p className="source-operation__status source-operation__summary--theme">
        <strong>{t("主题")}</strong>
        <span className="source-operation__pending">
          {theme ? `${theme.length}/${MAX_THEME_CHARACTERS}` : t("可留空")}
        </span>
      </p>
      <p className="creation-hint">
        {t("添加来源共同的主题，知言 Agent 将深度检索该主题的相关内容，打破信息茧房，取其精华，去其糟粕。")}
      </p>
      <label className="sr-only" htmlFor={inputId}>{t("主题")}</label>
      <input
        id={inputId}
        value={theme}
        maxLength={MAX_THEME_CHARACTERS}
        placeholder={t("这些来源共同在谈什么")}
        aria-describedby={`${inputId}-hint`}
        onChange={(event) => onThemeChange(event.target.value)}
      />
      <p className="form-hint" id={`${inputId}-hint`}>
        {footnote ?? t("最多 80 字")}
      </p>
      {tooLong ? <p role="alert" className="form-error">{t("主题不能超过 80 个字。")}</p> : null}
      {PROPOSAL_OFFERED ? (
        <section className="theme-assistant" aria-label={t("提炼主题")}>
          <div className="theme-assistant__body">
            <div className="button-row">
              <button
                className="button button--quiet"
                type="button"
                disabled={!canPropose || running}
                onClick={() => void propose()}
              >
                <Sparkles size={14} aria-hidden="true" />
                {running ? t("正在提炼…") : candidates.length ? t("重新提炼") : t("提炼主题")}
              </button>
              {!canPropose && disabledReason ? (
                <p className="creation-hint">{domainMessage(disabledReason)}</p>
              ) : null}
            </div>
            <p className="creation-hint">{t("使用 AI 从来源中提炼共同主题，从3个候选中选择。")}</p>
            {candidates.length > 0 ? (
              <ul className="theme-candidates" aria-label={t("主题候选")}>
                {candidates.map((candidate) => (
                  <li key={candidate.theme}>
                    <button
                      className="theme-candidate"
                      type="button"
                      aria-pressed={candidate.theme === theme}
                      onClick={() => onThemeChange(candidate.theme)}
                    >
                      <strong>{candidate.theme}</strong>
                      <span>{candidate.why}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {error ? (
              <p role="alert" className="form-error">
                {domainMessage(error)}
                {isCreditRefusal(error) ? <BuyCreditsLink /> : null}
              </p>
            ) : null}
          </div>
        </section>
      ) : null}
    </article>
  );
}
