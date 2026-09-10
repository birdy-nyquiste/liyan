import json
import re
from collections.abc import Collection

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from liyan_server.liyan.failures import LiyanRunFailure

UNUSABLE_MESSAGE = "立言服务返回了无法使用的文章，请重试。"

#: What may sit inside a tag after its name: printable ASCII without angle
#: brackets. The old rule let a tag's insides be anything at all, so 「产能 n<k
#: 时，边际成本 c>0」 read as one — an article could not state an inequality.
_TAG_ATTRIBUTES = r"[ !-;=?-~]"

_RAW_HTML = re.compile(
    r"<!--[\s\S]*?-->"
    r"|<!\s*[A-Za-z][^<>]*>"
    r"|<\?[\s\S]*?\?>"
    r"|</\s*[A-Za-z][A-Za-z0-9-]*\s*>"
    rf"|<[A-Za-z][A-Za-z0-9-]*(?:\s+{_TAG_ATTRIBUTES}*?)?\s*/?>",
    re.I,
)
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M)
#: The internal names an article must never carry. 来源 X is a label only when
#: the letter stands alone: 「数据来源 Wind」 and 「信息来源 BBC」 are ordinary
#: attributions. Item identifiers are not here at all — a pattern like
#: `[EFVLI]-\d+` refuses F-16, L-4 and I-95 along with F-01, so which ones this
#: run may not use is answered by `context_identifiers` instead.
_INTERNAL_REFERENCE = re.compile(
    r"(?:来源\s*[A-ZＡ-Ｚ](?![A-Za-zＡ-Ｚａ-ｚ])|知言报告|REF-?\d+|"
    r"CAPSULE\s*[:#-]?\s*\d+|胶囊\s*\d+)",
    re.I,
)
#: Only the tells that cannot be anything else. 「作为AI行业的从业者」,
#: 「根据提供的材料，法院认定…」 and an article discussing 系统 Prompt are all
#: ordinary sentences, and discarding a whole generation over one of them costs
#: far more than the awkward phrase it prevents.
_GENERATION_NARRATION = re.compile(
    r"(?:作为(?:一个|一名)?\s*(?:AI|人工智能)(?:\s*(?:助手|模型|语言模型|程序))?\s*[，,：:]"
    r"|立言指令)",
    re.I,
)
_UNSAFE_LINK = re.compile(r"(?<!!)\[[^\]]+\]\((?!https?://)[^)]+\)", re.I)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_CODE = re.compile(r"```|~~~|`[^`]+`")
_UNSUPPORTED_HEADING = re.compile(r"^(?:#\s+|#{4,}\s+)", re.M)
_SETEXT_H1 = re.compile(r"^.+\n\s*=+\s*$", re.M)
_FOOTNOTE = re.compile(r"\[\^[^\]]+\]|^\[\^[^\]]+\]:", re.M)
_TASK_LIST = re.compile(r"^\s*[-+*]\s+\[[ xX]\]\s+", re.M)
_DEFINITION_LIST = re.compile(r"^\s{0,3}:\s+\S", re.M)
_LIST_ITEM = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])(?:\s|$)")
_INDENTED_LINE = re.compile(r"^(?: {4}|\t)\S")
_LINK_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S", re.M)
_TITLE_MARKDOWN = re.compile(
    r"(?:^\s*(?:#{1,6}|>|[-+*]|\d+[.)])\s+|[*_~`]|!?\[[^\]]*\]\([^)]+\))",
    re.I,
)
_PUBLICATION_FIELD = re.compile(
    r"^\s*(?:status|postType|author|slug|category|categories|tags|featured|cover|excerpt|"
    r"date|publish(?:ed)?(?:_at|At)?|publication|visibility|文章类型|作者|分类|标签|封面|摘要|"
    r"发布状态|发布日期|发布时间|可见性)\s*[:：]\s*(?P<value>.*)$",
    re.I,
)
_SENTENCE_END = re.compile(r"[。！？!?]")
_YAML_FRONTMATTER = re.compile(
    r"\A---\s*\n(?=[\s\S]*?^\w[\w-]*\s*:)[\s\S]*?\n---\s*(?:\n|\Z)",
    re.M,
)


class GeneratedArticle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body_markdown: str

    @field_validator("title", "body_markdown")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Article fields must not be empty.")
        return value.strip()


#: Each rule with the name it is known by, so a rejection can say which one it
#: was. "A forbidden Markdown construct" is true of every article this refuses
#: and tells whoever reads it nothing — not which rule, and not whether the
#: model is close to acceptable or nowhere near it.
_TITLE_RULES: tuple[tuple[str, object], ...] = (
    ("raw HTML in the title", _RAW_HTML),
    ("an image in the title", _IMAGE),
    ("Markdown in the title", _TITLE_MARKDOWN),
)

_BODY_RULES: tuple[tuple[str, object], ...] = (
    ("raw HTML", _RAW_HTML),
    ("a table", _TABLE_DIVIDER),
    ("an image", _IMAGE),
    ("a code span or fence", _CODE),
    ("an H1 or an H4 and deeper", _UNSUPPORTED_HEADING),
    ("a setext H1", _SETEXT_H1),
    ("a footnote", _FOOTNOTE),
    ("a task list", _TASK_LIST),
    ("a definition list", _DEFINITION_LIST),
    ("a link definition", _LINK_DEFINITION),
    ("YAML front matter", _YAML_FRONTMATTER),
    ("a link that is not https", _UNSAFE_LINK),
)


