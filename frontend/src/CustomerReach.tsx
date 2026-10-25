import { FormEvent, useCallback, useEffect, useState } from "react";

import "./CustomerReach.css";

type Recipient = {
  recipient_id: string; customer_key: string; nickname: string; category: string; sequence: number;
  eligible: boolean; authorization_evidence: string | null; status: string; step: string;
  matched_customer: string | null; draft_verified: boolean | null; send_result: string | null;
  error_reason: string | null; processed_at: string | null;
};
type Campaign = {
  id: string; customer_category: "ordered" | "inquiry"; message_text: string; product_url: string;
  content_fingerprint: string; execution_mode: "simulated" | "desktop" | "desktop_preview"; status: string; step: string;
  recipients: Recipient[]; current_recipient_id: string | null; error_reason: string | null;
  created_at: string; started_at: string | null; finished_at: string | null;
};

const labels: Record<string, string> = {
  pending: "等待执行", locating: "定位客户", preparing: "准备草稿", awaiting_confirmation: "等待确认",
  sending: "发送中", success: "已完成", failed: "执行失败", unknown: "结果待核实",
  cancelled: "已取消", paused: "已暂停", skipped: "已跳过",
};
const categoryLabels = { ordered: "已成单客户", inquiry: "询盘客户" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/customer-reach${path}`, {
    ...init, headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body?.message || body?.detail?.message || "请求失败");
  return body as T;
}

export function CustomerReachPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [category, setCategory] = useState<"ordered" | "inquiry">("ordered");
  const [message, setMessage] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"simulated" | "desktop">("simulated");
  const current = campaigns.find((campaign) => campaign.id === selected) ?? campaigns[0] ?? null;
  const recipient = current?.recipients.find((row) => row.recipient_id === current.current_recipient_id) ?? null;

  const refresh = useCallback(async () => {
    try {
      const executor = await request<{ mode: "simulated" | "desktop" }>("/mode");
      setMode(executor.mode);
      const next = await request<Campaign[]>("/campaigns");
      setCampaigns(next);
      setSelected((value) => value ?? next[0]?.id ?? null);
    } catch (err) { setError(err instanceof Error ? err.message : "无法读取任务"); }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const campaign = await request<Campaign>("/campaigns", {
        method: "POST", body: JSON.stringify({ customer_category: category, message_text: message, product_url: url }),
      });
      setSelected(campaign.id); setMessage(""); setUrl(""); await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "创建失败"); }
    finally { setBusy(false); }
  }

  async function preview() {
    setBusy(true); setError("");
    try {
      const campaign = await request<Campaign>("/campaigns", {
        method: "POST", body: JSON.stringify({ customer_category: "ordered", message_text: "非发送验收", preview_only: true }),
      });
      setSelected(campaign.id); await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "创建失败"); }
    finally { setBusy(false); }
  }

  async function act(action: "confirm" | "pause" | "cancel" | "resume" | "skip-current") {
    if (!current) return;
    setBusy(true); setError("");
    try {
      const path = `/campaigns/${current.id}/${action}`;
      const body = (action === "confirm" || action === "skip-current") && recipient ? {
        campaign_id: current.id, recipient_id: recipient.recipient_id, customer_key: recipient.customer_key,
        content_fingerprint: current.content_fingerprint,
      } : undefined;
      await request<Campaign>(path, { method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : "操作失败"); }
    finally { setBusy(false); }
  }

  return <div className="customer-reach-page">
    <header className="page-header"><div><h1>客户触达</h1><p className="page-description">按客户列表顺序处理；每位客户单独核验和确认发送。</p></div></header>
    {mode === "simulated"
      ? <p className="reach-mode-note">当前为模拟执行模式：演练队列状态和逐客户确认，不操作 1688 或发送消息。</p>
      : <p className="reach-mode-note reach-mode-warning">桌面执行只纳入列表中同时具备稳定登录标识和明确营销授权标记的客户。</p>}
    <div className="reach-layout">
      <section className="reach-compose" aria-labelledby="reach-compose-title">
        <h2 id="reach-compose-title">创建推广任务</h2>
        {mode === "desktop" && <button className="secondary-button" disabled={busy} onClick={() => void preview()}>首位客户非发送验收</button>}
        <form onSubmit={(event) => void submit(event)}>
          <label>客户分类<select value={category} onChange={(event) => setCategory(event.target.value as "ordered" | "inquiry")}><option value="ordered">已成单客户</option><option value="inquiry">询盘客户</option></select></label>
          <label>新品推广文案<textarea required maxLength={10000} rows={6} value={message} onChange={(event) => setMessage(event.target.value)} placeholder="输入需要发送的完整文案" /></label>
          <label>商品链接<input required type="url" maxLength={2048} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://detail.1688.com/offer/..." /></label>
          <button className="primary-button" disabled={busy || !message.trim() || !url.trim()} type="submit">创建并开始</button>
        </form>
        <p className="reach-safety-note">没有明确授权的客户会跳过；每位客户都需单独确认。结果不确定时停止队列且不会重发。</p>
      </section>
      <section className="reach-records" aria-labelledby="reach-records-title">
        <div className="reach-section-heading"><h2 id="reach-records-title">推广任务</h2><span>{campaigns.length} 条</span></div>
        {campaigns.length === 0 ? <p className="reach-empty">还没有推广任务。</p> : <ul className="reach-task-list">{campaigns.map((campaign) => <li key={campaign.id}><button type="button" aria-current={campaign.id === current?.id ? "true" : undefined} onClick={() => setSelected(campaign.id)}><span><strong>{categoryLabels[campaign.customer_category]}</strong><small>{new Date(campaign.created_at).toLocaleString()}</small></span><span className={`reach-status reach-status-${campaign.status}`}>{labels[campaign.status] ?? campaign.status}</span></button></li>)}</ul>}
      </section>
    </div>
    {current && <section className="reach-detail" aria-labelledby="reach-detail-title">
      <div className="reach-section-heading"><div><h2 id="reach-detail-title">当前推广任务</h2><p>{current.step}</p></div><span className={`reach-status reach-status-${current.status}`}>{labels[current.status] ?? current.status}</span></div>
      <dl className="reach-facts">
        <div><dt>任务 ID</dt><dd>{current.id}</dd></div>
        <div><dt>客户分类</dt><dd>{categoryLabels[current.customer_category]}</dd></div>
        <div><dt>队列进度</dt><dd>{current.recipients.filter((row) => ["success", "failed", "unknown", "skipped"].includes(row.status)).length} / {current.recipients.length}</dd></div>
        <div><dt>执行模式</dt><dd>{current.execution_mode === "simulated" ? "模拟" : current.execution_mode === "desktop_preview" ? "Windows 桌面（非发送验收）" : "Windows 桌面"}</dd></div>
      </dl>
      {current.recipients.length > 0 && <div className="reach-records"><h3>客户处理顺序</h3><ul className="reach-task-list">{current.recipients.map((row) => <li key={row.recipient_id}><div className="reach-recipient-row"><span><strong>{row.sequence}. {row.nickname}</strong><small>{row.authorization_evidence ? `触达依据：${row.authorization_evidence}` : row.error_reason ?? (current.execution_mode === "desktop_preview" ? "仅非发送验收，不代表营销授权" : "无明确营销授权，已跳过")}</small></span><span className={`reach-status reach-status-${row.status}`}>{labels[row.status] ?? row.status}</span></div></li>)}</ul></div>}
      {recipient && <div className="reach-preview"><h3>{current.execution_mode === "desktop_preview" ? "非发送草稿核验" : "发送前核对"}</h3><p><strong>识别客户：</strong>{recipient.matched_customer ?? recipient.nickname}</p><p><strong>分类：</strong>{categoryLabels[current.customer_category]}</p><p><strong>授权：</strong>{recipient.authorization_evidence}</p><p><strong>草稿核验：</strong>{recipient.draft_verified ? "通过" : "未通过"}</p><p>{current.message_text}</p>{current.product_url && <a href={current.product_url} target="_blank" rel="noreferrer">{current.product_url}</a>}</div>}
      {current.error_reason && <p className="reach-error" role="alert">{current.error_reason}</p>}
      <div className="reach-actions">
        {current.status === "awaiting_confirmation" && recipient && <>{current.execution_mode !== "desktop_preview" && <button className="primary-button" disabled={busy || recipient.matched_customer !== recipient.nickname || recipient.draft_verified !== true} onClick={() => void act("confirm")}>确认向此客户发送一次</button>}<button className="secondary-button" disabled={busy} onClick={() => void act("skip-current")}>跳过此客户</button><button className="secondary-button" disabled={busy} onClick={() => void act("pause")}>暂停</button><button className="secondary-button" disabled={busy} onClick={() => void act("cancel")}>取消任务</button></>}
        {["pending", "locating", "preparing"].includes(current.status) && <><button className="secondary-button" disabled={busy} onClick={() => void act("pause")}>暂停</button><button className="secondary-button" disabled={busy} onClick={() => void act("cancel")}>取消</button></>}
        {current.status === "paused" && <><button className="secondary-button" disabled={busy} onClick={() => void act("resume")}>继续</button><button className="secondary-button" disabled={busy} onClick={() => void act("cancel")}>取消</button></>}
        {current.status === "success" && <p>{current.execution_mode === "simulated" ? "模拟完成：未向客户发送消息" : "队列处理完成，结果按客户记录保存"}</p>}
        {current.status === "unknown" && <p>请先核对当前客户的聊天记录；系统不会自动重发或继续队列。</p>}
      </div>
      <div className="reach-runtime"><h3>运行时截图</h3><img src={`/api/customer-reach/campaigns/${current.id}/screenshot`} alt="当前桌面执行步骤截图" onError={(event) => { event.currentTarget.hidden = true; }} /><p>截图仅供核对当前客户和可见草稿；模拟执行器不会产生桌面截图。</p></div>
    </section>}
    {error && <p className="reach-error" role="alert">{error}</p>}
  </div>;
}
