import { ArrowRight, ChevronDown, Compass, Feather, FileSearch, FileStack, Languages, MonitorCog, MoonStar, ScrollText, Sun, Telescope } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import type { InterfaceLocale } from "../interfaceLocale";
import { LegalDocument } from "./legal";
import "./public.css";

export type DisplayMode = "light" | "dark" | "system";
type PublicSiteProps = {
  locale: InterfaceLocale;
  mode: DisplayMode;
  onLocaleChange(): void;
  onModeChange(): void;
  signedIn: boolean;
  checking: boolean;
  children?: ReactNode;
};

// Public copy is intentionally kept here, separate from the workbench's UI
// dictionary. Brackets reserve the author's words; they are not product claims.
const reportSections = {
  source: ["概要", "“知”来源", "“知”事实", "“知”观点", "“知”逻辑", "“知”意图", "“知”依据"],
  theme: ["概要", "“知”盲点", "“知”事实", "“知”观点", "“知”分歧", "“知”依据"],
} as const;
const englishSections: Record<string, string> = {
  "概要": "Overview", "“知”来源": "Source", "“知”事实": "Facts", "“知”观点": "Viewpoints",
  "“知”逻辑": "Logic", "“知”意图": "Intent", "“知”依据": "Evidence", "“知”盲点": "Blind spots", "“知”分歧": "Disagreements",
};

function SampleLines() {
  return <div className="site-sample-lines" aria-hidden="true"><i /><i /><i /></div>;
}

/**
 * What each 知言报告 does, and the instrument it does it with.
 *
 * The icons carry a small system rather than being picked one at a time:
 * 来源 things are document-shaped — a stack of formats, then a document being
 * examined — and 主题 things are instruments — a compass to point, a telescope
 * to see past 信息茧房.
 */
const reports = {
  source: {
    icon: FileSearch,
    zh: "对每一个来源，抽丝剥茧，核查事实，分析观点，理清逻辑。",
    en: "Every source, unravelled thread by thread: facts checked, arguments weighed, logic laid bare.",
  },
  theme: {
    icon: Telescope,
    zh: "对来源的共同主题，深度检索，打破信息茧房，取其精华，去其糟粕。",
    en: "The theme your sources share, searched in depth: the information cocoon broken, the essence kept, the dross discarded.",
  },
} as const;

function Report({ kind, en }: { kind: "source" | "theme"; en: boolean }) {
  const title = kind === "source" ? (en ? "Source Zhiyan report" : "来源知言报告") : (en ? "Theme Zhiyan report" : "主题知言报告");
  const { icon: Icon } = reports[kind];
  return <article className="site-report" aria-label={title}>
    <header><span className="site-report-title"><Icon size={22} aria-hidden="true" /><h4>{title}</h4></span></header>
    <p className="site-report-intro">{reports[kind][en ? "en" : "zh"]}</p>
    {/* The sections are bounded and scroll inside that bound, so a report of
        seven of them does not set the height of the whole stage. Both reports
        take the same bound, which is what keeps the two columns level. The
        region is focusable and named because a scroll container that only a
        mouse can reach is not reachable. */}
    <div className="site-scroll">
      <div
        className="site-scroll-body"
        role="group"
        aria-label={en ? `${title} sections` : `${title}各节`}
        tabIndex={0}
      >
      {reportSections[kind].map((heading, index) => <div className="site-report-section" key={heading}>
        <h5>{en ? englishSections[heading] : heading}</h5>
        <p>[{en ? `${englishSections[heading]} explanation` : `${heading}说明`}]</p>
        <details open={index === 0 || (kind === "theme" && index === 1)}>
          <summary>{en ? "Example A · View example" : "示例 A · 查看示例"}<ChevronDown size={14} aria-hidden="true" /></summary>
          <div className="site-report-example">
            {index === 0 ? (kind === "source"
              ? (en ? ["Content summary", "Fact-check summary", "Reading note"] : ["内容概要", "核查概况", "阅读提示"])
              : (en ? ["Theme landscape", "Consensus and dispute", "Reading note"] : ["主题全景", "共识与争议", "阅读提示"])
            ).map(label => <div key={label}><span>{label}</span><SampleLines /></div>)
              : <>{kind === "theme" && index === 1 ? <span className="site-example-ref">TB-01</span> : null}<span>[{en ? "Example content" : "示例内容"}]</span><SampleLines />{kind === "theme" && index === 1 ? <a className="site-example-link" href="#example-instruction">{en ? "See this example in the instruction" : "查看此示例在立言指令中的引用"}<ArrowRight size={14} aria-hidden="true" /></a> : null}</>}
          </div>
        </details>
      </div>)}
      </div>
    </div>
  </article>;
}

