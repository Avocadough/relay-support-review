import React from 'react';
import { displayDate } from './ui.jsx';

function draftStatus(draft, index) {
  if (draft.review) return draft.review.action === 'approve' ? 'Approved' : 'Rejected';
  return index === 0 ? 'Pending review' : 'Superseded';
}

export default function TicketHistory({ detail }) {
  return (
    <section id="history-panel" role="tabpanel" aria-labelledby="history-tab" className="history-panel">
      <div className="section-label">
        ACTIVITY LOG<span>Revision {detail.revision}</span>
      </div>
      {detail.events?.length ? (
        <ol className="activity-list">
          {[...detail.events]
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            .map((event) => (
              <li key={event.id}>
                <span className="activity-dot" />
                <div>
                  <strong>{event.kind.replaceAll('_', ' ')}</strong>
                  <p>{event.message}</p>
                  <time dateTime={event.created_at}>{displayDate(event.created_at, true)}</time>
                </div>
              </li>
            ))}
        </ol>
      ) : (
        <p className="muted">No activity recorded yet.</p>
      )}
      {detail.drafts?.length > 0 && (
        <>
          <div className="section-label history-drafts-heading">DRAFT HISTORY</div>
          {detail.drafts.map((item, index) => (
            <details className="history-draft" key={item.id}>
              <summary>
                <span>
                  {item.mode === 'ai' ? 'Local AI' : 'Template'} draft {detail.drafts.length - index}
                </span>
                <span>{draftStatus(item, index)}</span>
              </summary>
              <p>{item.body}</p>
              {item.original_body !== item.body && (
                <details className="original-draft">
                  <summary>Original generated text</summary>
                  <p>{item.original_body}</p>
                </details>
              )}
              {item.review && (
                <div className="history-review-note">
                  <strong>{item.review.reviewer}</strong> · {item.review.note}
                </div>
              )}
              <small>{displayDate(item.created_at, true)}</small>
            </details>
          ))}
        </>
      )}
    </section>
  );
}
