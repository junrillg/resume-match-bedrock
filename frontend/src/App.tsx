import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, type Match, type Requirement, type Session } from './api';

const defaults: Requirement[] = [
  { skill: 'Python', weight: 3 }, { skill: 'Django', weight: 3 },
  { skill: 'React', weight: 2 }, { skill: 'PostgreSQL', weight: 2 },
];
const sample = 'FICTIONAL SAMPLE — not a real candidate\n\nBackend engineer\nBuilt Python services and Django APIs for an internal inventory application.\nCreated React interfaces for searching products and reviewing stock.\nWrote integration tests and reviewed changes with the engineering team.';
const providerLabel = (provider: Session['provider']) => provider === 'bedrock' ? 'AWS Bedrock' : 'Demo · local deterministic';
const errorText = (error: unknown) => error instanceof ApiError
  ? `${error.message}${error.requestId ? ` Reference: ${error.requestId}` : ''}`
  : 'Something went wrong. Please try again.';

export function MatchResult({ match, onDelete, busy }: { match: Match; onDelete: () => void; busy: boolean }) {
  const matched = match.requirements.filter((item) => item.matched).length;
  return <section className="panel result" aria-labelledby="result-heading" aria-live="polite">
    <div className="section-heading"><div><p className="eyebrow">Evidence report</p><h2 id="result-heading">{match.job_title}</h2></div><span className="tag">{providerLabel(match.provider)}</span></div>
    <div className="score-row">
      <div className="score"><strong>{match.score}<span>%</span></strong><span>weighted coverage</span></div>
      <div><h3>{matched} of {match.requirements.length} skills evidenced</h3><p>Only evidence found in the résumé contributes to this score. Review every excerpt before drawing a conclusion.</p></div>
    </div>
    <div className="coverage-track" role="meter" aria-label="Weighted skill evidence coverage" aria-valuemin={0} aria-valuemax={100} aria-valuenow={match.score}><span style={{ width: `${match.score}%` }} /></div>
    <div className="evidence-list">{match.requirements.map((item) => <article className="evidence" key={item.skill}>
      <div className="evidence-heading"><h3><span className={`evidence-symbol ${item.matched ? 'found' : ''}`} aria-hidden="true">{item.matched ? '✓' : '−'}</span>{item.skill}</h3><span className="weight-label">Weight {item.weight} · {item.matched ? 'Evidenced' : 'Not evidenced'}</span></div>
      {item.matched && item.evidence ? <blockquote>{item.evidence}</blockquote> : <p className="gap">No supporting excerpt found. This is a gap in the document, not proof of a missing ability.</p>}
    </article>)}</div>
    <div className="report-footer"><span>Reference {match.request_id}</span><button className="text-button danger" type="button" disabled={busy} onClick={onDelete}>Delete this report</button></div>
  </section>;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [jobTitle, setJobTitle] = useState('Full stack engineer');
  const [requirements, setRequirements] = useState(defaults);
  const [source, setSource] = useState<'paste' | 'file'>('paste');
  const [resume, setResume] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [selected, setSelected] = useState<Match | null>(null);
  const [deleteRequested, setDeleteRequested] = useState(false);
  const resultRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function clearPrivateState() {
    setMatches([]); setSelected(null); setResume(''); setFile(null); setPassword('');
    setJobTitle('Full stack engineer'); setRequirements(defaults); setDeleteRequested(false);
    if (fileRef.current) fileRef.current.value = '';
  }

  async function refreshSession() {
    const current = await api<Session>('session/');
    setSession(current);
    return current;
  }
  async function load() {
    setLoading(true);
    setError('');
    try {
      const current = await refreshSession();
      if (current.authenticated) setMatches((await api<{ matches: Match[] }>('matches/')).matches);
      else clearPrivateState();
    } catch (error) { setError(errorText(error)); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try { await action(); }
    catch (error) {
      setError(errorText(error));
      if (error instanceof ApiError && error.status === 401) {
        clearPrivateState();
        try { await refreshSession(); } catch { setSession(null); }
      }
    } finally { setBusy(false); }
  }

  async function login(event: FormEvent) {
    event.preventDefault();
    await perform(async () => {
      await api<Session>('login/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) }, session?.csrfToken);
      setPassword('');
      await refreshSession();
      setMatches((await api<{ matches: Match[] }>('matches/')).matches);
    });
  }

  async function logout() {
    await perform(async () => {
      await api('logout/', { method: 'POST' }, session?.csrfToken);
      clearPrivateState();
      setSession(null);
      await refreshSession();
    });
  }

  async function analyze(event: FormEvent) {
    event.preventDefault();
    setError('');
    if (source === 'file' && (!file || file.size > 1024 * 1024 || !/\.(pdf|txt)$/i.test(file.name))) {
      setError('Choose a PDF or UTF-8 TXT file no larger than 1 MiB.'); return;
    }
    const cleaned = requirements.map((item) => ({ skill: item.skill.trim(), weight: item.weight }));
    if (new Set(cleaned.map((item) => item.skill.toLowerCase())).size !== cleaned.length) {
      setError('Each skill must be unique. Combine duplicate skills before running the match.'); return;
    }
    await perform(async () => {
      const body = new FormData();
      body.set('job_title', jobTitle.trim());
      body.set('requirements', JSON.stringify(cleaned));
      if (source === 'file' && file) body.set('resume', file);
      else body.set('resume_text', resume.trim());
      const match = await api<Match>('matches/', { method: 'POST', body }, session?.csrfToken);
      setMatches((previous) => [match, ...previous]);
      setSelected(match); setDeleteRequested(false);
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    });
  }

  async function deleteMatch() {
    if (!selected) return;
    const id = selected.id;
    await perform(async () => {
      await api(`matches/${id}/`, { method: 'DELETE' }, session?.csrfToken);
      setMatches((previous) => previous.filter((match) => match.id !== id));
      setSelected(null); setDeleteRequested(false);
    });
  }

  return <>
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="topbar"><a className="brand" href="/" aria-label="Resume Match home"><span className="brand-mark" aria-hidden="true">r<span>m</span></span><span>Resume Match<small>Evidence workspace</small></span></a>
      <div className="account">{session && <span className="provider"><i aria-hidden="true" />{providerLabel(session.provider)}</span>}{session?.authenticated && <><span className="username">{session.username}</span><button className="header-button" type="button" onClick={logout} disabled={busy}>Sign out</button></>}</div>
    </header>
    <main id="workspace">
      <div className="intro"><div><p className="eyebrow">Résumé intelligence / human review</p><h1>Make the evidence<br /><em>easy to see.</em></h1><p>Compare a résumé with the skills that matter for a role.<br className="desktop-break" /> Explicit weights. Source excerpts. A score you can inspect.</p></div><div className="intro-note"><span className="note-icon" aria-hidden="true">↗</span><p>A review aid, never a hiring recommendation. A person makes the decision.</p></div></div>
      {error && <div className="error" role="alert"><strong>We couldn’t complete that.</strong><p>{error}</p>{!session && <button type="button" onClick={load} disabled={loading}>Retry connection</button>}</div>}
      {loading ? <div className="panel loading" role="status">Connecting to your workspace…</div> : !session?.authenticated ? <section className="panel login-panel" aria-labelledby="login-heading"><div><p className="eyebrow">Your private workspace</p><h2 id="login-heading">Sign in to review a résumé</h2><p>Reports belong to your account. Original uploads are processed without keeping the file; reports retain supporting excerpts until deleted.</p><p className="help">Use the account created during local setup. There is no shared default password.</p></div><form onSubmit={login}><label htmlFor="username">Username</label><input id="username" autoComplete="username" required value={username} maxLength={150} onChange={(event) => setUsername(event.target.value)} /><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" maxLength={1024} required value={password} onChange={(event) => setPassword(event.target.value)} /><button className="primary" disabled={busy || !session} type="submit">{busy ? 'Signing in…' : 'Sign in'}<span aria-hidden="true">→</span></button></form></section> : <div className="workspace-grid">
        <div><form className="panel match-form" onSubmit={analyze} aria-labelledby="new-match-heading"><div className="section-heading"><div><p className="eyebrow">New comparison</p><h2 id="new-match-heading">Define the match</h2></div><button className="text-button" type="button" disabled={busy} onClick={() => { setResume(sample); setSource('paste'); setJobTitle('Full stack engineer'); setRequirements(defaults.map((item) => ({ ...item }))); setFile(null); if (fileRef.current) fileRef.current.value = ''; }}>Use fictional sample <span aria-hidden="true">↗</span></button></div>
          <fieldset disabled={busy}><legend className="step-title"><span>01</span> The role</legend><label htmlFor="job-title">Role title</label><input id="job-title" required maxLength={120} value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} />
          <div className="requirement-title"><span className="field-label">Required skills</span><span>Weight 1–10</span></div><p className="help">Higher weights give a skill more influence. Use specific, job-relevant skills.</p>
          {requirements.map((item, index) => <div className="requirement-row" key={index}><input aria-label={`Skill ${index + 1}`} placeholder="e.g. Django" required maxLength={80} value={item.skill} onChange={(event) => setRequirements((previous) => previous.map((value, i) => i === index ? { ...value, skill: event.target.value } : value))} /><input aria-label={`Weight for skill ${index + 1}`} type="number" min={1} max={10} step={1} required value={Number.isNaN(item.weight) ? '' : item.weight} onChange={(event) => setRequirements((previous) => previous.map((value, i) => i === index ? { ...value, weight: event.target.valueAsNumber } : value))} /><button className="remove-button" type="button" disabled={requirements.length === 1} aria-label={`Remove skill ${index + 1}`} onClick={() => setRequirements((previous) => previous.filter((_, i) => i !== index))}>×</button></div>)}
          <button className="text-button add-skill" type="button" disabled={requirements.length >= 20} onClick={() => setRequirements((previous) => [...previous, { skill: '', weight: 1 }])}>+ Add skill <span className="muted">{requirements.length}/20</span></button></fieldset>
          <fieldset disabled={busy}><legend className="step-title"><span>02</span> The résumé</legend><div className="source-options"><label><input type="radio" name="source" checked={source === 'paste'} onChange={() => setSource('paste')} /> Paste text</label><label><input type="radio" name="source" checked={source === 'file'} onChange={() => setSource('file')} /> Upload document</label></div>
          {source === 'paste' ? <><label className="sr-only" htmlFor="resume-text">Résumé text</label><textarea id="resume-text" required maxLength={30000} rows={8} placeholder="Paste the résumé here. Start with the fictional sample to explore safely." value={resume} onChange={(event) => setResume(event.target.value)} /><div className="input-meta"><span>Only the selected source is submitted.</span><span>{resume.length.toLocaleString()}/30,000</span></div></> : <div className="file-area"><label htmlFor="resume-file">Choose a résumé document</label><input id="resume-file" ref={fileRef} type="file" accept=".pdf,.txt" required onChange={(event) => setFile(event.target.files?.[0] || null)} /><p className="help">PDF or UTF-8 TXT · max 1 MiB · up to 10 PDF pages. Scanned PDFs need text extraction first.</p></div>}
          <p className="privacy-note">{session.provider === 'bedrock' ? 'Bedrock mode: submitted résumé text is sent to AWS Bedrock in the configured region. Use only documents you are authorized to process.' : 'Demo mode: local deterministic extraction. No résumé text is sent to AWS or an AI model.'}</p></fieldset>
          <button className="primary analyze" type="submit" disabled={busy}>{busy ? 'Processing résumé…' : 'Analyze evidence'}<span aria-hidden="true">→</span></button><p className="form-footnote">20 comparisons per account per day. Scores measure weighted evidence coverage, not candidate quality.</p>
        </form><div className="result-anchor" ref={resultRef}>{selected && <><MatchResult match={selected} busy={busy} onDelete={() => setDeleteRequested(true)} />{deleteRequested && <div className="delete-confirm" role="alert"><p>Delete this report and its saved evidence? This cannot be undone.</p><button className="danger-button" type="button" disabled={busy} onClick={deleteMatch}>Delete report</button><button className="text-button" type="button" disabled={busy} onClick={() => setDeleteRequested(false)}>Keep report</button></div>}</>}</div></div>
        <aside aria-labelledby="history-heading"><div className="history-heading"><p className="eyebrow">Your workspace</p><h2 id="history-heading">Recent reports <span>{matches.length}</span></h2></div>{matches.length ? <div className="history-list">{matches.map((match) => <button type="button" key={match.id} className={`history-item ${selected?.id === match.id ? 'selected' : ''}`} disabled={busy} aria-pressed={selected?.id === match.id} onClick={() => { setSelected(match); setDeleteRequested(false); }}><span className="history-title">{match.job_title}</span><span className="history-meta">{new Date(match.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}<span>{match.score}%</span></span></button>)}</div> : <div className="empty-history"><span aria-hidden="true">≡</span><h3>A clear paper trail.</h3><p>Your comparisons will appear here. Start with the fictional sample to see how the evidence report works.</p></div>}<div className="method-note"><h3>How the score works</h3><p>Matched skill weights ÷ all skill weights × 100.</p><p>Evidence is checked against the source text. An absent excerpt contributes zero weight. Skill wording and extraction errors can affect coverage.</p><span>Review excerpts, then verify with a person.</span></div></aside>
      </div>}
      <footer className="site-footer"><span>Resume Match <span aria-hidden="true">/</span> Architecture lab</span><span>Django · React · AWS Bedrock adapter</span></footer>
    </main>
  </>;
}