#: What one 知言 item identifier looks like, in either report: `F-01` from a
#: 来源 report, `TB-03` from a 主题 one.
_ITEM_IDENTIFIER = re.compile(r"^T?[EFVLI]-\d{2,}$")

_SOURCES_AND_REPORTS = re.compile(
    r"<CURRENT_SOURCES_AND_REPORTS>\n(?P<payload>.*?)\n</CURRENT_SOURCES_AND_REPORTS>",
    re.S,
)


def context_identifiers(input_text: str) -> frozenset[str]:
    """The 知言 identifiers this run was actually shown.

    Which strings an article must not carry is a fact about the run, not a
    shape: this context holds F-01 and F-02, so those two are forbidden and
    F-16 is a fighter jet. Read from the reports' own `id` fields rather than
    from the whole block, so a 来源 that happens to mention L-4 does not make
    an article about spinal discs unwritable.
    """
    block = _SOURCES_AND_REPORTS.search(input_text)
    if block is None:
        return frozenset()
    try:
        payload = json.loads(block.group("payload"))
    except ValueError:
        return frozenset()
    found: set[str] = set()
    _collect_identifiers(payload, found)
    return frozenset(found)


def _collect_identifiers(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        identifier = node.get("id")
        if isinstance(identifier, str) and _ITEM_IDENTIFIER.match(identifier):
            found.add(identifier)
        for value in node.values():
            _collect_identifiers(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_identifiers(value, found)


def _cited_identifier(text: str, identifiers: Collection[str]) -> str | None:
    """The first context identifier the text quotes verbatim, if any."""
    for identifier in identifiers:
        pattern = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(identifier)}(?![0-9])")
        if pattern.search(text):
            return identifier
    return None


def _has_indented_code(body: str) -> bool:
    """Whether a four-space indent here is code rather than list content.

    Nested items and continuation lines inside a list are indented too, and the
    subset allows lists — so a line-level rule refused most of the lists it was
    written to permit. An indent is only code where no list is open.
    """
    list_open = False
    for line in body.splitlines():
        if not line.strip():
            continue
        if _LIST_ITEM.match(line):
            list_open = True
        elif _INDENTED_LINE.match(line):
            if not list_open:
                return True
        else:
            list_open = False
    return False


def _has_publication_front_matter(body: str) -> bool:
    """Whether the article opens with metadata instead of prose.

    Front matter is a position, not a punctuation mark: 「作者：张三」 under a
    pulled quote and 「摘要：本文讨论……。」 as an opening sentence are ordinary
    writing. What is not is a short `key: value` line where the article should
    have started.
    """
    for line in body.splitlines():
        if not line.strip():
            return False
        match = _PUBLICATION_FIELD.match(line)
        if match is None:
            return False
        value = match.group("value").strip()
        return len(value) <= 60 and not _SENTENCE_END.search(value)
    return False


def unsupported_markdown_reason(title: str, body: str) -> str | None:
    """Which rule the pair breaks, or None if it breaks none.

    Named rather than counted: the model is asked for a narrow Markdown subset,
    and knowing it reached for a table is the difference between adjusting a
    prompt and guessing at one.
    """
    for reason, rule in _TITLE_RULES:
        if rule.search(title):  # type: ignore[attr-defined]
            return reason
    for reason, rule in _BODY_RULES:
        if rule.search(body):  # type: ignore[attr-defined]
            return reason
    if _has_indented_code(body):
        return "indented code"
    if _has_publication_front_matter(body):
        return "publication front matter"
    if "~~" in body:
        return "strikethrough"
    if "\n" in title:
        return "a line break in the title"
    return None


def unsupported_article_markdown(title: str, body: str) -> bool:
    """Whether the pair leaves the canonical Markdown subset both sides may store."""
    return unsupported_markdown_reason(title, body) is not None


def accept_article_text(
    article_text: str,
    *,
    context_identifiers: Collection[str] = (),
) -> GeneratedArticle:
    try:
        article = GeneratedArticle.model_validate(json.loads(article_text))
    except (json.JSONDecodeError, ValidationError) as error:
        raise LiyanRunFailure("invalid_article_schema", UNUSABLE_MESSAGE, str(error)) from error
    body = article.body_markdown
    if reason := unsupported_markdown_reason(article.title, body):
        raise LiyanRunFailure(
            "unsupported_article_markdown",
            UNUSABLE_MESSAGE,
            f"The article uses {reason}, which the canonical subset forbids.",
        )
    if _INTERNAL_REFERENCE.search(article.title) or _INTERNAL_REFERENCE.search(body):
        raise LiyanRunFailure(
            "internal_article_reference",
            UNUSABLE_MESSAGE,
            "The article exposes an internal source or report identifier.",
        )
    quoted = _cited_identifier(article.title, context_identifiers) or _cited_identifier(
        body, context_identifiers
    )
    if quoted is not None:
        raise LiyanRunFailure(
            "internal_article_reference",
            UNUSABLE_MESSAGE,
            f"The article quotes {quoted}, an identifier from its own 知言 context.",
        )
    if _GENERATION_NARRATION.search(article.title) or _GENERATION_NARRATION.search(body):
        raise LiyanRunFailure(
            "article_generation_narration",
            UNUSABLE_MESSAGE,
            "The article narrates its generation context.",
        )
    return article
