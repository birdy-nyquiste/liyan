import { ArrowRight, ChevronDown, FileText, Languages, MonitorCog, MoonStar, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import type { InterfaceLocale } from "../interfaceLocale";
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

function Report({ kind, en }: { kind: "source" | "theme"; en: boolean }) {
  const title = kind === "source" ? (en ? "Source Zhiyan report" : "来源知言报告") : (en ? "Topic Zhiyan report" : "主题知言报告");
  return <article className="site-report" aria-label={title}>
    <header><FileText size={22} aria-hidden="true" /><h4>{title}</h4></header>
    <p className="site-report-intro">[{en ? `${title}: purpose and what you learn` : `${title}：作用与收获说明`}]</p>
    <div className="site-report-sections">
      {reportSections[kind].map((heading, index) => <div className="site-report-section" key={heading}>
        <h5>{en ? englishSections[heading] : heading}</h5>
        <p>[{en ? `${englishSections[heading]} explanation` : `${heading}说明`}]</p>
        <details open={index === 0 || (kind === "theme" && index === 1)}>
          <summary>{en ? "Example A · View example" : "示例 A · 查看示例"}<ChevronDown size={14} aria-hidden="true" /></summary>
          <div className="site-report-example">
            {index === 0 ? (kind === "source"
              ? (en ? ["Content summary", "Fact-check summary", "Reading note"] : ["内容概要", "核查概况", "阅读提示"])
              : (en ? ["Topic landscape", "Consensus and dispute", "Reading note"] : ["主题全景", "共识与争议", "阅读提示"])
            ).map(label => <div key={label}><span>{label}</span><SampleLines /></div>)
              : <>{kind === "theme" && index === 1 ? <span className="site-example-ref">TB-01</span> : null}<span>[{en ? "Example content" : "示例内容"}]</span><SampleLines />{kind === "theme" && index === 1 ? <a className="site-example-link" href="#example-instruction">{en ? "See this example in the instruction" : "查看此示例在立言指令中的引用"}<ArrowRight size={14} aria-hidden="true" /></a> : null}</>}
          </div>
        </details>
      </div>)}
    </div>
  </article>;
}

function ExampleDocument({ title }: { title: string }) {
  return <div className="site-document"><FileText size={20} aria-hidden="true" /><strong>{title}</strong><SampleLines /></div>;
}

function Homepage({ en, action }: { en: boolean; action: ReactNode }) {
  return <main id="main-content" className="site-main">
    <section className="site-hero" aria-labelledby="site-headline">
      <div className="site-hero-copy">
        <h1 id="site-headline">[{en ? "Your headline" : "主标题"}]<br /><span>[{en ? "Second line" : "主标题第二行"}]</span></h1>
        <p>[{en ? "A short introduction to Liyan" : "一句介绍立言阁"}]</p>
        <div className="site-actions">{action}<a className="site-text-link" href="#workflow">{en ? "Explore the workflow" : "了解使用流程"}<ArrowRight size={16} aria-hidden="true" /></a></div>
      </div>
      <ol className="site-journey" aria-label={en ? "Workflow overview" : "流程概览"}>
        {[en ? "Sources · Topic" : "来源 · 主题", en ? "Zhiyan" : "知言", en ? "Liyan" : "立言", en ? "Publications" : "发布"].map((name, index) => <li key={name}><span className="site-journey-number">0{index + 1}</span><strong>{name}</strong><div className="site-journey-glyph" aria-hidden="true">{index === 3 ? <span className="site-mini-branches"><i /><i /><i /></span> : <FileText size={36} strokeWidth={1} />}</div><span>[{en ? "Stage description" : "阶段说明"}]</span></li>)}
      </ol>
    </section>

    <section id="workflow" className="site-workflow" aria-labelledby="workflow-heading">
      <h2 id="workflow-heading" className="site-section-title">{en ? "How it works" : "使用流程"}</h2>
      <section className="site-stage" aria-labelledby="inputs-heading">
        <div className="site-stage-heading"><span className="site-stage-number">01</span><h3 id="inputs-heading">{en ? "Sources · Topic" : "来源 · 主题"}</h3><p>[{en ? "What you provide and how to begin" : "你提供什么，以及如何开始的说明"}]</p></div>
        <div className="site-inputs">{[en ? "Source" : "来源", en ? "Topic" : "主题"].map(title => <article key={title}><header><h4>{title}</h4><span>{en ? "You provide" : "你提供"}</span></header><p>[{en ? `${title} explanation` : `${title}说明`}]</p><ExampleDocument title={`${en ? "Example A" : "示例 A"} · ${title}`} /></article>)}</div>
      </section>
      <section className="site-stage" aria-labelledby="reports-heading">
        <div className="site-stage-heading"><span className="site-stage-number">02</span><h3 id="reports-heading">{en ? "Zhiyan" : "知言"}</h3><p>[{en ? "How Liyan analyses your sources and topic" : "立言阁如何分析来源与主题的说明"}]</p></div>
        <div className="site-reports"><Report kind="source" en={en} /><Report kind="theme" en={en} /></div>
      </section>
      <section className="site-stage" aria-labelledby="writing-heading">
        <div className="site-stage-heading"><span className="site-stage-number">03</span><h3 id="writing-heading">{en ? "Liyan" : "立言"}</h3><p>[{en ? "How your direction shapes the article" : "如何由你决定文章表达的说明"}]</p></div>
        <div className="site-writing">
          <ExampleDocument title={en ? "Example A · Liyan article" : "示例 A · 立言文章"} />
          <div className="site-direction" id="example-instruction"><h4>{en ? "Your Liyan instruction" : "你的立言指令"}</h4><p>[{en ? "Your editorial direction" : "你的表达方向"}]</p><div className="site-citation"><span>TB-01</span><span>[{en ? "Selected topic-report item" : "你选择引用的主题报告内容"}]</span></div><p className="site-small">[{en ? "How to cite report items in your instruction" : "通过立言指令引用报告内容的说明"}]</p></div>
        </div>
      </section>
      <section className="site-stage" aria-labelledby="publication-heading">
        <div className="site-stage-heading"><span className="site-stage-number">04</span><h3 id="publication-heading">{en ? "Publications" : "发布"}</h3><p>[{en ? "The intended publication experience" : "面向发布目标的体验说明"}]</p></div>
        <div className="site-publication" role="img" aria-label={en ? "Example A article branches toward three illustrative publication destinations" : "示例 A 文章连接至三个示意发布目标"}>
          <ExampleDocument title={en ? "Example A · Article" : "示例 A · 立言文章"} />
          <svg viewBox="0 0 120 240" preserveAspectRatio="none" aria-hidden="true"><path d="M0 120 C60 120 50 35 120 35 M0 120 H120 M0 120 C60 120 50 205 120 205" /><circle cx="3" cy="120" r="3" /></svg>
          <div className="site-destinations">{["A", "B", "C"].map(destination => <div key={destination}><FileText size={19} aria-hidden="true" /><span>[{en ? "Destination" : "发布目标"} {destination}]</span></div>)}</div>
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
  return <div className="public-site">
    <a className="site-skip" href="#main-content">{en ? "Skip to content" : "跳至内容"}</a>
    <header className="site-header">
      <Link to="/" className="site-brand" aria-label={en ? "Liyan home" : "立言阁首页"}><img src="/liyan-mark.svg" alt="" /><span>立言阁</span></Link>
      <nav className="site-nav" aria-label={en ? "Page sections" : "页面目录"}>{[["workflow", en ? "How it works" : "使用流程"], ["pricing", en ? "Pricing" : "价格"], ["faq", en ? "FAQ" : "常见问题"]].map(([id, label]) => <Link key={id} to={`/#${id}`}>{label}</Link>)}</nav>
      <div className="site-controls">
        <button type="button" className="site-toggle" onClick={onLocaleChange} aria-label={`${en ? "Language" : "语言"}: ${en ? "English" : "中文"}`}><Languages size={18} aria-hidden="true" /><span>{en ? "EN" : "中文"}</span></button>
        <button type="button" className="site-toggle site-mode" onClick={onModeChange} aria-label={`${en ? "Mode" : "模式"}: ${modeLabel}`} title={modeLabel}>{mode === "light" ? <Sun size={18} aria-hidden="true" /> : mode === "dark" ? <MoonStar size={18} aria-hidden="true" /> : <MonitorCog size={18} aria-hidden="true" />}<span>{modeLabel}</span></button>
        {action}
      </div>
    </header>
    {pathname === "/" ? <Homepage en={en} action={action} /> : legal ? <main id="main-content" className="site-legal"><h1>{pathname === "/terms" ? (en ? "Terms of Use" : "使用条款") : (en ? "Privacy Policy" : "隐私政策")}</h1><p>{en ? "Under construction. Content will be added here." : "页面建设中，内容待补充。"}</p><Link className="site-text-link" to="/">{en ? "Back to home" : "返回首页"}<ArrowRight size={16} aria-hidden="true" /></Link></main> : <main id="main-content" className="site-auth">{children}</main>}
    <footer className="site-footer"><div className="site-footer-brand"><span>立言阁</span><p>{en ? "A product of Nyquiste Corporation" : "Nyquiste Corporation 旗下产品"}</p></div><div className="site-footer-bottom"><small>© {new Date().getFullYear()} Nyquiste Corporation</small><nav aria-label={en ? "Legal and contact" : "法律与联系"}><Link to="/terms">{en ? "Terms of Use" : "使用条款"}</Link><Link to="/privacy">{en ? "Privacy Policy" : "隐私政策"}</Link><a href="mailto:birdyyao@nyquiste.com">{en ? "Contact us" : "联系我们"}</a></nav></div></footer>
  </div>;
}
