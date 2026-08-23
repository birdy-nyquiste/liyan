import { describe, expect, it } from "vitest";

import { articleContentHash } from "./articleContentHash";

describe("articleContentHash", () => {
  it("matches the server hash of the same canonical title and body", async () => {
    // The expected value comes from the server helper:
    // sha256(json.dumps({"body_markdown": ..., "title": ...}, ensure_ascii=False,
    //                   sort_keys=True, separators=(",", ":")))
    const hash = await articleContentHash({
      title: "四天工作制的真问题",
      body_markdown: "工时只是生产方式的一部分。\n\n## 现实条件\n\n改变流程比压缩时间更重要。",
    });

    expect(hash).toBe(
      "7c6a31fa67733ea7bcf5db13af66658a996e3966751b3e7f3e412c0e8f016fc7",
    );
  });

  it("ignores surrounding whitespace the server strips before saving", async () => {
    const padded = await articleContentHash({ title: " 标题 ", body_markdown: "正文。\n" });
    const exact = await articleContentHash({ title: "标题", body_markdown: "正文。" });

    expect(padded).toBe(exact);
  });
});