/** The article, as much of it as a placeholder can be. */
function SampleArticle() {
  return (
    <div className="site-article-body">
      {Array.from({ length: 12 }, (_, index) => <SampleLines key={index} />)}
    </div>
  );
}

/* Every caller names its own icon, so there is no default to fall back to. */
function ExampleDocument({ title, icon: Icon }: { title: string; icon: LucideIcon }) {
  return <div className="site-document"><Icon size={20} aria-hidden="true" /><strong>{title}</strong><SampleLines /></div>;
}

/**
 * 知 or 立, set apart.
 *
 * The two verbs 立言阁 is named for, and the whole claim is the order they come
 * in — so they are marked wherever they appear in the headline and the lede
 * rather than left to read as ordinary characters. 楷体 against 宋体 is the
 * distinction, the accent makes it visible at a glance, and the size makes it
 * lead. English has no 楷体, so it takes the equivalent device: the serif in
 * italic, which is what the Latin tradition does with a word lifted out of a
 * line. `:lang()` picks between them — `App.tsx` keeps `<html lang>` in step
 * with the locale.
 */
function Verb({ children }: { children: ReactNode }) {
  return <span className="site-verb">{children}</span>;
}

/**
 * A run that may not break across lines.
 *
 * Chinese breaks between any two characters, so an unprotected 妙笔生花 can
 * lose its last character to the next line and a four-character idiom read as
 * two halves of nothing. Wrapping each idiom and each clause leaves the line
 * able to turn only where the punctuation already says it may.
 */
function Clause({ children }: { children: ReactNode }) {
  return <span className="site-clause">{children}</span>;
}

