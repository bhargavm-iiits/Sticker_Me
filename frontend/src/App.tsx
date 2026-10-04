import { useEffect, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import { StickerReview } from './StickerReview'

type Sticker = { id: string; position: number; intent: string; emoji: string; caption: string; status: string; revision: number; image_url: string | null; likeness_score: number | null; likeness_note: string | null; quality_status: string; quality_report: { checks?: Record<string, { state: string; note: string }> }; expression_intensity: number }
type Design = { candidate: number; image_url: string; score: number | null; quality: { status: string } }
type Pack = { id: string; name: string; mode: string; style: string; tone: string; approved: boolean; status: string; error: string | null; face_url: string | null; design_url: string | null; designs: Design[]; stickers: Sticker[] }
type Job = { kind: string; state: string; progress: number; total: number; error: string | null; phase?: string; estimated_remaining_seconds?: number | null }
type Doctor = { comfyui: { ready: boolean; error: string | null }; english_font: string | null; face_animation: boolean; photo_animation_enabled: boolean; photo_styles: string[]; hand_detector: boolean }
type Screen = 'home' | 'upload' | 'settings' | 'progress' | 'design' | 'preview' | 'editor' | 'export'

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

function packScreen(pack: Pack): Screen {
  return pack.status === 'ready' ? 'editor' : pack.status === 'awaiting_approval' ? 'preview' : pack.status === 'awaiting_design' ? 'design' : 'progress'
}

function MaskEditor({ pack, sticker, onSave, onClose }: { pack: Pack; sticker: Sticker; onSave: (data: FormData) => Promise<void>; onClose: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const original = useRef<HTMLImageElement | null>(null)
  const initial = useRef<HTMLImageElement | null>(null)
  const painting = useRef(false)
  const lastPoint = useRef<{ left: number; top: number } | null>(null)
  const [restore, setRestore] = useState(false)
  const [brush, setBrush] = useState(20)
  const [ready, setReady] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false
    function load(layer: string): Promise<HTMLImageElement> {
      return new Promise((resolve, reject) => {
        const image = new Image()
        image.onload = () => resolve(image)
        image.onerror = () => reject(new Error('Could not load the image layer'))
        image.src = `/api/packs/${pack.id}/stickers/${sticker.id}/layer/${layer}?v=${sticker.revision}`
      })
    }
    Promise.all([load('artwork'), load('cutout')]).then(([artwork, cutout]) => {
      if (disposed || !canvas.current) return
      original.current = artwork
      initial.current = cutout
      canvas.current.width = artwork.width
      canvas.current.height = artwork.height
      canvas.current.getContext('2d')?.drawImage(cutout, 0, 0)
      setReady(true)
    }).catch((err: Error) => setError(err.message))
    return () => { disposed = true }
  }, [pack.id, sticker.id, sticker.revision])

  function paint(event: PointerEvent<HTMLCanvasElement>) {
    if (!painting.current || !ready || saving || !original.current) return
    const surface = event.currentTarget
    const bounds = surface.getBoundingClientRect()
    const left = (event.clientX - bounds.left) * surface.width / bounds.width
    const top = (event.clientY - bounds.top) * surface.height / bounds.height
    const context = surface.getContext('2d')!
    const previous = lastPoint.current || { left, top }
    const distance = Math.hypot(left - previous.left, top - previous.top)
    const steps = Math.max(1, Math.ceil(distance / Math.max(1, brush / 3)))
    for (let step = 0; step <= steps; step++) {
      context.save()
      context.beginPath()
      context.arc(previous.left + (left - previous.left) * step / steps, previous.top + (top - previous.top) * step / steps, brush, 0, Math.PI * 2)
      if (restore) {
        context.clip()
        context.drawImage(original.current, 0, 0)
      } else {
        context.globalCompositeOperation = 'destination-out'
        context.fill()
      }
      context.restore()
    }
    lastPoint.current = { left, top }
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const blob = await new Promise<Blob>((resolve, reject) => canvas.current!.toBlob((value) => value ? resolve(value) : reject(new Error('Could not save mask')), 'image/png'))
      const data = new FormData()
      data.append('mask', blob, 'mask.png')
      await onSave(data)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return <div className="modal-backdrop"><section className="mask-modal" role="dialog" aria-modal="true" aria-label="Correct foreground mask">
    <div className="section-heading"><div><h2>Keep the good bits.</h2><p>Erase background or restore clipped hair and hands.</p></div><button className="text-button" disabled={saving} onClick={onClose}>Close</button></div>
    {error && <p role="alert">{error}</p>}
    <div className="mask-tools"><button className={`secondary-button ${!restore ? 'active' : ''}`} onClick={() => setRestore(false)}>Erase</button><button className={`secondary-button ${restore ? 'active' : ''}`} onClick={() => setRestore(true)}>Restore</button><label>Brush <input type="range" min="2" max="60" value={brush} onChange={(event) => setBrush(Number(event.target.value))} /></label><button className="text-button" disabled={!ready || saving} onClick={() => { const context = canvas.current!.getContext('2d')!; context.clearRect(0, 0, canvas.current!.width, canvas.current!.height); context.drawImage(initial.current!, 0, 0) }}>Reset</button></div>
    <canvas className="mask-canvas" ref={canvas} onPointerDown={(event) => { painting.current = true; lastPoint.current = null; event.currentTarget.setPointerCapture(event.pointerId); paint(event) }} onPointerMove={paint} onPointerUp={() => { painting.current = false; lastPoint.current = null }} onPointerCancel={() => { painting.current = false }} />
    <button className="primary-button" disabled={!ready || saving} onClick={save}>{saving ? 'Saving…' : 'Save mask'}</button>
  </section></div>
}

function App() {
  const [screen, setScreen] = useState<Screen>('home')
  const [packs, setPacks] = useState<Pack[]>([])
  const [pack, setPack] = useState<Pack | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [doctor, setDoctor] = useState<Doctor | null>(null)
  const [photo, setPhoto] = useState<File | null>(null)
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)
  const [name, setName] = useState('My stickers')
  const [style, setStyle] = useState('realistic')
  const [tone, setTone] = useState('playful')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [captionDraft, setCaptionDraft] = useState('')
  const [maskSticker, setMaskSticker] = useState<Sticker | null>(null)
  const [darkPreview, setDarkPreview] = useState(false)
  const requestKey = useRef(crypto.randomUUID())

  function refreshDoctor() {
    api<Doctor>('/api/doctor').then(setDoctor).catch((err: Error) => setError(err.message))
  }

  useEffect(() => {
    api<Pack[]>('/api/packs').then(setPacks).catch((err: Error) => setError(err.message))
    refreshDoctor()
  }, [])

  useEffect(() => { requestKey.current = crypto.randomUUID() }, [photo, name, style, tone])

  function acceptSnapshot(current: Pack, currentJob?: Job) {
    setPack(current)
    if (currentJob) setJob(currentJob)
    setPacks((previous) => [current, ...previous.filter((item) => item.id !== current.id)])
    setScreen((previous) => previous === 'progress' && ['ready', 'awaiting_approval', 'awaiting_design'].includes(current.status) ? packScreen(current) : previous)
  }

  useEffect(() => {
    if (!pack || !['queued', 'processing'].includes(pack.status)) return
    let disposed = false
    const id = pack.id
    const events = new EventSource(`/api/packs/${id}/events`)
    events.addEventListener('snapshot', (event) => {
      if (!disposed) {
        const snapshot = JSON.parse((event as MessageEvent).data) as { pack: Pack; job: Job }
        acceptSnapshot(snapshot.pack, snapshot.job)
      }
    })
    const timer = window.setInterval(async () => {
      try {
        const [current, currentJob] = await Promise.all([api<Pack>(`/api/packs/${id}`), api<Job>(`/api/packs/${id}/job`)])
        if (!disposed) acceptSnapshot(current, currentJob)
      } catch (err) {
        if (!disposed) setError((err as Error).message)
      }
    }, 5000)
    return () => { disposed = true; events.close(); window.clearInterval(timer) }
  }, [pack?.id, pack?.status])

  useEffect(() => {
    if (!photo) { setPhotoUrl(null); return }
    const url = URL.createObjectURL(photo)
    setPhotoUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [photo])

  async function openPack(id: string) {
    setError(null)
    setJob(null)
    try {
      const current = await api<Pack>(`/api/packs/${id}`)
      acceptSnapshot(current)
      setScreen(packScreen(current))
    } catch (err) { setError((err as Error).message) }
  }

  async function createPack() {
    if (!photo || !consent) return
    setBusy(true)
    setError(null)
    const data = new FormData()
    data.append('photo', photo)
    data.append('name', name)
    data.append('style', style)
    data.append('tone', tone)
    data.append('consent', 'true')
    try {
      const created = await api<Pack>('/api/packs', { method: 'POST', headers: { 'Idempotency-Key': requestKey.current }, body: data })
      acceptSnapshot(created)
      setJob(null)
      setScreen(packScreen(created))
    } catch (err) { setError((err as Error).message); refreshDoctor() }
    finally { setBusy(false) }
  }

  async function packAction(path: string, init: RequestInit = { method: 'POST' }, progress = false) {
    if (!pack) return
    setBusy(true)
    setError(null)
    try {
      const updated = await api<Pack>(`/api/packs/${pack.id}${path}`, init)
      acceptSnapshot(updated)
      if (progress) { setJob(null); setScreen('progress') }
      return updated
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  async function saveCaption(stickerId: string) {
    const updated = await packAction(`/stickers/${stickerId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ caption: captionDraft }) })
    if (updated) setEditingId(null)
  }

  async function moveSticker(stickerId: string, offset: number) {
    if (!pack) return
    const order = pack.stickers.map((sticker) => sticker.id)
    const position = order.indexOf(stickerId)
    const destination = position + offset
    if (destination < 0 || destination >= order.length) return
    ;[order[position], order[destination]] = [order[destination], order[position]]
    await packAction('/order', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sticker_ids: order }) })
  }

  async function deletePack(id: string) {
    if (!window.confirm('Delete this pack and all its local images?')) return
    try {
      await api(`/api/packs/${id}`, { method: 'DELETE' })
      setPacks((previous) => previous.filter((item) => item.id !== id))
      if (pack?.id === id) { setPack(null); setScreen('home') }
    } catch (err) { setError((err as Error).message) }
  }

  async function downloadPack(format: 'png' | 'platform' = 'platform') {
    if (!pack) return
    setBusy(true)
    setError(null)
    try {
      const response = await fetch(`/api/packs/${pack.id}/export${format === 'png' ? '/png' : ''}`)
      if (!response.ok) { const body = await response.json().catch(() => null); throw new Error(body?.detail || 'Export failed') }
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = `stickerme-${pack.id}${format === 'png' ? '-png' : ''}.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  function resetFlow() {
    setPhoto(null); setName('My stickers'); setStyle('realistic'); setTone('playful'); setConsent(false)
    setPack(null); setJob(null); setError(null); setEditingId(null); setScreen('upload'); refreshDoctor()
  }

  async function startOverFace() {
    if (pack && ['queued', 'processing'].includes(pack.status)) {
      const cancelled = await packAction('/cancel')
      if (!cancelled) return
    }
    resetFlow()
  }

  const previews = pack?.stickers.filter((sticker) => sticker.image_url) || []
  const activeGeneration = pack && ['queued', 'processing'].includes(pack.status)
  const photoNeedsAnimation = !!doctor?.photo_animation_enabled && !!doctor?.photo_styles.includes(style)
  const generationReady = !!doctor?.comfyui.ready && (!photoNeedsAnimation || doctor.face_animation)
  const previewsReviewed = previews.length === 3 && previews.every(s => ['accepted', 'legacy'].includes(s.quality_status))
  const allReviewed = !!pack?.stickers.every(s => ['accepted', 'legacy'].includes(s.quality_status))
  const reviewedCount = pack?.stickers.filter(s => ['accepted', 'legacy'].includes(s.quality_status)).length || 0

  function stickerCards(stickers: Sticker[], controls: boolean) {
    return <div className={`sticker-grid ${darkPreview ? 'dark-preview' : ''}`}>{stickers.map((sticker) => <article className="sticker-card" key={sticker.id}>
      <div className="sticker-preview">{sticker.image_url ? <img src={sticker.image_url} alt={`${sticker.intent}: ${sticker.caption}`} /> : <span>{sticker.status === 'generating' ? 'Drawing…' : 'Waiting'}</span>}</div>
      <div className="sticker-meta"><span>{String(sticker.position + 1).padStart(2, '0')} · {sticker.intent}</span><span>{sticker.emoji}</span></div>
      {controls && pack?.mode === 'cartoon' && sticker.image_url && <StickerReview sticker={sticker} busy={busy} packId={pack.id} action={packAction} />}
      {editingId === sticker.id ? <div className="caption-form"><input className="input" value={captionDraft} onChange={(event) => setCaptionDraft(event.target.value)} maxLength={48} aria-label={`Caption for ${sticker.intent}`} /><div><button className="secondary-button" disabled={busy} onClick={() => saveCaption(sticker.id)}>Save</button><button className="text-button" onClick={() => setEditingId(null)}>Cancel</button></div></div> : <div className="sticker-caption"><strong>{sticker.caption}</strong>{controls && <button className="text-button" disabled={busy} onClick={() => { setEditingId(sticker.id); setCaptionDraft(sticker.caption) }}>Edit</button>}</div>}
      {controls && sticker.image_url && pack && <a className="text-button save-png" href={`/api/packs/${pack.id}/stickers/${sticker.id}/download`} download={`${String(sticker.position + 1).padStart(2, '0')}-${sticker.intent}.png`}>Save PNG ↓</a>}{sticker.image_url && sticker.likeness_note && <small className="likeness-note">{sticker.likeness_note}</small>}{controls && pack?.mode === 'cartoon' && <div className="sticker-tools"><button className={sticker.likeness_score != null && sticker.likeness_score < 0.30 ? "text-button redraw-needed" : "text-button"} disabled={busy} onClick={() => packAction(`/stickers/${sticker.id}/regenerate`, { method: 'POST' }, true)}>Redraw</button><button className="text-button" disabled={busy} onClick={() => setMaskSticker(sticker)}>Fix mask</button>{pack.approved && <><button className="text-button" disabled={busy || sticker.position === 0} aria-label={`Move ${sticker.intent} earlier`} onClick={() => moveSticker(sticker.id, -1)}>←</button><button className="text-button" disabled={busy || sticker.position === pack.stickers.length - 1} aria-label={`Move ${sticker.intent} later`} onClick={() => moveSticker(sticker.id, 1)}>→</button><button className="text-button danger" disabled={busy || pack.stickers.length <= 3} onClick={() => { if (window.confirm(`Remove ${sticker.intent}?`)) packAction(`/stickers/${sticker.id}`, { method: 'DELETE' }) }}>Remove</button></>}</div>}
    </article>)}</div>
  }

  return <div className="app-shell">
    <header className="topbar"><button className="brand" onClick={() => setScreen('home')} aria-label="StickerMe home"><span className="brand-mark">✦</span><span>Sticker<span className="brand-accent">Me</span></span></button><div className="top-actions"><span className="local-badge"><span className="local-dot" /> Local & private</span><button className="text-button" onClick={() => setScreen('home')}>My packs</button></div></header>
    <main>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
      {pack && previews.length > 0 && ['progress', 'preview', 'editor', 'export'].includes(screen) && <div className="download-toolbar"><button className="primary-button" disabled={busy} onClick={() => downloadPack('png')}>{busy ? 'Preparing download…' : `Download PNGs (${previews.length})`} ↓</button><span>Transparent images with your current captions. Download any saved reaction.</span></div>}
      {screen === 'home' && <>
        <section className="hero"><div className="hero-content"><span className="eyebrow">YOUR FACE. EVERY FEELING.</span><h1>A little <em>cartoon you.</em> A whole lot of expression.</h1><p>Turn one photo into a pack of reactions. Choose a photographic look or an illustrated character, then review the face, expression and hands before exporting.</p><div className="hero-actions"><button className="primary-button" onClick={resetFlow}>Make my stickers <span>↗</span></button><span className="quiet-note">English captions · No account · Local GPU</span></div></div><div className="hero-art" aria-hidden="true"><div className="orb orb-one" /><div className="orb orb-two" /><div className="demo-card demo-one"><span>👋</span><strong>Hi!</strong></div><div className="demo-card demo-two"><span>💜</span><strong>Miss you</strong></div><div className="demo-card demo-three"><span>😂</span><strong>LOL</strong></div><div className="sparkle sparkle-one">✦</div><div className="sparkle sparkle-two">✧</div></div></section>
        <section className="content-section"><div className="section-heading"><div><span className="eyebrow">YOUR COLLECTION</span><h2>My sticker packs</h2></div><span className="count-pill">{packs.length} packs</span></div>{packs.length === 0 ? <div className="empty-state"><div className="empty-icon">✳</div><h3>Your collection starts here</h3><p>Preview three reactions before making your full pack.</p><button className="secondary-button" onClick={resetFlow}>Create a pack</button></div> : <div className="pack-grid">{packs.map((item) => <article className="pack-card" key={item.id}><div className="pack-cover">{item.stickers.find((sticker) => sticker.image_url)?.image_url ? <img src={item.stickers.find((sticker) => sticker.image_url)!.image_url!} alt="Pack preview" /> : <span>✦</span>}</div><div className="pack-card-body"><span className="status-pill">{item.status.replaceAll('_', ' ')}</span><h3>{item.name}</h3><p>{item.stickers.length} stickers · {item.mode === 'cartoon' ? `${item.style} · English` : 'Legacy photo cutout — same pose'}</p><div className="card-actions"><button className="secondary-button" onClick={() => openPack(item.id)}>Open pack</button><button className="icon-button" onClick={() => deletePack(item.id)} aria-label={`Delete ${item.name}`}>⌫</button></div></div></article>)}</div>}</section>
      </>}
      {screen === 'upload' && <section className="flow-layout"><div className="flow-intro"><span className="step-label">STEP 01 / 04</span><h1>Meet your <em>sticker self.</em></h1><p>Choose one person facing the camera in even light. Your face should fill at least a quarter of the photo width. Avoid sunglasses, masks, and beauty filters.</p><div className="tip-card"><strong>Your real face, new reactions</strong><p>Realistic and Likeness generate each expression and pose together using your original photo as the identity reference. Cartoon, Chibi and Comic draw a character from your photo; choose a recognizable design first. Check every expression and gesture in the previews.</p></div></div><div className="form-card"><label className={`dropzone ${photoUrl ? 'has-photo' : ''}`} htmlFor="photo-input">{photoUrl ? <img src={photoUrl} alt="Selected photo preview" /> : <><span className="upload-icon">↑</span><strong>Choose your photo</strong><span>JPEG, PNG, or WebP · up to 12 MB</span></>}<input id="photo-input" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file && file.size > 12 * 1024 * 1024) { setError('Choose a photo under 12 MB'); return } setPhoto(file || null); setError(null) }} /></label><div className="form-footer"><button className="text-button" onClick={() => setScreen('home')}>← Back</button><button className="primary-button" disabled={!photo} onClick={() => setScreen('settings')}>Continue →</button></div></div></section>}
      {screen === 'settings' && <section className="flow-layout"><div className="flow-intro"><span className="step-label">STEP 02 / 04</span><h1>Choose your <em>vibe.</em></h1><p>For illustrated styles, choose a character design first. Then review three reactions: a wave, a laugh and a surprise, before making the other nine.</p><div className="tip-card"><strong>{doctor?.comfyui.ready ? 'Cartoon engine ready' : 'Checking local engine'}</strong><p>{doctor?.comfyui.ready ? 'FLUX.2 Klein 4B runs on this computer. The first image can take longer while the models load.' : doctor?.comfyui.error || 'Loading diagnostics…'}</p><button className="text-button" onClick={refreshDoctor}>Refresh engine check</button>{photoNeedsAnimation && doctor && !doctor.face_animation && <p>Original-photo face animation is unavailable. Run setup.ps1 -DownloadModel or choose an illustrated style.</p>}{doctor && !doctor.comfyui.ready && <p>Run <code>setup_engine.ps1</code>, then <code>start.ps1</code>.</p>}</div></div><div className="form-card settings-card"><label className="field-label" htmlFor="pack-name">Pack name</label><input className="input" id="pack-name" maxLength={80} value={name} onChange={(event) => setName(event.target.value)} /><span className="field-label">Illustration style</span><div className="choice-grid three-choices">{['realistic', 'likeness', 'cartoon', 'chibi', 'comic'].map((value) => <button key={value} className={`choice ${style === value ? 'selected' : ''}`} onClick={() => setStyle(value)}><strong>{value === 'realistic' ? 'Realistic (recommended)' : value}</strong><small>{value === 'realistic' ? 'Photo reference · natural reactions' : value === 'likeness' ? 'Your own face, soft shading' : value === 'cartoon' ? 'Drawn character · smooth outlines' : value === 'chibi' ? 'Large head · small body' : 'Drawn character · bold ink'}</small></button>)}</div><span className="field-label tone-label">Expression tone</span><div className="choice-grid three-choices">{['playful', 'warm', 'dramatic'].map((value) => <button key={value} className={`choice ${tone === value ? 'selected' : ''}`} onClick={() => setTone(value)}><strong>{value}</strong></button>)}</div><p className="quiet-note">English starter captions. Edit or remove captions later.</p><label className="check-row"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>I have permission to use this person’s photo.</span></label><div className="form-footer"><button className="text-button" onClick={() => setScreen('upload')}>← Back</button><button className="primary-button" disabled={!photo || !consent || busy || !generationReady} onClick={createPack}>{busy ? 'Creating…' : ['cartoon', 'chibi', 'comic'].includes(style) ? 'Create 2 character designs' : 'Create 3 previews'} ✦</button></div></div></section>}
      {pack?.face_url && ['progress', 'design', 'preview', 'editor'].includes(screen) && <div className="face-reference"><img src={pack.face_url} alt="Face crop used for generation" />{pack.design_url && <img src={pack.design_url} alt="Approved character design" />}<div><strong>Your photo{pack.design_url ? ' and approved character' : ' reference'}</strong><p>Compare it with each reaction.</p></div><button className="text-button" disabled={busy} onClick={startOverFace}>Wrong face? Start over</button></div>}
      {screen === 'design' && pack && <section className="content-section"><div className="section-heading"><div><span className="step-label">CHOOSE YOUR CHARACTER</span><h1>Which drawing feels like <em>you?</em></h1><p>Compare the face shape, hair, facial hair and accessories with your photo. This design will guide every reaction.</p></div><button className="secondary-button" disabled={busy} onClick={() => packAction('/design/retry', { method: 'POST' }, true)}>Try two more designs</button></div><div className="sticker-grid design-grid">{pack.designs.map(design => <article className="sticker-card" key={design.candidate}><div className="sticker-preview"><img src={design.image_url} alt={`Character design ${design.candidate + 1}`} /></div><p>{design.score == null ? 'Compare the face manually' : `Face score ${design.score.toFixed(2)} · advisory`}</p><button className="primary-button" disabled={busy || design.quality.status === 'blocked'} onClick={() => packAction('/design', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ candidate: design.candidate }) }, true)}>Use this character</button>{design.quality.status === 'blocked' && <p>Possible anatomy or duplicate-face defect. Try another design.</p>}</article>)}</div></section>}
      {screen === 'progress' && pack && <section className="content-section"><div className="section-heading"><div><span className="step-label">{pack.approved ? 'DRAWING YOUR PACK' : 'STEP 03 / 04'}</span><h1>{pack.status === 'failed' ? 'We hit a snag.' : pack.status === 'cancelled' ? 'Generation paused.' : 'Drawing each reaction.'}</h1><p>{pack.error || 'We generate the selected reaction, screen face resemblance and anatomy, then prepare the cutout and caption. Completed candidates appear below for your review.'}</p></div><button className="text-button" onClick={() => setScreen('home')}>Back to my packs</button></div><div className="progress-panel"><div className="progress-copy"><strong>{job?.kind === 'design' ? 'Creating character designs' : job?.kind === 'regenerate' ? 'Correcting selected reaction' : pack.approved ? 'Generating remaining reactions' : 'Generating three previews'}</strong><span>{job?.progress || 0} / {job?.total || (pack.approved ? 9 : 3)}</span></div><p className="progress-phase">{job?.phase || 'Preparing references'}{job?.estimated_remaining_seconds != null && ` · approximately ${Math.ceil(job.estimated_remaining_seconds / 60)} min remaining, based on completed reactions`}</p><div className="progress-track"><div style={{ width: `${((job?.progress || 0) / (job?.total || 3)) * 100}%` }} /></div></div><div className="flow-actions">{activeGeneration ? <button className="secondary-button" disabled={busy} onClick={() => packAction('/cancel')}>Cancel generation</button> : <button className="primary-button" disabled={busy} onClick={() => { if (window.confirm('Resume incomplete reactions? If the engine lost its history, this explicitly permits a new attempt. Completed stickers will be kept.')) packAction('/retry', { method: 'POST' }, true) }}>Resume incomplete stickers</button>}</div>{stickerCards(previews, false)}</section>}
      {screen === 'preview' && pack && <section className="content-section"><div className="section-heading"><div><span className="step-label">STEP 03 / 04 · CHECK YOUR CARTOON</span><h1>Does this feel like <em>you?</em></h1><p>Check the face, expression, and hands. Redraw a reaction if needed. Your full pack will reuse these three.</p></div><button className="primary-button" disabled={busy || !previewsReviewed} onClick={() => packAction('/approve', { method: 'POST' }, true)}>Approve & draw 9 more →</button></div><div className="notice">Face scores are advisory. Compare your face, check the intended emotion and inspect every hand. Mark each preview reviewed before continuing.</div>{stickerCards(previews, true)}</section>}
      {screen === 'editor' && pack && <section className="content-section editor-section"><div className="section-heading"><div><span className="eyebrow">{pack.mode === 'cartoon' ? `${pack.style} REACTIONS · ENGLISH` : 'LEGACY CUTOUT · SAME POSE'}</span><h1>{pack.name}</h1><p>{pack.mode === 'cartoon' ? 'Different expressions. Different gestures. Your words.' : 'This older pack is a cutout, not generated cartoons. Create a new pack for new expressions.'}</p></div><button className="primary-button" disabled={busy || (pack.mode === 'cartoon' && !allReviewed)} onClick={() => setScreen('export')}>WhatsApp / Telegram ZIP ↗</button></div><div className="notice">PNG downloads are available now. Review each sticker before creating the WhatsApp / Telegram ZIP. Correction creates a new candidate for one reaction; compare or restore previous versions. Caption and mask edits keep the generated artwork.</div><p className="review-progress" role="status">{reviewedCount} / {pack.stickers.length} stickers reviewed. {allReviewed ? 'Your pack is ready to export.' : 'Review the remaining images below. Flagged images can be accepted after you check them.'}</p><div className="preview-toggle"><button className="secondary-button" onClick={() => setDarkPreview(!darkPreview)}>{darkPreview ? 'Light preview' : 'Dark preview'}</button></div>{stickerCards(pack.stickers, true)}</section>}
      {screen === 'export' && pack && <section className="center-stage export-stage"><span className="step-label">STEP 04 / 04 · READY TO SHARE</span><div className="export-art">↗</div><h1>Pack it up, <em>send it out.</em></h1><p>Your ZIP includes {pack.stickers.length} transparent stickers for WhatsApp and Telegram, separate text-free artwork, a tray icon, and generation details.</p><button className="primary-button download-button" disabled={busy} onClick={() => downloadPack('platform')}>{busy ? 'Preparing ZIP…' : 'Download ZIP'} ↓</button><div className="tip-card export-tip"><strong>Import instructions</strong><p>A ZIP does not install stickers automatically. Transfer it to your phone. WhatsApp needs a compatible sticker app; for Telegram, upload through @stickers. Emoji mappings are included in the manifest.</p></div><button className="text-button" onClick={() => setScreen('editor')}>← Back to editor</button></section>}
    </main>
    {maskSticker && pack && <MaskEditor pack={pack} sticker={maskSticker} onClose={() => setMaskSticker(null)} onSave={async (data) => { const updated = await api<Pack>(`/api/packs/${pack.id}/stickers/${maskSticker.id}/mask`, { method: 'POST', body: data }); acceptSnapshot(updated); setMaskSticker(null) }} />}
    <footer className="footer"><span>✦ StickerMe</span><span>Made locally, kept personally.</span></footer>
  </div>
}

export default App
