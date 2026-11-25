import React, { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import NewTicket from './NewTicket.jsx';
import TicketHistory from './TicketHistory.jsx';
import { displayDate, ErrorMessage, Icon } from './ui.jsx';

const statusLabels = { open: 'Open', draft: 'In review', approved: 'Approved' };
const statusFilters = { all: 'All', ...statusLabels };
const factValues = {
  plan: { monthly: 'Monthly', annual: 'Annual' },
  reason: { refund: 'Refund', cancel: 'Cancellation', duplicate_charge: 'Duplicate charge' },
};

const decisionLabels = {
  eligible_review: 'Eligible for review',
  not_eligible: 'Outside refund policy',
  needs_information: 'More information needed',
  manual_review: 'Manual review required',
};
const fieldLabels = {
  plan: 'Plan',
  charged_on: 'Charge date',
  requested_on: 'Request date',
  usage_count: 'Usage count',
  reason: 'Request type',
};
const approvalNote = 'Reviewed against the cited demo policy. Approval records this draft only.';

function Badge({ status }) {
  return <span className={`badge badge-${status}`}>{statusLabels[status] || status}</span>;
}
function Empty({ icon = 'inbox', title, children }) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon name={icon} size={28} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

export default function App() {
  const [tickets, setTickets] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState('');
  const [actionError, setActionError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState('');
  const [draftBody, setDraftBody] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState(approvalNote);
  const [tab, setTab] = useState('draft');
  const draft = detail?.drafts?.[0];
  const dirty = Boolean(
    draft &&
    !draft.review &&
    (draftBody !== draft.body || note !== approvalNote || reviewer.trim() !== ''),
  );
  const latestRequest = useRef(0);

  async function loadWorkspace(initial = false) {
    if (initial) setLoading(true);
    setGlobalError('');
    try {
      const [items, documents, counts] = await Promise.all([
        api('/tickets'),
        api('/policies'),
        api('/stats'),
      ]);
      setTickets(items);
      setPolicies(documents);
      setStats(counts);
      if (initial) setSelectedId(items[0]?.id || null);
    } catch (e) {
      setGlobalError(e.message);
    } finally {
      setLoading(false);
    }
  }
  function acceptDetail(result) {
    setDetail(result);
    setDraftBody(result.drafts?.[0]?.body || '');
    setNote(approvalNote);
    setReviewer('');
    setConflict(false);
  }
  async function loadDetail(id) {
    const request = ++latestRequest.current;
    setDetailLoading(true);
    setActionError('');
    setNotice('');
    try {
      const result = await api(`/tickets/${encodeURIComponent(id)}`);
      if (request === latestRequest.current) acceptDetail(result);
    } catch (e) {
      if (request === latestRequest.current) {
        setDetail(null);
        setActionError(e.message);
      }
    } finally {
      if (request === latestRequest.current) setDetailLoading(false);
    }
  }
  useEffect(() => {
    loadWorkspace(true);
  }, []);
  useEffect(() => {
    if (selectedId) loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId]);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', prevent);
    return () => window.removeEventListener('beforeunload', prevent);
  }, [dirty]);
  function mayDiscard() {
    return !dirty || window.confirm('Discard the unsaved changes to this draft?');
  }
  function selectTicket(id) {
    if (id === selectedId || busy || !mayDiscard()) return;
    setSelectedId(id);
    setTab('draft');
    setReviewer('');
  }
  async function generate(mode) {
    if (!detail || !mayDiscard()) return;
    setBusy(mode);
    setActionError('');
    setNotice('');
    try {
      const result = await api(`/tickets/${encodeURIComponent(detail.id)}/drafts`, {
        mode,
        expected_revision: detail.revision,
      });
      acceptDetail(result);
      setTab('draft');
      setNotice(
        mode === 'ai'
          ? 'Local AI draft saved. Review every statement before approving.'
          : 'Template draft saved. Review and edit it below.',
      );
      await loadWorkspace();
    } catch (e) {
      setActionError(e.message);
      setConflict(e.status === 409);
    } finally {
      setBusy('');
    }
  }
  async function review(action) {
    if (!detail || !draft) return;
    if (!draftBody.trim() || !reviewer.trim() || !note.trim()) {
      setActionError('Add the draft text, reviewer name, and review note before continuing.');
      return;
    }
    if (action === 'reject' && note.trim() === approvalNote) {
      setActionError('Replace the approval note with the reason for rejecting this draft.');
      document.getElementById('review-note')?.focus();
      return;
    }
    setBusy(action);
    setActionError('');
    setNotice('');
    try {
      const result = await api(`/tickets/${encodeURIComponent(detail.id)}/review`, {
        draft_id: draft.id,
        expected_revision: detail.revision,
        action,
        body: draftBody.trim(),
        note: note.trim(),
        reviewer: reviewer.trim(),
      });
      acceptDetail(result);
      setNotice(
        action === 'approve'
          ? 'Draft approved and saved locally. Nothing was sent and no refund was issued.'
          : 'Draft rejected. The ticket is open for a new draft.',
      );
      await loadWorkspace();
    } catch (e) {
      setActionError(e.message);
      setConflict(e.status === 409);
    } finally {
      setBusy('');
    }
  }
  const filtered = tickets.filter(
    (ticket) =>
      (filter === 'all' || ticket.status === filter) &&
      `${ticket.customer} ${ticket.title} ${ticket.id} ${ticket.body}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const citationIds = new Set([...(detail?.assessment?.citations || []), ...(draft?.citations || [])]);
  const pending = draft && !draft.review && detail?.status !== 'approved';

  return (
    <div className="app-shell">
      <aside className="brand-rail" aria-label="Workspace">
        <a className="brand-mark" href="#main" aria-label="Relay workspace">
          <span />
          <span />
          <span />
        </a>
        <div className="rail-active" title="Support inbox">
          <Icon name="inbox" size={22} />
        </div>
        <div className="rail-bottom">
          <Icon name="shield" size={20} />
          <span>LOCAL</span>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="wordmark">
            relay<span className="wordmark-dot">.</span>
            <span className="wordmark-divider" />
            <span className="workspace-label">Support workspace</span>
          </div>
          <div className="environment">
            <span className="environment-dot" />
            Local only
            <span className="env-separator" />
            Synthetic demo
          </div>
        </header>
        <main id="main">
          <section className="page-heading">
            <div>
              <h1>Ticket review</h1>
            </div>
            <button
              className="button primary"
              onClick={() => {
                if (mayDiscard()) setCreating(true);
              }}
              disabled={Boolean(busy)}
            >
              <Icon name="plus" size={17} />
              New ticket
            </button>
          </section>
          <section className="queue-summary" aria-label="Queue overview">
            <div className="summary-title">
              <span className="live-dot" />
              Your local queue
            </div>
            <div className="summary-values">
              {Object.entries(statusLabels).map(([key, label]) => (
                <div key={key}>
                  <strong>{stats ? stats[key] : '—'}</strong>
                  <span>{label}</span>
                </div>
              ))}
            </div>
            <span className="summary-caption">
              <Icon name="shield" size={15} />
              Nothing is sent
            </span>
          </section>
          {globalError && (
            <div className="global-error">
              <ErrorMessage error={globalError} />
              <button className="button secondary" onClick={() => loadWorkspace(!selectedId)}>
                Retry connection
              </button>
            </div>
          )}
          <div className="workspace-grid">
            <aside className="queue-panel" aria-label="Ticket queue">
              <div className="queue-header">
                <h2>
                  Inbox <span className="count-pill">{stats?.total ?? '—'}</span>
                </h2>
                <button
                  type="button"
                  className="icon-button"
                  title="Refresh queue"
                  aria-label="Refresh queue"
                  onClick={() => loadWorkspace()}
                  disabled={loading || Boolean(busy)}
                >
                  <Icon name="refresh" size={16} />
                </button>
              </div>
              <label className="search-box">
                <Icon name="search" size={17} />
                <input
                  aria-label="Search tickets"
                  type="search"
                  placeholder="Search tickets…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <div className="status-tabs" aria-label="Filter tickets">
                {Object.entries(statusFilters).map(([value, label]) => (
                  <button
                    key={value}
                    aria-pressed={filter === value}
                    className={filter === value ? 'active' : ''}
                    onClick={() => setFilter(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="ticket-list" aria-busy={loading}>
                {loading ? (
                  <div className="loading-block">
                    <span className="spinner" />
                    Loading your queue…
                  </div>
                ) : filtered.length === 0 ? (
                  <Empty title={tickets.length ? 'No matching tickets' : 'No tickets'}>
                    {tickets.length
                      ? 'Try a different search or status filter.'
                      : 'Create a synthetic ticket to start a review.'}
                  </Empty>
                ) : (
                  filtered.map((ticket) => (
                    <button
                      className={`ticket-item ${selectedId === ticket.id ? 'selected' : ''}`}
                      key={ticket.id}
                      onClick={() => selectTicket(ticket.id)}
                      disabled={Boolean(busy)}
                      aria-current={selectedId === ticket.id ? 'true' : undefined}
                    >
                      <span className="ticket-row">
                        <span className="ticket-customer">{ticket.customer}</span>
                        <time dateTime={ticket.created_at}>{displayDate(ticket.created_at)}</time>
                      </span>
                      <strong className="ticket-subject">{ticket.title}</strong>
                      <span className="ticket-preview">{ticket.body}</span>
                      <span className="ticket-row ticket-bottom">
                        <Badge status={ticket.status} />
                        <span className="ticket-short-id">
                          {ticket.id.length > 15 ? ticket.id.slice(0, 8) : ticket.id}
                        </span>
                      </span>
                    </button>
                  ))
                )}
              </div>
            </aside>

            <section className="workbench" aria-label="Ticket workbench" aria-busy={detailLoading}>
              {detailLoading ? (
                <div className="loading-block detail-loader">
                  <span className="spinner" />
                  Opening ticket…
                </div>
              ) : !detail ? (
                <>
                  <ErrorMessage error={actionError} />
                  <Empty title="Pick a ticket to begin">
                    Your customer message, draft, and review history will appear here.
                  </Empty>
                </>
              ) : (
                <>
                  <header className="ticket-heading">
                    <div className="ticket-heading-meta">
                      <span className="eyebrow">
                        TICKET <span>{detail.id.length > 15 ? detail.id.slice(0, 8) : detail.id}</span>
                      </span>
                      <Badge status={detail.status} />
                    </div>
                    <h2>{detail.title}</h2>
                    <div className="sender-line">
                      <span className="avatar">{detail.customer.charAt(0).toUpperCase()}</span>
                      <span>
                        <strong>{detail.customer}</strong>
                        <small>Synthetic customer</small>
                      </span>
                      <time dateTime={detail.created_at}>{displayDate(detail.created_at, true)}</time>
                    </div>
                  </header>
                  <div className="ticket-content">
                    <section className="message-section">
                      <div className="section-label">
                        <Icon name="inbox" size={15} />
                        CUSTOMER MESSAGE
                      </div>
                      <p className="customer-message">{detail.body}</p>
                    </section>
                    <section className="facts-section" aria-label="Entered facts">
                      <div className="section-label">
                        ENTERED FACTS<span>Manually supplied</span>
                      </div>
                      <dl className="facts-grid">
                        {Object.entries(fieldLabels).map(([key, label]) => (
                          <div key={key}>
                            <dt>{label}</dt>
                            <dd className={detail.facts[key] == null ? 'unknown' : ''}>
                              {factValues[key]?.[detail.facts[key]] ?? detail.facts[key] ?? 'Unknown'}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </section>
                    <section
                      className={`assessment assessment-${detail.assessment.decision}`}
                      aria-label="Policy assessment"
                    >
                      <span className="assessment-icon">
                        <Icon
                          name={detail.assessment.decision === 'eligible_review' ? 'check' : 'info'}
                          size={19}
                        />
                      </span>
                      <div>
                        <div className="assessment-heading">
                          <strong>
                            {decisionLabels[detail.assessment.decision] || detail.assessment.decision}
                          </strong>
                          <span>RULE-BASED CHECK</span>
                        </div>
                        <p>{detail.assessment.reason}</p>
                        {detail.assessment.missing_fields?.length > 0 && (
                          <p className="missing-facts">
                            Missing:{' '}
                            {detail.assessment.missing_fields
                              .map((key) => fieldLabels[key] || key)
                              .join(', ')}
                          </p>
                        )}
                        <small>Eligibility is not payment authorization.</small>
                      </div>
                    </section>
                    <div className="workbench-tabs" role="tablist" aria-label="Ticket sections">
                      <button
                        role="tab"
                        aria-selected={tab === 'draft'}
                        aria-controls="draft-panel"
                        id="draft-tab"
                        onClick={() => setTab('draft')}
                        className={tab === 'draft' ? 'active' : ''}
                      >
                        <Icon name="document" size={16} />
                        Reply & review
                      </button>
                      <button
                        role="tab"
                        aria-selected={tab === 'history'}
                        aria-controls="history-panel"
                        id="history-tab"
                        onClick={() => setTab('history')}
                        className={tab === 'history' ? 'active' : ''}
                      >
                        <Icon name="clock" size={16} />
                        Activity<span>{detail.events?.length || 0}</span>
                      </button>
                    </div>
                    <ErrorMessage
                      error={actionError}
                      onRetry={
                        conflict
                          ? () => {
                              if (mayDiscard()) loadDetail(detail.id);
                            }
                          : undefined
                      }
                    />
                    {notice && (
                      <div className="notice" role="status">
                        <Icon name="check" size={16} />
                        {notice}
                      </div>
                    )}
                    {tab === 'draft' ? (
                      <section id="draft-panel" role="tabpanel" aria-labelledby="draft-tab">
                        {detail.status !== 'approved' && (
                          <div className="draft-tools">
                            <div>
                              <h3>{draft ? 'Create another draft' : 'Start with a draft'}</h3>
                              <p>Use a template or ask the local model.</p>
                            </div>
                            <div className="draft-actions">
                              <button
                                className="button secondary compact"
                                onClick={() => generate('template')}
                                disabled={Boolean(busy)}
                              >
                                <Icon name="document" size={15} />
                                {busy === 'template' ? 'Preparing…' : 'Use template'}
                              </button>
                              <button
                                className="button teal-light compact"
                                onClick={() => generate('ai')}
                                disabled={Boolean(busy)}
                              >
                                {busy === 'ai' ? (
                                  <span className="spinner small" />
                                ) : (
                                  <Icon name="sparkle" size={16} />
                                )}{' '}
                                {busy === 'ai' ? 'Drafting locally…' : 'Generate AI draft'}
                              </button>
                            </div>
                          </div>
                        )}
                        {!draft ? (
                          <div className="composer-placeholder">
                            <Icon name="document" size={26} />
                            <p>No draft yet</p>
                          </div>
                        ) : (
                          <div className="draft-review">
                            <div className="draft-provenance">
                              <span className={`draft-mode ${draft.mode === 'ai' ? 'ai' : ''}`}>
                                <Icon name={draft.mode === 'ai' ? 'sparkle' : 'document'} size={14} />
                                {draft.mode === 'ai' ? 'Local AI draft' : 'Template · no AI'}
                              </span>
                              <span>
                                {draft.model ? `${draft.model} · ` : ''}
                                {Number.isFinite(draft.latency_ms)
                                  ? `${(draft.latency_ms / 1000).toFixed(1)}s`
                                  : ''}
                              </span>
                            </div>
                            {draft.warnings?.map((warning, index) => (
                              <div className="draft-warning" key={index}>
                                <Icon name="info" size={14} />
                                <span>{warning}</span>
                              </div>
                            ))}
                            <label className="draft-label" htmlFor="draft-body">
                              {pending ? 'Review and edit the reply' : 'Saved reply'}
                              {pending && (
                                <span>{dirty ? 'Unsaved edits' : 'Edits save with your review'}</span>
                              )}
                            </label>
                            <textarea
                              id="draft-body"
                              className="draft-editor"
                              value={draftBody}
                              onChange={(event) => setDraftBody(event.target.value)}
                              maxLength={4000}
                              rows={9}
                              readOnly={!pending}
                              disabled={Boolean(busy)}
                            />
                            <div className="citation-row">
                              <span>References</span>
                              {draft.citations?.map((id) => (
                                <a
                                  key={id}
                                  href={`#policy-${id}`}
                                  onClick={() =>
                                    document.getElementById(`policy-${id}`)?.setAttribute('open', '')
                                  }
                                >
                                  {id}
                                  <Icon name="chevron" size={11} />
                                </a>
                              ))}
                              {!draft.citations?.length && <span>No references supplied</span>}
                            </div>
                            {pending ? (
                              <div className="review-form">
                                <div className="review-form-heading">
                                  <h3>Human review</h3>
                                  <span>This name appears in the ticket history.</span>
                                </div>
                                <label htmlFor="reviewer">
                                  Reviewer name
                                  <input
                                    id="reviewer"
                                    value={reviewer}
                                    onChange={(event) => setReviewer(event.target.value)}
                                    placeholder="Your name"
                                    maxLength={80}
                                    disabled={Boolean(busy)}
                                  />
                                </label>
                                <label htmlFor="review-note">
                                  Review note
                                  <textarea
                                    id="review-note"
                                    value={note}
                                    onChange={(event) => setNote(event.target.value)}
                                    maxLength={500}
                                    rows={2}
                                    disabled={Boolean(busy)}
                                  />
                                </label>
                                <div className="review-actions">
                                  <button
                                    className="button reject"
                                    onClick={() => review('reject')}
                                    disabled={Boolean(busy)}
                                  >
                                    {busy === 'reject' ? 'Saving…' : 'Reject draft'}
                                  </button>
                                  <button
                                    className="button primary"
                                    onClick={() => review('approve')}
                                    disabled={Boolean(busy)}
                                  >
                                    <Icon name="check" size={17} />
                                    {busy === 'approve' ? 'Saving…' : 'Approve draft'}
                                  </button>
                                </div>
                                <p className="review-disclaimer">
                                  <Icon name="shield" size={13} />
                                  Approval saves this draft locally. It does not send a reply or issue a
                                  refund.
                                </p>
                              </div>
                            ) : (
                              <div
                                className={`review-record ${draft.review?.action === 'reject' ? 'rejected' : ''}`}
                              >
                                <Icon
                                  name={draft.review?.action === 'approve' ? 'check' : 'info'}
                                  size={18}
                                />
                                <div>
                                  <strong>
                                    {draft.review?.action === 'approve' ? 'Approved' : 'Rejected'} by{' '}
                                    {draft.review?.reviewer}
                                  </strong>
                                  <p>{draft.review?.note}</p>
                                  <small>
                                    {displayDate(draft.review?.created_at, true)} · Saved locally
                                  </small>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </section>
                    ) : (
                      <TicketHistory detail={detail} />
                    )}
                  </div>
                </>
              )}
            </section>

            <aside className="policy-panel" aria-label="Policy references">
              <div className="policy-header">
                <span className="policy-icon">
                  <Icon name="document" size={19} />
                </span>
                <div>
                  <h2>Policy reference</h2>
                  <p>Read the source before approving.</p>
                </div>
              </div>
              <div className="policy-version">
                <span className="live-dot" />
                Fictional policy<span>{policies[0]?.version || '—'}</span>
              </div>
              <div className="policy-list">
                {policies.map((policy) => (
                  <details
                    className={`policy-card ${citationIds.has(policy.id) ? 'cited' : ''}`}
                    id={`policy-${policy.id}`}
                    key={`${detail?.id}-${policy.id}`}
                    open={citationIds.has(policy.id) || undefined}
                  >
                    <summary>
                      <span className="policy-card-meta">
                        <span>{policy.id}</span>
                        {citationIds.has(policy.id) && <span className="cited-label">Referenced</span>}
                      </span>
                      <strong>{policy.title}</strong>
                    </summary>
                    <p>{policy.text}</p>
                  </details>
                ))}
              </div>
              <div className="policy-note">
                <Icon name="shield" size={21} />
                <h3>Reviewing a reply</h3>
                <p>Check dates and amounts in the draft against the cited policy.</p>
              </div>
            </aside>
          </div>
        </main>
      </div>
      {creating && (
        <NewTicket
          onClose={() => setCreating(false)}
          onCreate={(result) => {
            setCreating(false);
            setSelectedId(result.id);
            setSearch('');
            setFilter('all');
            setTab('draft');
            setReviewer('');
            loadWorkspace();
          }}
        />
      )}
    </div>
  );
}
