import React, { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { ErrorMessage, Icon } from './ui.jsx';

export default function NewTicket({ onClose, onCreate }) {
  const panel = useRef(null);
  const [form, setForm] = useState({
    customer: '',
    title: '',
    body: '',
    plan: '',
    charged_on: '',
    requested_on: '',
    usage_count: '',
    reason: '',
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  function changeField(event) {
    const { name, value } = event.target;
    setForm((previous) => ({ ...previous, [name]: value }));
  }

  useEffect(() => {
    const previous = document.activeElement;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panel.current?.querySelector('input')?.focus();
    return () => {
      document.body.style.overflow = priorOverflow;
      previous?.focus();
    };
  }, []);

  useEffect(() => {
    function onKey(event) {
      if (event.key === 'Escape' && !saving) onClose();
      if (event.key === 'Tab') {
        const focusable = Array.from(
          panel.current.querySelectorAll(
            'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled)',
          ),
        );
        const first = focusable[0],
          last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [saving, onClose]);
  async function submit(event) {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      const result = await api('/tickets', {
        customer: form.customer.trim(),
        title: form.title.trim(),
        body: form.body.trim(),
        facts: {
          plan: form.plan || null,
          charged_on: form.charged_on || null,
          requested_on: form.requested_on || null,
          usage_count: form.usage_count === '' ? null : Number(form.usage_count),
          reason: form.reason || null,
        },
      });
      onCreate(result);
    } catch (e) {
      setError(e.message);
      setSaving(false);
    }
  }
  return (
    <div className="modal-backdrop">
      <section
        ref={panel}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-ticket-title"
      >
        <header className="modal-header">
          <div>
            <h2 id="new-ticket-title">New demo ticket</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Close new ticket"
            onClick={onClose}
            disabled={saving}
          >
            <Icon name="cross" />
          </button>
        </header>
        <form onSubmit={submit}>
          <fieldset className="submission-fields" disabled={saving}>
            <p className="form-intro">Use fictional customer details for this ticket.</p>
            <div className="form-grid">
              <label className="span-two">
                Customer name
                <input
                  value={form.customer}
                  name="customer"
                  onChange={changeField}
                  required
                  maxLength={80}
                  placeholder="e.g. Jamie Chen"
                />
              </label>
              <label className="span-two">
                Subject
                <input
                  value={form.title}
                  name="title"
                  onChange={changeField}
                  required
                  maxLength={160}
                  placeholder="What does this customer need?"
                />
              </label>
              <label className="span-two">
                Customer message
                <textarea
                  value={form.body}
                  name="body"
                  onChange={changeField}
                  required
                  maxLength={4000}
                  rows={4}
                  placeholder="Paste or write a synthetic support request…"
                />
              </label>
            </div>
            <div className="form-divider">
              <span>Known facts</span>
              <small>Leave unknown facts blank</small>
            </div>
            <div className="form-grid">
              <label>
                Plan
                <select value={form.plan} name="plan" onChange={changeField}>
                  <option value="">Unknown</option>
                  <option value="monthly">Monthly</option>
                  <option value="annual">Annual</option>
                </select>
              </label>
              <label>
                Request type
                <select value={form.reason} name="reason" onChange={changeField}>
                  <option value="">Unknown</option>
                  <option value="refund">Refund</option>
                  <option value="cancel">Cancellation</option>
                  <option value="duplicate_charge">Duplicate charge</option>
                </select>
              </label>
              <label>
                Charge date
                <input type="date" value={form.charged_on} name="charged_on" onChange={changeField} />
              </label>
              <label>
                Request date
                <input
                  type="date"
                  value={form.requested_on}
                  name="requested_on"
                  onChange={changeField}
                />
              </label>
              <label>
                Usage count
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={form.usage_count}
                  name="usage_count"
                  onChange={changeField}
                  placeholder="Unknown"
                />
              </label>
            </div>
            <ErrorMessage error={error} />
            <footer className="modal-footer">
              <button type="button" className="button secondary" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button className="button primary" disabled={saving}>
                {saving ? 'Creating…' : 'Create ticket'}
                <Icon name="arrow" size={16} />
              </button>
            </footer>
          </fieldset>
        </form>
      </section>
    </div>
  );
}
