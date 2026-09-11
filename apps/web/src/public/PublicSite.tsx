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
// dictionary.
//
// The worked example running through 使用流程 is a real 立言任务, shortened. Its
// 来源 is a column on AI-assisted writing, its 知言报告 and its 立言文章 are the
// ones the product actually produced for it, and every line below is cut from
// those — trimmed hard, because what a visitor needs from this section is the
// shape of the flow, not the whole of an analysis. Names of living people are
// not carried over: the example is here to show what a report looks like, and
// it can do that without publishing a verdict on somebody by name.
const example = {
  source: {
    zh: "《AI代笔风潮之下的讨论和思考（上）》",
    en: "“Writing in the age of the AI ghostwriter (part one)”",
  },
  sourceNote: { zh: "专栏评论 · 约 3,400 字", en: "Column · about 3,400 characters" },
  theme: {
    zh: "AI辅助写作引发的语言同质化与作者主体性焦虑",
    en: "AI-assisted writing, the flattening of language, and the author's loss of self",
  },
} as const;

type Line = { zh: string; en: string };
type ReportSection = {
  heading: Line;
  /** One item from the real report, cut to what fits a folded panel. */
  example: Line | readonly { label: Line; body: Line }[];
};

const sourceSections: readonly ReportSection[] = [
  {
    heading: { zh: "概要", en: "Overview" },
    example: [
      {
        label: { zh: "内容概要", en: "Content summary" },
        body: {
          zh: "以“朋友因被指出‘AI感’而撤稿”的一件小事切入，借齐普夫定律与“最省力原则”，论证生成式 AI 的输出正走向同质化。",
          en: "Opens on a friend withdrawing a submission after being told it “felt like AI”, then argues from Zipf’s law and the principle of least effort that generative AI flattens what it writes.",
        },
      },
      {
        label: { zh: "核查概况", en: "Fact-check summary" },
        body: {
          zh: "引用的作家言论多与原文一致，但一处受访时间与文中说法不符，另一处的后续澄清没有被呈现。",
          en: "Most quoted remarks match their sources, but one interview date does not, and one speaker’s later clarification is left out.",
        },
      },
      {
        label: { zh: "阅读提示", en: "Reading note" },
        body: {
          zh: "文中的个人案例无法由外部资料核实，宜作叙事材料读；标题标注“（上）”，论述可能未完。",
          en: "The personal anecdotes cannot be verified from outside the text, and the title marks this as part one, so the argument may be unfinished.",
        },
      },
    ],
  },
  {
    heading: { zh: "“知”来源", en: "Source" },
    example: {
      zh: "评论性随笔，个人叙事夹叙夹议；未署名，未注明首发媒体，正文残留“广告”字样，疑为抓取时混入的噪声。",
      en: "A personal essay arguing as it narrates. No byline, no publication named, and a stray “advertisement” left in the body — noise from the capture.",
    },
  },
  {
    heading: { zh: "“知”事实", en: "Facts" },
    example: {
      zh: "「某作家新作中 AI 写作的比例已占一半」——存在争议：该表态确有报道，但其后续澄清说明那是 AI 在约 30 步创作流程中的参与，正文未呈现这一澄清。",
      en: "“Half of one novelist’s new book was written by AI” — disputed. The remark was reported, but the speaker later clarified that the half refers to AI’s part in a 30-step process; the source does not carry the clarification.",
    },
  },
  {
    heading: { zh: "“知”观点", en: "Viewpoints" },
    example: {
      zh: "「所谓‘AI感’，是句式与逻辑结构雷同、缺乏个性」——作者的经验式观察，是全文的出发点，可检验性有限。",
      en: "“What feels like AI is sameness of sentence and structure” — the author’s own impression, the starting point of the piece, and hard to test.",
    },
  },
  {
    heading: { zh: "“知”逻辑", en: "Logic" },
    example: {
      zh: "从词频规律（齐普夫定律）泛化为“人类行为普遍法则”，再推出“AI 输出必然同质化”——跨领域类比，中间缺少论证。",
      en: "A word-frequency regularity is generalised into a universal law of behaviour, then straight into “AI output must flatten” — an analogy across fields with the middle missing.",
    },
  },
  {
    heading: { zh: "“知”意图", en: "Intent" },
    example: {
      zh: "以褒义词框定案例中人物的选择，为“撤稿”赋予道德高度，可能意在为论述增加情感正当性。",
      en: "Warm words frame the withdrawn submission as a moral act, which lends the argument feeling in place of evidence.",
    },
  },
  {
    heading: { zh: "“知”依据", en: "Evidence" },
    example: {
      zh: "一篇新闻周刊报道——用于核查上面那条“占一半”的说法。",
      en: "A news weekly’s report — what the “half of it” claim above was checked against.",
    },
  },
] as const;

