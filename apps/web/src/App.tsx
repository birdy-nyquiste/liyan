import { useEffect, useState } from "react";

import { serverIsAlive } from "./api/client";
import "./styles.css";

type HealthState = "checking" | "available" | "unavailable";

export default function App() {
  const [health, setHealth] = useState<HealthState>("checking");

  useEffect(() => {
    let active = true;

    void serverIsAlive()
      .then((isAlive) => {
        if (active) setHealth(isAlive ? "available" : "unavailable");
      })
      .catch(() => {
        if (active) setHealth("unavailable");
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="shell">
      <header className="masthead">
        <p className="eyebrow">LIYAN WORKBENCH</p>
        <h1>立言阁</h1>
        <p className="subtitle">从来源到知言，再到由你定调的立言文章。</p>
      </header>

      <section className="workspace" aria-labelledby="workspace-heading">
        <div>
          <p className="section-kicker">本地工作台</p>
          <h2 id="workspace-heading">应用骨架已就绪</h2>
          <p>前端正通过 OpenAPI 生成的客户端连接服务端。</p>
        </div>

        <div
          className={`status status--${health}`}
          role="status"
          aria-live="polite"
        >
          <span className="status__dot" aria-hidden="true" />
          <span>
            {health === "checking" && "正在检查服务"}
            {health === "available" && "服务正常"}
            {health === "unavailable" && "服务暂不可用"}
          </span>
        </div>
      </section>
    </main>
  );
}