function Homepage({ en, action }: { en: boolean; action: ReactNode }) {
  return <main id="main-content" className="site-main">
    <section className="site-hero" aria-labelledby="site-headline">
      {/*
        Two columns divided by the page's own figure: a hairline with a brass
        node on it, which is what `.site-stage-heading` puts beside every stage
        of 使用流程 below. The hero is that figure at hero scale rather than a
        device invented for one section.
      */}
      <div className="site-hero-couplet">
      {/* A couplet: two lines by construction, not by wrapping. Both halves
          begin with the marked verb, so 知 sits directly above 立 — and the
          same is true of the two promise lines opposite, which are the same
          couplet again at reading size. Nothing may indent or centre these or
          that column of verbs comes apart. */}
      <h1 id="site-headline">
        {en ? (
          <>
            <Clause>
              <Verb>Know</Verb> the vast world
            </Clause>
            <Clause>
              <Verb>Write</Verb> what endures
            </Clause>
          </>
        ) : (
          <>
            <Clause>
              <Verb>“知”</Verb>大千世界
            </Clause>
            <Clause>
              <Verb>“立”</Verb>不朽篇章
            </Clause>
          </>
        )}
      </h1>
      </div>
      <div className="site-hero-page">
      {/*
        Four lines, and the typography is the argument.
        The first is 信息繁杂, so it is set in the sans — the voice of
        undifferentiated information — and recessed. The last two are 妙笔生花,
        so they are 宋体 at reading size: composed prose, the form arriving
        where the sentence does. Between them the hinge, which belongs to the
        lines it introduces rather than to the one it follows — hence generous
        space above it and tight space below.
      */}
      <div className="site-lede">
        {en ? (
          <>
            <p className="site-lede-problem">
              What you read piles up and stirs a hundred thoughts; the feeling arrives, the
              words do not.
            </p>
            <p className="site-lede-turn">立言阁 helps you:</p>
            <p className="site-lede-promise">
              First <Verb>know</Verb> what was said — keep the essence, discard the dross;
            </p>
            <p className="site-lede-promise">
              then <Verb>write</Verb> words of your own — the thoughts well up, and the pen
              flowers.
            </p>
          </>
        ) : (
          <>
            <p className="site-lede-problem">信息繁杂，时常感慨万千；有感而发，不知如何表达</p>
            <p className="site-lede-turn">立言阁帮你：</p>
            <p className="site-lede-promise">
              <Clause>
                先<Verb>“知”</Verb>其言
              </Clause>
              ，<Clause>取其精华</Clause>，<Clause>去其糟粕</Clause>；
            </p>
            <p className="site-lede-promise">
              <Clause>
                再<Verb>“立”</Verb>其言
              </Clause>
              ，<Clause>文思泉涌</Clause>，<Clause>妙笔生花</Clause>。
            </p>
          </>
        )}
      </div>
      <div className="site-actions">{action}<a className="site-text-link" href="#workflow">{en ? "Explore the workflow" : "了解使用流程"}<ArrowRight size={16} aria-hidden="true" /></a></div>
      </div>
    </section>

    <section id="workflow" className="site-workflow" aria-labelledby="workflow-heading">
      <h2 id="workflow-heading" className="site-section-title">{en ? "How it works" : "使用流程"}</h2>
      <section className="site-stage" aria-labelledby="inputs-heading">
        <div className="site-stage-heading"><span className="site-stage-number">01</span><h3 id="inputs-heading">{en ? "Sources · Theme" : "来源 · 主题"}</h3><p>{en ? "Upload your sources, then add the theme they share." : "上传来源，添加来源的共同主题"}</p></div>
        {/* 来源 is a stack of mixed formats and 主题 is the direction the agent
            is pointed in, so the two icons differ in silhouette rather than in
            detail — stacked rectangles against a circle, told apart at a glance
            and at 20px. */}
        <div className="site-inputs">
          {[
            {
              title: en ? "Source" : "来源",
              icon: FileStack,
              body: en
                ? "Pasted text, URL capture, Markdown, PDF, TXT, DOCX"
                : "文本粘贴，URL抓取，Markdown，PDF，TXT，DOCX",
            },
            {
              title: en ? "Theme" : "主题",
              icon: Compass,
              body: en ? "The theme your sources share." : "来源的共同主题",
            },
          ].map(({ title, icon: Icon, body }) => (
            <article key={title}>
              <header>
                <Icon size={20} aria-hidden="true" />
                <h4>{title}</h4>
              </header>
              <p>{body}</p>
              <ExampleDocument title={`${en ? "Example A" : "示例 A"} · ${title}`} icon={Icon} />
            </article>
          ))}
        </div>
      </section>
      <section className="site-stage" aria-labelledby="reports-heading">
        <div className="site-stage-heading"><span className="site-stage-number">02</span><h3 id="reports-heading">{en ? "Zhiyan" : "知言"}</h3>
          {/* A citation rather than a sentence, so it is set as one: the
              classical text in 宋体, the attribution on its own line. Mencius'
              four clauses are parallel six-character units — breaking one in
              half would ruin the figure — so each is a Clause. */}
          <p className="site-stage-quote">
            {en ? (
              /* English has no six-character parallel to hold, and its clauses
                 are long enough that forcing one per line would wrap each of
                 them anyway. It stays prose. */
              <>
                Asked: “What is it to know words?” Mencius said: “In one-sided words, know what
                they hide; in extravagant words, know where they have fallen; in deviant words,
                know what they have strayed from; in evasive words, know where they run out.”
              </>
            ) : (
              /* One line each, structurally rather than by wrapping, so the
                 four clauses line up under one another and the parallel is
                 visible as a shape. The opening quote stays on 孟子曰's line;
                 leading the first clause it would indent that one clause and
                 the column would come apart. */
              <>
                <span className="site-quote-line">问：“何谓知言？”</span>
                <span className="site-quote-line">孟子曰：“</span>
                <span className="site-quote-line">诐辞知其所蔽，</span>
                <span className="site-quote-line">淫辞知其所陷，</span>
                <span className="site-quote-line">邪辞知其所离，</span>
                <span className="site-quote-line">遁辞知其所穷”</span>
              </>
            )}
            <cite>{en ? "Mencius · Gongsun Chou I" : "出自《孟子 · 公孙丑上》"}</cite>
          </p>
        </div>
        <div className="site-reports"><Report kind="source" en={en} /><Report kind="theme" en={en} /></div>
      </section>
      <section className="site-stage" aria-labelledby="writing-heading">
        <div className="site-stage-heading">
          <span className="site-stage-number">03</span>
          <h3 id="writing-heading">{en ? "Liyan" : "立言"}</h3>
          {/* Where the product's own name comes from: 立言 is one of the 三不朽,
              and 不朽篇章 in the headline is this passage. Set as a citation,
              like 知言's. */}
          <p className="site-stage-quote">
            {en ? (
              <>
                “Highest is to establish virtue; next, to establish merit; next, to establish
                words. Long past and still not fallen away — this is what is called
                imperishable.”
              </>
            ) : (
              <>
                {/* The opening quote hangs into the margin so that 太 sits above
                    其 and 其 — three parallel clauses, one column. */}
                <span className="site-quote-line site-quote-line--hang">
                  <span className="site-quote-mark">“</span>太上有立德，
                </span>
                <span className="site-quote-line">其次有立功，</span>
                <span className="site-quote-line">其次有立言。</span>
                <span className="site-quote-line">虽久不废，此之谓不朽”</span>
              </>
            )}
            <cite>{en ? "Zuo Zhuan · Duke Xiang, year 24" : "出自《左传 · 襄公二十四年》"}</cite>
          </p>
        </div>
        <div className="site-writing">
          {/* The article is bounded and scrolls, exactly as the 知言报告 do —
              the same two classes, so the two cannot drift apart. */}
          <article className="site-article" aria-label={en ? "Example A · Liyan article" : "示例 A · 立言文章"}>
            <header>
              <span className="site-report-title">
                <ScrollText size={22} aria-hidden="true" />
                <h4>{en ? "Example A · Liyan article" : "示例 A · 立言文章"}</h4>
              </span>
            </header>
            <div className="site-scroll">
              <div
                className="site-scroll-body"
                role="group"
                aria-label={en ? "Liyan article body" : "立言文章正文"}
                tabIndex={0}
              >
                <SampleArticle />
              </div>
            </div>
          </article>
          <div className="site-direction" id="example-instruction">
            <header>
              <span className="site-report-title">
                <Feather size={22} aria-hidden="true" />
                <h4>{en ? "Your Liyan instruction" : "你的立言指令"}</h4>
              </span>
            </header>
            {/* The field you write the instruction into, drawn with the same
                border, radius and ground the workbench's own inputs use. Not a
                real control: nothing here would have anywhere to send it. */}
            <div className="site-instruction">
              <p>[{en ? "Your editorial direction" : "你的表达方向"}]</p>
              <div className="site-citation"><span>TB-01</span><span>[{en ? "Selected topic-report item" : "你选择引用的主题报告内容"}]</span></div>
            </div>
            <p className="site-small">[{en ? "How to cite report items in your instruction" : "通过立言指令引用报告内容的说明"}]</p>
          </div>
        </div>
      </section>
    </section>

    <section id="pricing" className="site-pricing" aria-labelledby="pricing-heading">
      <div><h2 id="pricing-heading" className="site-section-title">{en ? "Pricing" : "价格"}</h2><p>[{en ? "Pricing and credits explanation" : "价格与额度说明"}]</p></div>
      <div className="site-price-placeholder"><div><h3>[{en ? "Credit pack name" : "额度包名称"}]</h3><p>[{en ? "Credit pack description" : "额度包说明"}]</p></div><div><strong>[{en ? "Price" : "价格"}]</strong><span>[{en ? "Credit amount" : "额度数量"}]</span></div>{action}</div>
    </section>
    <section id="faq" className="site-faq" aria-labelledby="faq-heading">
      <h2 id="faq-heading" className="site-section-title">{en ? "Frequently asked questions" : "常见问题"}</h2>
      <div>{[1, 2, 3].map(number => <details key={number}><summary>[{en ? "Question" : "问题"} {number}]<ChevronDown size={18} aria-hidden="true" /></summary><p>[{en ? "Answer" : "回答"} {number}]</p></details>)}</div>
    </section>
    <section className="site-closing"><h2>[{en ? "Your closing message" : "结尾文案"}]</h2>{action}</section>
  </main>;
}

