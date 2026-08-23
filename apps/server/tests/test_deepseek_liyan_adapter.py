import json

import pytest

from liyan_server.liyan.acceptance import accept_article_text
from liyan_server.liyan.deepseek import (
    DeepSeekLiyanProvider,
    ProviderHttpResponse,
    request_body,
)
from liyan_server.liyan.failures import LiyanRunFailure
from liyan_server.liyan.prompt import liyan_request


def test_liyan_request_is_stateless_structured_and_has_no_tools() -> None:
    request = liyan_request(model="deepseek-v4-flash", input_text="approved context")
    body = request_body(request)

    assert body["store"] is False
    assert body["tools"] == []
    assert body["tool_choice"] == "none"
    assert body["text"] == {
        "format": {
            "type": "json_schema",
            "name": "liyan_article",
            "strict": True,
            "schema": request.article_schema,
        }
    }
    assert "previous_response_id" not in body


def test_provider_accepts_fenced_structured_output() -> None:
    provider = DeepSeekLiyanProvider(
        api_key="secret",
        post=lambda *_: ProviderHttpResponse(
            200,
            {
                "id": "resp-liyan",
                "status": "completed",
                "model": "deepseek-v4-flash",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "```json\n"
                                + json.dumps(
                                    {"title": "标题", "body_markdown": "完整正文。"},
                                    ensure_ascii=False,
                                )
                                + "\n```",
                            }
                        ],
                    }
                ],
            },
        ),
    )

    result = provider.generate(
        liyan_request(model="deepseek-v4-flash", input_text="approved context")
    )

    assert json.loads(result.article_text)["title"] == "标题"
    assert result.response_id == "resp-liyan"


@pytest.mark.parametrize(
    "body",
    [
        "根据知言报告 A 的 F-01，结论如下。",
        "<p>原始 HTML</p>",
        "|甲|乙|\n|---|---|\n|一|二|",
        "![图片](https://example.com/image.png)",
        "[不安全链接](javascript:alert(1))",
        "```python\nprint('code')\n```",
        "#### 不允许的四级标题",
        "不允许的一级标题\n================",
        "脚注内容[^1]\n\n[^1]: 说明",
        "- [ ] 发布清单",
        "---\nstatus: preview\nauthor: someone\n---\n正文",
        "postType: opinion\n\n正文",
        "<!-- 内部注释 -->\n\n正文",
        "术语\n: 定义",
        "date: 2026-08-22\n\n正文",
        "publish_at: 2026-08-22T12:00:00Z\n\n正文",
        "发布状态：草稿\n\n正文",
    ],
)
def test_acceptance_rejects_internal_traces_and_unsupported_markdown(body: str) -> None:
    with pytest.raises(LiyanRunFailure):
        accept_article_text(
            json.dumps({"title": "标题", "body_markdown": body}, ensure_ascii=False)
        )


def test_acceptance_does_not_override_the_users_editorial_claim() -> None:
    article = accept_article_text(
        json.dumps(
            {"title": "一项确定的判断", "body_markdown": "这项主张是确定事实。"},
            ensure_ascii=False,
        )
    )

    assert article.body_markdown == "这项主张是确定事实。"


@pytest.mark.parametrize(
    "title",
    [
        "<b>标题</b>",
        "![标题图](https://example.com/a.png)",
        "# 标题",
        "`标题`",
        "[标题](https://example.com)",
    ],
)
def test_acceptance_rejects_markup_in_the_title(title: str) -> None:
    with pytest.raises(LiyanRunFailure):
        accept_article_text(
            json.dumps({"title": title, "body_markdown": "完整正文。"}, ensure_ascii=False)
        )
