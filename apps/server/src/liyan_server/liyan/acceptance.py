import json
import re

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from liyan_server.liyan.failures import LiyanRunFailure

UNUSABLE_MESSAGE = "立言服务返回了无法使用的文章，请重试。"

_RAW_HTML = re.compile(r"<!--[\s\S]*?-->|</?[A-Za-z][^>]*>|<![A-Z][^>]*>|<\?[^>]*>", re.I)
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M)
_INTERNAL_REFERENCE = re.compile(
    r"(?:来源\s*[A-ZＡ-Ｚ]|知言报告|REF-?\d+|CAPSULE\s*[:#-]?\s*\d+|胶囊\s*\d+|"
    r"(?<![A-Za-z])[EFVLI]-\d+)",
    re.I,
)
_GENERATION_NARRATION = re.compile(r"(?:根据提供的?材料|作为\s*AI|立言指令|系统\s*Prompt)", re.I)
_UNSAFE_LINK = re.compile(r"(?<!!)\[[^\]]+\]\((?!https?://)[^)]+\)", re.I)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_CODE = re.compile(r"```|~~~|`[^`]+`")
_UNSUPPORTED_HEADING = re.compile(r"^(?:#\s+|#{4,}\s+)", re.M)
_SETEXT_H1 = re.compile(r"^.+\n\s*=+\s*$", re.M)
_FOOTNOTE = re.compile(r"\[\^[^\]]+\]|^\[\^[^\]]+\]:", re.M)
_TASK_LIST = re.compile(r"^\s*[-+*]\s+\[[ xX]\]\s+", re.M)
_DEFINITION_LIST = re.compile(r"^\s{0,3}:\s+\S", re.M)
_INDENTED_CODE = re.compile(r"^(?: {4}|\t)\S", re.M)
_LINK_DEFINITION = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S", re.M)
_TITLE_MARKDOWN = re.compile(
    r"(?:^\s*(?:#{1,6}|>|[-+*]|\d+[.)])\s+|[*_~`]|!?\[[^\]]*\]\([^)]+\)|"
    r"<!--[\s\S]*?-->|</?[A-Za-z][^>]*>)",
    re.I,
)
_PUBLICATION_FIELD = re.compile(
    r"^\s*(?:status|postType|author|slug|category|categories|tags|featured|cover|excerpt|"
    r"date|publish(?:ed)?(?:_at|At)?|publication|visibility|文章类型|作者|分类|标签|封面|摘要|"
    r"发布状态|发布日期|发布时间|可见性)\s*[:：]",
    re.I | re.M,
)
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
    ("indented code", _INDENTED_CODE),
    ("a link definition", _LINK_DEFINITION),
    ("publication front matter", _PUBLICATION_FIELD),
    ("YAML front matter", _YAML_FRONTMATTER),
    ("a link that is not https", _UNSAFE_LINK),
)


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
    if "~~" in body:
        return "strikethrough"
    if "\n" in title:
        return "a line break in the title"
    return None


def unsupported_article_markdown(title: str, body: str) -> bool:
    """Whether the pair leaves the canonical Markdown subset both sides may store."""
    return unsupported_markdown_reason(title, body) is not None


def accept_article_text(article_text: str) -> GeneratedArticle:
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
    if _GENERATION_NARRATION.search(article.title) or _GENERATION_NARRATION.search(body):
        raise LiyanRunFailure(
            "article_generation_narration",
            UNUSABLE_MESSAGE,
            "The article narrates its generation context.",
        )
    return article