export function PublicSite({ locale, mode, onLocaleChange, onModeChange, signedIn, checking, children }: PublicSiteProps) {
  const en = locale === "en";
  const { pathname } = useLocation();
  const modeLabel = { light: en ? "Light" : "浅色", dark: en ? "Dark" : "深色", system: en ? "System" : "跟随系统" }[mode];
  const ctaText = checking ? (en ? "Loading…" : "读取中…") : signedIn ? (en ? "Go to workbench" : "前往工作台") : (en ? "Get started" : "立即体验");
  const action = checking ? <span className="site-cta" aria-busy="true">{ctaText}</span> : <Link className="site-cta" to={signedIn ? "/task" : "/sign-in"}>{ctaText}<ArrowRight size={16} aria-hidden="true" /></Link>;
  const legal = pathname === "/terms" || pathname === "/privacy";
  // 登录 is a page with one thing to do on it, and a full marketing footer
  // underneath was both the wrong shape and the reason the footer needed
  // scrolling to reach. The legal links it carries are also inside the card.
  const compactFooter = pathname !== "/" && !legal;
  return <div className="public-site">
    <a className="site-skip" href="#main-content">{en ? "Skip to content" : "跳至内容"}</a>
    <div className="site-header-bar">
      <header className="site-header">
        <Link to="/" className="site-brand" aria-label={en ? "Liyan home" : "立言阁首页"}><img src="/liyan-mark.svg" alt="" /><span>立言阁</span></Link>
        <nav className="site-nav" aria-label={en ? "Page sections" : "页面目录"}>{[["workflow", en ? "How it works" : "使用流程"], ["pricing", en ? "Pricing" : "价格"], ["faq", en ? "FAQ" : "常见问题"]].map(([id, label]) => <Link key={id} to={`/#${id}`}>{label}</Link>)}</nav>
        <div className="site-controls">
          <button type="button" className="site-toggle" onClick={onLocaleChange} aria-label={`${en ? "Language" : "语言"}: ${en ? "English" : "中文"}`}><Languages size={18} aria-hidden="true" /><span>{en ? "EN" : "中文"}</span></button>
          <button type="button" className="site-toggle site-mode" onClick={onModeChange} aria-label={`${en ? "Mode" : "模式"}: ${modeLabel}`} title={modeLabel}>{mode === "light" ? <Sun size={18} aria-hidden="true" /> : mode === "dark" ? <MoonStar size={18} aria-hidden="true" /> : <MonitorCog size={18} aria-hidden="true" />}<span>{modeLabel}</span></button>
          {action}
        </div>
      </header>
    </div>
    {pathname === "/" ? <Homepage en={en} action={action} /> : legal ? <main id="main-content" className="site-legal"><LegalDocument kind={pathname === "/terms" ? "terms" : "privacy"} en={en} /><Link className="site-text-link" to="/">{en ? "Back to home" : "返回首页"}<ArrowRight size={16} aria-hidden="true" /></Link></main> : <main id="main-content" className="site-auth">{children}</main>}
    <footer className={`site-footer${compactFooter ? " site-footer--compact" : ""}`}><div className="site-footer-brand"><span>立言阁</span><p>{en ? "A product of Nyquiste Corporation" : "Nyquiste Corporation 旗下产品"}</p></div><div className="site-footer-bottom"><small>© {new Date().getFullYear()} Nyquiste Corporation</small><nav aria-label={en ? "Legal and contact" : "法律与联系"}><Link to="/terms">{en ? "Terms of Use" : "使用条款"}</Link><Link to="/privacy">{en ? "Privacy Policy" : "隐私政策"}</Link><a href="mailto:birdyyao@nyquiste.com">{en ? "Contact us" : "联系我们"}</a></nav></div></footer>
  </div>;
}