const themeSections: readonly ReportSection[] = [
  {
    heading: { zh: "概要", en: "Overview" },
    example: [
      {
        label: { zh: "主题全景", en: "Theme landscape" },
        body: {
          zh: "2025—2026 年间讨论明显升温，大致分三层：语言是否真的在同质化、这件事能否用数据检验、以及披露与规范。",
          en: "The debate grew through 2025–26 on three levels: whether language really is flattening, whether that can be measured, and what disclosure rules now require.",
        },
      },
      {
        label: { zh: "共识与争议", en: "Consensus and dispute" },
        body: {
          zh: "共识是 AI 文本占比在快速上升、输出确有向高频表达收缩的倾向；分歧在于同质化发生在形式还是实质，以及这个代价是否可接受。",
          en: "Agreed: AI text is a fast-growing share of what is published, and it does contract toward high-frequency phrasing. Disputed: whether that flattening is of form or of substance, and whether the cost is acceptable.",
        },
      },
      {
        label: { zh: "阅读提示", en: "Reading note" },
        body: {
          zh: "来源的论证较多依赖理论推演，实测部分由本报告补齐。",
          en: "The source argues mostly from theory; the measurements are what this report adds.",
        },
      },
    ],
  },
  {
    heading: { zh: "“知”盲点", en: "Blind spots" },
    example: {
      zh: "缺少以数据检验“同质化是否真的发生”的经验研究。实测比定律推演复杂：语义收缩有数据支持，风格单一化尚未获证实——停留在推演，会把本可检验的问题变成无法反驳的口号。",
      en: "No empirical work testing whether the flattening actually happened. The measurements are messier than the analogy: semantic contraction shows up in the data, stylistic sameness does not — and an argument that stays theoretical turns a testable question into an unanswerable slogan.",
    },
  },
  {
    heading: { zh: "“知”事实", en: "Facts" },
    example: {
      zh: "一项覆盖 2022—2025 年的互联网样本研究估计，到 2025 年年中，约 35% 的新发布网站包含 AI 生成或辅助的文本。",
      en: "A study sampling the web from 2022 to 2025 estimates that by mid-2025 around 35% of newly published sites carried AI-generated or AI-assisted text.",
    },
  },
  {
    heading: { zh: "“知”观点", en: "Viewpoints" },
    example: {
      zh: "一种立场认为，AI 按概率输出，把语言推向高频词与主流观点；依赖它，作者会降格为算法输出的筛选者。",
      en: "One position: AI writes by probability, pushing language toward common words and majority opinion — lean on it and the author is demoted to a picker of its output.",
    },
  },
  {
    heading: { zh: "“知”分歧", en: "Disagreements" },
    example: {
      zh: "表面在争“是否同质化”，实则在争价值排序：当表达效率与语言多样性冲突时，哪一边优先。",
      en: "The surface argument is whether flattening is real; underneath it is an ordering of values — efficiency of expression against diversity of language, when the two conflict.",
    },
  },
  {
    heading: { zh: "“知”依据", en: "Evidence" },
    example: {
      zh: "一部关于人工智能生成内容标识的部门规章全文，2025 年 9 月 1 日起施行。",
      en: "The full text of a rule on labelling AI-generated content, in force from 1 September 2025.",
    },
  },
] as const;

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
    sections: sourceSections,
  },
  theme: {
    icon: Telescope,
    zh: "对来源的共同主题，深度检索，打破信息茧房，取其精华，去其糟粕。",
    en: "The theme your sources share, searched in depth: the information cocoon broken, the essence kept, the dross discarded.",
    sections: themeSections,
  },
} as const;

