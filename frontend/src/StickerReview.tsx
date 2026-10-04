import { useEffect, useState } from 'react'

type Check = { state: string; note: string }
type ReviewedSticker = { id: string; revision: number; intent: string; image_url: string | null; quality_status: string; quality_report: { checks?: Record<string, Check> }; expression_intensity: number; likeness_score: number | null; caption: string }
type Version = { id: string; revision: number; image_url: string; caption: string; quality_status: string }
type Action = (path: string, init?: RequestInit, progress?: boolean) => Promise<unknown>

export function StickerReview({ sticker, busy, packId, action }: { sticker: ReviewedSticker; busy: boolean; packId: string; action: Action }) {
  const [correction, setCorrection] = useState('redraw')
  const [intensity, setIntensity] = useState(sticker.expression_intensity || 1)
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [selected, setSelected] = useState<Version | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { setIntensity(sticker.expression_intensity || 1) }, [sticker.expression_intensity])
  useEffect(() => {
    if (!versions) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setVersions(null) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [versions])
  const base = `/stickers/${sticker.id}`
  async function history() {
    setError(null)
    try {
      const response = await fetch(`/api/packs/${packId}${base}/versions`)
      if (!response.ok) throw new Error('Could not load saved versions. Wait for generation to finish.')
      const items: Version[] = await response.json()
      setVersions(items)
      setSelected(items.find(v => v.revision !== sticker.revision) || items[0] || null)
    } catch (err) { setError((err as Error).message) }
  }
  return <div className="quality-panel">
    <span className={`quality-status ${sticker.quality_status}`}>{sticker.quality_status === 'accepted' ? 'Reviewed by you' : sticker.quality_status === 'blocked' ? 'Check flagged image' : sticker.quality_status === 'legacy' ? 'Earlier artwork · check visually' : 'Needs your review'}</span>
    {sticker.likeness_score != null && <small>Face score {sticker.likeness_score.toFixed(2)} · advisory</small>}
    <details><summary>Face, expression & anatomy checks</summary><ul>{Object.entries(sticker.quality_report?.checks || {}).map(([name, check]) => <li key={name}><strong>{name}: </strong>{check.note}<span className="check-state">{check.state === 'screened' ? 'Automatically screened' : check.state.replaceAll('_', ' ')}</span></li>)}</ul></details>
    {sticker.quality_status === 'blocked' && <small className="review-warning">An automatic check flagged this image. Inspect the face and hands; if they look right, you can accept it anyway.</small>}
    {sticker.quality_status !== 'accepted' && <button className="secondary-button review-button" disabled={busy || !sticker.image_url} onClick={() => action(`${base}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: sticker.revision, override_detected: sticker.quality_status === 'blocked' }) })}>{sticker.quality_status === 'blocked' ? 'I checked it—accept anyway' : 'Face, reaction & hands look right'}</button>}
    <label className="correction-label">Improve this reaction<select value={correction} onChange={event => setCorrection(event.target.value)}><option value="redraw">New candidate</option><option value="face">Closer face resemblance</option><option value="hands">Better hands and gesture</option><option value="expression">Clearer expression</option></select></label>
    <label className="intensity-label">Expression intensity <output>{intensity.toFixed(2)}</output><input type="range" aria-label={`Expression intensity for ${sticker.intent}`} min="0.25" max="1.3" step="0.05" value={intensity} onChange={event => setIntensity(Number(event.target.value))} /></label>
    <small>Creates a new candidate for this reaction; compare and restore earlier versions.</small>
    <div className="review-actions"><button className="text-button" disabled={busy} onClick={() => action(`${base}/regenerate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ correction, intensity }) }, true)}>Generate correction</button><button className="text-button" disabled={busy} onClick={history}>Compare / restore</button>{sticker.caption && <button className="text-button" disabled={busy} onClick={() => action(base, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ caption: '' }) })}>Remove caption</button>}</div>
    {error && <p role="alert">{error}</p>}
    {versions && <div className="modal-backdrop"><section className="mask-modal version-modal" role="dialog" aria-modal="true" aria-label="Compare saved sticker versions"><div className="section-heading"><h2>Choose the better reaction.</h2><button className="text-button" onClick={() => setVersions(null)}>Close</button></div><div className="version-comparison"><figure><img src={sticker.image_url || ''} alt="Current sticker" /><figcaption>Current · version {sticker.revision}</figcaption></figure>{selected && <figure><img src={selected.image_url} alt={`Saved version ${selected.revision}`} /><figcaption>Saved · version {selected.revision}</figcaption></figure>}</div><label>Saved versions<select value={selected?.id || ''} onChange={event => setSelected(versions.find(v => v.id === event.target.value) || null)}>{versions.map(v => <option key={v.id} value={v.id}>Version {v.revision} · {v.caption || 'No caption'}</option>)}</select></label><button className="primary-button" disabled={busy || !selected || selected.revision === sticker.revision} onClick={async () => { const result = await action(`${base}/versions/${selected!.id}/restore`); if (result) setVersions(null) }}>Restore selected version</button></section></div>}
  </div>
}
