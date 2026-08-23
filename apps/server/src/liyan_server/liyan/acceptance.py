import json
import re

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from liyan_server.liyan.failures import LiyanRunFailure

UNUSABLE_MESSAGE = "立言服务返回了无法使用的文章，请重试。"

_RAW_HTML = re.compile(r"<!--[\s\S]*?-->|</?[A-Za-z][^>]*>|<![A-Z][^>]*>|<\?[^>]*>", re.I)
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", re.M)
_INTERNAL_REFERENCE = re.compile(
    r"(?:来源\s*[A-ZＡ-Ｚ]|知言报告|REF-\d+|(?<![A-Za-z])[FVLI]-\d+)", re.I
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


def accept_article_text(article_text: str) -> GeneratedArticle:
    try:
        article = GeneratedArticle.model_validate(json.loads(article_text))
    except (json.JSONDecodeError, ValidationError) as error:
        raise LiyanRunFailure("invalid_article_schema", UNUSABLE_MESSAGE, str(error)) from error
    body = article.body_markdown
    forbidden = (
        _RAW_HTML.search(article.title)
        or _RAW_HTML.search(body)
        or _TABLE_DIVIDER.search(body)
        or _IMAGE.search(article.title)
        or _IMAGE.search(body)
        or _CODE.search(body)
        or _UNSUPPORTED_HEADING.search(body)
        or _SETEXT_H1.search(body)
        or _FOOTNOTE.search(body)
        or _TASK_LIST.search(body)
        or _DEFINITION_LIST.search(body)
        or _INDENTED_CODE.search(body)
        or _LINK_DEFINITION.search(body)
        or _TITLE_MARKDOWN.search(article.title)
        or "~~" in body
        or _PUBLICATION_FIELD.search(body)
        or _YAML_FRONTMATTER.search(body)
        or _UNSAFE_LINK.search(body)
        or "\n" in article.title
    )
    if forbidden:
        raise LiyanRunFailure(
            "unsupported_article_markdown",
            UNUSABLE_MESSAGE,
            "The article contains a forbidden Markdown construct.",
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