function Report({ kind, en }: { kind: "source" | "theme"; en: boolean }) {
  const title = kind === "source" ? (en ? "Source ZhiYan report" : "来源知言报告") : (en ? "Theme ZhiYan report" : "主题知言报告");
  const { icon: Icon, sections } = reports[kind];
  const say = (line: Line) => (en ? line.en : line.zh);
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
      {sections.map(({ heading, example }, index) => {
        // 盲点 is the section the 立言指令 below cites, so it carries the
        // reference chip and the link down to it. Nothing opens on arrival:
        // the section names and what each is for are the argument, and seven
        // examples unfolded at once bury them.
        const cited = kind === "theme" && index === 1;
        return <div className="site-report-section" key={heading.zh}>
          <h5>{say(heading)}</h5>
          <details>
            <summary>{en ? "View example" : "查看示例"}<ChevronDown size={14} aria-hidden="true" /></summary>
            <div className="site-report-example">
              {Array.isArray(example)
                ? example.map(({ label, body }) => <div key={label.zh}><span>{say(label)}</span><p>{say(body)}</p></div>)
                : <>
                    {cited ? <span className="site-example-ref">TB-01</span> : null}
                    <span>{say(example as Line)}</span>
                    {cited ? <a className="site-example-link" href="#example-instruction">{en ? "See this example cited in the instruction" : "查看此示例在立言指令中的引用"}<ArrowRight size={14} aria-hidden="true" /></a> : null}
                  </>}
            </div>
          </details>
        </div>;
      })}
      </div>
    </div>
  </article>;
}

/**
 * The 立言文章 this example produced, cut to five paragraphs.
 *
 * The whole piece is ten times this and argues across two 来源 the section
 * does not show. What is kept is the spine — the claim, the argument it comes
 * from, and where it lands — because a visitor is reading this to see that an
 * article comes out at the end, not to read the article.
 */
const articleExcerpt = {
  zh: [
    "先是句子，后是饭碗——这是许多人感知 AI 冲击的顺序。",
    "写东西的人最先警觉：满网都是有“AI感”的文章，句式雷同，逻辑像套模板。两种焦虑通常各说各话，可摆在一起看，它们的结构惊人地相似——而且很可能，都把矛头对准了错误的靶子。",
    "这种直觉不是杯弓蛇影。语言天然向“最省力”处坍缩，而生成式 AI 的原理恰好是预测“下一个最可能的词”，输出必然向高频表达与主流观点集中。",
    "问题在于它瞄准的靶子。绝大多数人的写作从来不是文学创作：技术方案、政策解读要的是清晰、准确、高效，不是句式的个性飞扬。",
    "所以，与其恐慌于句子的同质化，不如警惕思想的懒惰化。机器能以最高效率给出最高频、最正确、最不冒犯的答案；人之所以还有事可做，是因为总有人愿意为没有标准答案的问题熬夜。",
  ],
  en: [
    "First the sentences, then the jobs — that is the order in which most people feel this arriving.",
    "Writers noticed first: the web is full of pieces that feel like AI, the same shapes, the same logic poured into the same mould. The two anxieties are usually argued separately, but set side by side their structure is uncannily alike — and both may be aimed at the wrong target.",
    "The instinct is not imagined. Language collapses toward least effort, and a generative model works by predicting the likeliest next word, so its output contracts toward common phrasing and majority opinion.",
    "The trouble is the target. Almost nobody's writing is literature: a technical proposal or a policy note wants to be clear, accurate and quick, not distinctive in its sentences.",
    "So rather than fear that sentences are converging, watch for thinking going lazy. A machine will give you the most frequent, most correct, least offensive answer at speed; people still have work because some of them will sit up all night with a question that has no standard answer.",
  ],
} as const;

function SampleArticle({ en }: { en: boolean }) {
  return (
    <div className="site-article-body">
      {articleExcerpt[en ? "en" : "zh"].map(paragraph => <p key={paragraph}>{paragraph}</p>)}
    </div>
  );
}

