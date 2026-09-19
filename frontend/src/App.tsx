import { FormEvent, useState } from "react";

import "./App.css";

type Status = "idle" | "loading" | "success" | "invalid" | "duplicate" | "server-error";

type Competitor = {
  offer_id: string;
  url: string;
};

export function getResponseStatus(responseOk: boolean, code?: string): Status {
  if (responseOk) return "success";
  if (code === "invalid_competitor_url") return "invalid";
  if (code === "competitor_already_exists") return "duplicate";
  return "server-error";
}

function App() {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [competitor, setCompetitor] = useState<Competitor | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setCompetitor(null);

    try {
      const response = await fetch("/api/competitors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, group_id: null }),
      });

      if (response.ok) {
        setCompetitor(await response.json());
        setUrl("");
        setStatus("success");
        return;
      }

      const body = (await response.json()) as { code?: string };
      setStatus(getResponseStatus(response.ok, body.code));
    } catch {
      setStatus("server-error");
    }
  }

  return (
    <main className="workbench-shell">
      <section className="competitor-card" aria-labelledby="page-title">
        <p className="eyebrow">竞品监控 / 添加竞品</p>
        <h1 id="page-title">添加 1688 竞品</h1>
        <p className="intro">登记商品链接后开始监控。当前只保存链接，不会立即访问商品详情页。</p>

        <form onSubmit={handleSubmit}>
          <label htmlFor="competitor-url">1688 商品链接</label>
          <input
            id="competitor-url"
            type="text"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://detail.1688.com/offer/123456789.html"
            required
          />
          <p className="hint">仅支持 detail.1688.com/offer/{"{offerId}"}.html</p>
          <button type="submit" disabled={status === "loading"}>
            {status === "loading" ? "正在添加…" : "添加竞品"}
          </button>
        </form>

        <div className={`feedback feedback-${status}`} role="status" aria-live="polite">
          {status === "loading" && "正在校验并保存…"}
          {status === "success" && competitor && (
            <>
              <strong>已添加竞品</strong>
              <span>offerId：{competitor.offer_id}</span>
              <span>标准化链接：{competitor.url}</span>
            </>
          )}
          {status === "invalid" && "链接无效：请输入指定格式的 1688 商品链接。"}
          {status === "duplicate" && "该 1688 商品已经添加。"}
          {status === "server-error" && "服务暂时不可用，请稍后重试。"}
        </div>
      </section>
    </main>
  );
}

export default App;