/* Every caller names its own icon, so there is no default to fall back to. */
function ExampleDocument({ title, note, icon: Icon }: { title: string; note: string; icon: LucideIcon }) {
  return <div className="site-document"><Icon size={20} aria-hidden="true" /><strong>{title}</strong><p>{note}</p></div>;
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

function Homepage({ en, action, newcomer }: { en: boolean; action: ReactNode; newcomer: boolean }) {
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
            <p className="site-lede-turn">LiYan Studio helps you:</p>
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
      {/* What the button costs, answered before it is pressed. Only for a
          visitor who could still be granted anything: under 前往工作台 it would
          be offering a signed-in user something they were given long ago, and
          under 读取中… it would be a line that appears and then vanishes. */}
      {newcomer ? <p className="site-actions-note">{en ? "Signing up grants you credits." : "注册即赠送额度"}</p> : null}
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
                ? "Pasted text, web page capture, Markdown, PDF, TXT, DOCX"
                : "粘贴文本，网页文字抓取，Markdown，PDF，TXT，DOCX",
              example: en ? example.source.en : example.source.zh,
              note: en ? example.sourceNote.en : example.sourceNote.zh,
            },
            {
              title: en ? "Theme" : "主题",
              icon: Compass,
              body: en ? "The theme your sources share." : "来源的共同主题",
              example: en ? example.theme.en : example.theme.zh,
              note: en ? "The theme of this example" : "本示例的主题",
            },
          ].map(({ title, icon: Icon, body, example, note }) => (
            <article key={title}>
              <header>
                <Icon size={20} aria-hidden="true" />
                <h4>{title}</h4>
              </header>
              <p>{body}</p>
              <ExampleDocument title={example} note={note} icon={Icon} />
            </article>
          ))}
        </div>
      </section>
      <section className="site-stage" aria-labelledby="reports-heading">
        <div className="site-stage-heading"><span className="site-stage-number">02</span><h3 id="reports-heading">{en ? "ZhiYan" : "知言"}</h3>
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
          <h3 id="writing-heading">{en ? "LiYan" : "立言"}</h3>
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
          <article className="site-article" aria-label={en ? "Example · LiYan article" : "示例 · 立言文章"}>
            <header>
              <span className="site-report-title">
                <ScrollText size={22} aria-hidden="true" />
                <h4>{en ? "“Sentences and paychecks” · excerpt" : "《句子与饭碗：AI 时代的两场焦虑》· 节选"}</h4>
              </span>
            </header>
            <div className="site-scroll">
              <div
                className="site-scroll-body"
                role="group"
                aria-label={en ? "LiYan article body" : "立言文章正文"}
                tabIndex={0}
              >
                <SampleArticle en={en} />
              </div>
            </div>
          </article>
          <div className="site-direction">
            <header>
              <span className="site-report-title">
                <Feather size={22} aria-hidden="true" />
                <h4>{en ? "Your LiYan instruction" : "你的立言指令"}</h4>
              </span>
            </header>
            {/* The field you write the instruction into, drawn with the same
                border, radius and ground the workbench's own inputs use. Not a
                real control: nothing here would have anywhere to send it. */}
            {/* The workbench's own field, drawn the way the workbench draws
                it: one bordered box you write into, with a cited 知言报告 item
                sitting inline in the sentence as a capsule — which is what it
                is there, an atom in the text rather than an attachment under
                it. Not a real control; nothing here would have anywhere to
                send it. */}
            <div className="site-instruction" id="example-instruction">
              <p>
                {en ? "Write for people who are using AI to write. Take no side; land on " : "写给同样在用 AI 写东西的人。不站队，落点放在 "}
                <span className="site-capsule">TB-01</span>
                {en
                  ? " — treat the flattening as something that can be tested, not as a slogan."
                  : " 这条盲点上：把“同质化”当成可以检验的问题，而不是价值口号。"}
              </p>
            </div>
            <p className="site-small">{en
              ? "Anything in either report can be cited this way, by its number. What you cite travels into the article with you; the rest stays reference."
              : "两份报告里的任何一条都可以这样按编号引用。被引用的内容会随你进入文章，其余的只作参考。"}</p>
          </div>
        </div>
      </section>
    </section>

    <section id="pricing" className="site-pricing" aria-labelledby="pricing-heading">
      <div>
        <h2 id="pricing-heading" className="site-section-title">{en ? "Pricing" : "价格"}</h2>
      </div>
      {/* The section's claim, and the thing a visitor came here to find out —
          so it is set at the lede's size and face rather than as a line of
          explanation beside the heading. The grant carries the weight: it is
          the half of the sentence that says nothing has to be paid to begin. */}
      <div className="site-pricing-lede">
        <p>{en ? "Pay for what you use. No subscription." : <><Clause>按量计费</Clause>，<Clause>没有订阅</Clause>。</>}</p>
        {/* No figure. The grant is `signup_grant_credits`, an operator setting
            whose own comment calls its value a placeholder — a number printed
            here would be a promise the server can change without noticing. */}
        <p className="site-pricing-grant">
          {en
            ? "Signing up grants you credits to start with."
            : <><Clause>注册即赠送额度</Clause>，<Clause>可直接开始</Clause>。</>}
        </p>
      </div>
      <div className="site-pricing-body">
        {/* What actually spends 额度, in the order a 立言任务 spends it — the
            same three acts `/account` names, so a user reads the same list
            before signing up and after. 提炼主题 is deliberately absent: the
            homepage does not discuss how a 主题 arrives. */}
        <div className="site-spends">
          <h3>{en ? "What spends credits" : "消耗额度的操作"}</h3>
          <ul>
          {[
            { icon: FileStack, zh: "来源抓取", en: "Capturing a source" },
            { icon: FileSearch, zh: "知言报告生成", en: "Generating a ZhiYan report" },
            { icon: ScrollText, zh: "立言文章生成", en: "Generating a LiYan article" },
          ].map(({ icon: Icon, zh, en: label }) => (
            <li key={zh}>
              <Icon size={20} aria-hidden="true" />
              <span>{en ? label : zh}</span>
            </li>
          ))}
          </ul>
        </div>
        {/* The one number worth carrying away. It is the margin figure from
            `docs/operations/credits.md` — 400 = K × (1 − margin) — and every
            额度包 is sold at it, so quoting the rate says what the packs would
            have said without putting three prices on a page nobody has reached
            a decision on yet. */}
        <div className="site-rate">
          <strong>{en ? "US$1 = 400 credits" : "1 美元 = 400 额度"}</strong>
          <p>
            {en
              ? "Around three complete tasks: roughly 12 ZhiYan reports and 3 LiYan articles. A guide only — what you spend follows what you actually do."
              : "400 额度大约可完成 3 个完整的任务，约 12 篇知言报告和 3 篇立言文章。仅供参考，用量以实际情况为准。"}
          </p>
        </div>
      </div>
      {action}
    </section>
    <section id="faq" className="site-faq" aria-labelledby="faq-heading">
      <h2 id="faq-heading" className="site-section-title">{en ? "Frequently asked questions" : "常见问题"}</h2>
      {/* Four questions, and every answer is a fact this system enforces: the
          limits are `docs/operations/limits.md`, the 付费用户 boundary is what
          `has_purchased` decides, and the last two are 使用条款 3.1 in the
          words a visitor would use. Anything that moves there moves here. */}
      <div>
        {[
          {
            zhQ: "支持哪些来源？一个任务能放几个？",
            zhA: "粘贴文本、网页文字抓取，以及 Markdown、PDF、TXT、DOCX 上传。一个任务最多 3 个来源；上传单个文件不超过 10MB，PDF 不超过 100 页。",
            enQ: "What sources are supported, and how many can one task hold?",
            enA: "Pasted text, captured web page text, and Markdown, PDF, TXT and DOCX uploads. Up to three sources per task; an uploaded file may be up to 10MB, and a PDF up to 100 pages.",
          },
          {
            zhQ: "注册后能直接开始吗？",
            zhA: "可以。注册即赠送额度。网页文字抓取与文件上传在购买过额度后开启。",
            enQ: "Can I start straight after signing up?",
            enA: "Yes. Signing up grants you credits. Web page capture and file uploads open once you have bought credits.",
          },
          {
            zhQ: "额度是怎么扣的？",
            zhA: "按实际发生的工作量计算，来源越长、报告/文章越长，消耗越多。",
            enQ: "How are credits spent?",
            enA: "By the work actually done: the longer the source, and the longer the report or article, the more it spends.",
          },
          {
            zhQ: "失败的操作也会扣额度吗？",
            zhA: "不会。未产出任何结果的来源抓取、报告/文章生成不消耗额度。",
            enQ: "Do failed operations spend credits?",
            enA: "No. A source capture, report or article that produced nothing spends no credits.",
          },
        ].map(({ zhQ, zhA, enQ, enA }) => (
          <details key={zhQ}>
            <summary>{en ? enQ : zhQ}<ChevronDown size={18} aria-hidden="true" /></summary>
            <p>{en ? enA : zhA}</p>
          </details>
        ))}
      </div>
    </section>
    {/* The page's last line, and the couplet's own conclusion: 有感而发 is the
        lede's problem and 知言而立 is what the two verbs answer it with. The
        verbs are not marked here — the accent belongs to the hero, and
        spending it again at the foot of the page would make it decoration. */}
    <section className="site-closing">
      <h2>
        {en ? "Moved to speak: know the words, then write your own." : <><Clause>有感而发</Clause>，<Clause>知言而立</Clause></>}
      </h2>
      {action}
    </section>
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
        <Link to="/" className={`site-brand${en ? " site-brand--latin" : ""}`} aria-label={en ? "LiYan Studio home" : "立言阁首页"}><img src="/liyan-mark.svg" alt="" /><span>{en ? "LiYan Studio" : "立言阁"}</span></Link>
        <nav className="site-nav" aria-label={en ? "Page sections" : "页面目录"}>{[["workflow", en ? "How it works" : "使用流程"], ["pricing", en ? "Pricing" : "价格"], ["faq", en ? "FAQ" : "常见问题"]].map(([id, label]) => <Link key={id} to={`/#${id}`}>{label}</Link>)}</nav>
        <div className="site-controls">
          <button type="button" className="site-toggle" onClick={onLocaleChange} aria-label={`${en ? "Language" : "语言"}: ${en ? "English" : "中文"}`}><Languages size={18} aria-hidden="true" /><span>{en ? "EN" : "中文"}</span></button>
          <button type="button" className="site-toggle site-mode" onClick={onModeChange} aria-label={`${en ? "Mode" : "模式"}: ${modeLabel}`} title={modeLabel}>{mode === "light" ? <Sun size={18} aria-hidden="true" /> : mode === "dark" ? <MoonStar size={18} aria-hidden="true" /> : <MonitorCog size={18} aria-hidden="true" />}<span>{modeLabel}</span></button>
          {action}
        </div>
      </header>
    </div>
    {pathname === "/" ? <Homepage en={en} action={action} newcomer={!signedIn && !checking} /> : legal ? <main id="main-content" className="site-legal"><LegalDocument kind={pathname === "/terms" ? "terms" : "privacy"} en={en} /><Link className="site-text-link" to="/">{en ? "Back to home" : "返回首页"}<ArrowRight size={16} aria-hidden="true" /></Link></main> : <main id="main-content" className="site-auth">{children}</main>}
    <footer className={`site-footer${compactFooter ? " site-footer--compact" : ""}`}><div className="site-footer-brand"><div className={`site-brand${en ? " site-brand--latin" : ""}`}><img src="/liyan-mark.svg" alt="" /><span>{en ? "LiYan Studio" : "立言阁"}</span></div><p>{en ? "A product of Nyquiste Corporation" : "Nyquiste Corporation 旗下产品"}</p></div><div className="site-footer-bottom"><small>© {new Date().getFullYear()} Nyquiste Corporation</small><nav aria-label={en ? "Legal and contact" : "法律与联系"}><Link to="/terms">{en ? "Terms of Use" : "使用条款"}</Link><Link to="/privacy">{en ? "Privacy Policy" : "隐私政策"}</Link><a href="mailto:birdyyao@nyquiste.com">{en ? "Contact us" : "联系我们"}</a></nav></div></footer>
  </div>;
}
