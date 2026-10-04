import { useEffect, useRef, useState } from 'react'
import { Client, handle_file } from '@gradio/client'
import { zipSync, strToU8 } from 'fflate'
import { CLOUD_SPACE, CLOUD_ORIGIN, REACTIONS, STYLES, TONES, reactionPrompt, validatePhoto, composeCloudSticker, savedCloudPacks, saveCloudPack, downloadBlob } from './cloudSticker'
import type { CloudPack, CloudSticker } from './cloudSticker'
import './free-cloud.css'

function newPack(): CloudPack { return { id: crypto.randomUUID(), name: 'My stickers', style: 'cartoon', tone: 'playful', photo: null, stickers: [] } }
function useBlobUrl(blob: Blob | null) {
  const [url, setUrl] = useState('')
  useEffect(() => { if (!blob) { setUrl(''); return }; const value = URL.createObjectURL(blob); setUrl(value); return () => URL.revokeObjectURL(value) }, [blob])
  return url
}

function StickerCard({ sticker, disabled, change, redraw }: { sticker: CloudSticker; disabled: boolean; change: (sticker: CloudSticker) => Promise<void>; redraw: () => void }) {
  const url = useBlobUrl(sticker.png)
  const [caption, setCaption] = useState(sticker.caption)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => setCaption(sticker.caption), [sticker.caption])
  async function edit(transparent = sticker.transparent ?? true) {
    setSaving(true); setError('')
    try { await change({ ...sticker, caption: caption.trim(), transparent, reviewed: false, png: await composeCloudSticker(sticker.artwork, caption, transparent) }) } catch (err) { setError((err as Error).message) } finally { setSaving(false) }
  }
  return <article className="sticker-card cloud-sticker">
    <div className="sticker-preview checker"><img src={url} alt={`${sticker.key}: ${sticker.caption}`} /></div>
    <label className="cloud-caption">Caption<input aria-label={`${sticker.key} caption`} value={caption} maxLength={48} disabled={disabled || saving} onChange={event => setCaption(event.target.value)} /></label>
    <div className="cloud-card-actions"><button className="text-button" disabled={disabled || saving || caption === sticker.caption} onClick={() => edit()}>Apply caption</button><button className="text-button" disabled={disabled || saving} onClick={redraw}>Redraw</button></div>
    <label className="cloud-check"><input type="checkbox" checked={sticker.reviewed} disabled={disabled || saving} onChange={event => change({ ...sticker, reviewed: event.target.checked })} />Face & hands look right</label>
    <div className="cloud-card-actions"><button className="secondary-button" onClick={() => downloadBlob(sticker.png, `${sticker.key}.png`)}>Save PNG ↓</button><button className="text-button" disabled={disabled || saving} onClick={() => edit(!sticker.transparent)}>{sticker.transparent ? 'Keep background' : 'Remove background'}</button></div>
    {error && <p className="cloud-error" role="alert">{error}</p>}
  </article>
}

export default function FreeCloudApp() {
  const [pack, setPack] = useState<CloudPack>(newPack)
  const [packs, setPacks] = useState<CloudPack[]>([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reaction, setReaction] = useState('greeting')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [loaded, setLoaded] = useState(false)
  const cancelled = useRef(false)
  const active = useRef<{ cancel: () => unknown } | null>(null)
  const photoUrl = useBlobUrl(pack.photo)

  useEffect(() => {
    let disposed = false
    savedCloudPacks().then(items => { if (!disposed) { setPacks(items); if (items.length) setPack(items[items.length - 1]); setLoaded(true) } }).catch(err => { if (!disposed) { setError(err.message); setLoaded(true) } })
    return () => { disposed = true; cancelled.current = true; active.current?.cancel() }
  }, [])

  async function persist(next: CloudPack) {
    setPack(next)
    setPacks(previous => [...previous.filter(item => item.id !== next.id), next])
    try { await saveCloudPack(next) } catch (err) { setError((err as Error).message) }
  }

  async function choosePhoto(file?: File) {
    if (!file) return
    setError('')
    try {
      await validatePhoto(file)
      await persist({ ...newPack(), name: pack.name, style: pack.style, tone: pack.tone, photo: file })
      setConsent(false)
    } catch (err) { setError((err as Error).message) }
  }

  async function generate(keys: string[]) {
    if (!pack.photo || !consent || busy) return
    setBusy(true); setError(''); cancelled.current = false
    let current = pack
    try {
      setStatus('Connecting to the free GPU…')
      const client = await Client.connect(CLOUD_SPACE, { events: ['data', 'status'] })
      for (let index = 0; index < keys.length; index++) {
        if (cancelled.current) break
        const key = keys[index], item = REACTIONS.find(value => value.key === key)!
        const seed = crypto.getRandomValues(new Uint32Array(1))[0] % 2147483647
        setStatus(`${index + 1}/${keys.length} · ${item.caption} · waiting for a GPU…`)
        const job = client.submit('/infer', {
          prompt: reactionPrompt(key, current.style, current.tone), input_images: [{ image: handle_file(current.photo!), caption: null }],
          mode_choice: 'Distilled (4 steps)', seed, randomize_seed: false, width: 768, height: 768,
          num_inference_steps: 4, guidance_scale: 1, prompt_upsampling: false,
        })
        active.current = job
        let resultUrl = ''
        for await (const event of job) {
          if (cancelled.current) break
          if (event.type === 'status') {
            if (event.stage === 'error') throw new Error(typeof event.message === 'string' ? event.message : 'The free GPU request failed. Try again later.')
            setStatus(`${index + 1}/${keys.length} · ${item.caption} · ${event.stage === 'generating' ? 'drawing your reaction…' : event.position != null ? `queue position ${event.position + 1}` : 'waiting for a GPU…'}`)
          }
          if (event.type === 'data') {
            const result = (event.data as Array<{ url?: string } | string>)[0]
            resultUrl = typeof result === 'string' ? result : result?.url || ''
          }
        }
        active.current = null
        if (cancelled.current) break
        if (!resultUrl) throw new Error('The GPU returned no image. Try again later.')
        const url = new URL(resultUrl, CLOUD_ORIGIN)
        if (url.origin !== CLOUD_ORIGIN) throw new Error('The image service returned an unexpected download address.')
        setStatus(`${index + 1}/${keys.length} · finishing the transparent PNG…`)
        const response = await fetch(url)
        if (!response.ok) throw new Error('Could not download the generated artwork. Try again.')
        const artwork = await response.blob()
        const caption = current.stickers.find(sticker => sticker.key === key)?.caption ?? item.caption
        const png = await composeCloudSticker(artwork, caption)
        if (cancelled.current) break
        current = { ...current, stickers: [...current.stickers.filter(sticker => sticker.key !== key), { key, caption, artwork, png, seed, reviewed: false, transparent: true }] }
        await persist(current)
      }
      setStatus(cancelled.current ? 'Stopped. Your finished stickers are saved.' : 'Ready. Check the face, expression and hands before sharing.')
    } catch (err) {
      const message = (err instanceof Error ? err.message : typeof err === 'object' && err && 'message' in err ? String(err.message) : String(err)).replace(/<[^>]*>/g, '')
      setError(cancelled.current ? '' : /quota|exceed|GPU duration/i.test(message) ? `The free GPU quota is exhausted. Your finished stickers are saved; try again after the quota resets. ${message}` : message)
      setStatus('Your finished stickers are saved in this browser.')
    } finally { active.current = null; setBusy(false) }
  }

  async function downloadPack() {
    try {
      const files: Record<string, Uint8Array> = {}
      for (const item of pack.stickers) files[`${item.key}.png`] = new Uint8Array(await item.png.arrayBuffer())
      files['pack.json'] = strToU8(JSON.stringify({ name: pack.name, style: pack.style, tone: pack.tone, model: CLOUD_SPACE, stickers: pack.stickers.map(({ key, caption, seed, reviewed }) => ({ key, caption, seed, reviewed })) }, null, 2))
      const zip = zipSync(files, { level: 0 })
      downloadBlob(new Blob([new Uint8Array(zip)], { type: 'application/zip' }), `${pack.name.replace(/[^a-z0-9-]/gi, '-').slice(0, 60) || 'stickers'}.zip`)
    } catch (err) { setError((err as Error).message) }
  }

  const ready = loaded && !!pack.photo && consent && !busy
  const missing = REACTIONS.filter(item => !pack.stickers.some(sticker => sticker.key === item.key))
  const previewKeys = ['greeting', 'laughter', 'surprise'].filter(key => !pack.stickers.some(item => item.key === key))
  return <div className="app-shell free-cloud">
    <header className="topbar"><a className="brand" href="/"><span className="brand-mark">✳</span>StickerMe<span className="brand-dot">.</span></a><span className="cloud-badge">FREE CLOUD DEMO</span></header>
    <main>
      <section className="hero cloud-hero"><div className="hero-content"><span className="eyebrow">YOUR FACE. A LITTLE MORE YOU.</span><h1>Every reaction.<br /><em>Made personal.</em></h1><p>Turn one portrait into expressive stickers. Preview a few, check the details, then build your collection.</p><a className="primary-button cloud-start" href="#create">Make my stickers <span>↗</span></a><div className="hero-note">12 reactions · 5 styles · transparent PNGs</div></div><div className="hero-art" aria-hidden="true"><div className="orb orb-one" /><div className="demo-card demo-one"><span>👋</span><strong>Hi!</strong></div><div className="demo-card demo-two"><span>😂</span><strong>LOL</strong></div><div className="demo-card demo-three"><span>😮</span><strong>OMG!</strong></div><span className="sparkle sparkle-one">✦</span><span className="sparkle sparkle-two">✧</span></div></section>
      <section className="flow-layout cloud-flow" id="create"><div className="flow-intro"><span className="step-label">START WITH YOUR PHOTO</span><h2>Meet your <em>sticker self.</em></h2><p>Choose a clear, front-facing photo of one person. Keep the face large and the lighting even.</p><div className="tip-card"><strong>Start with three reactions</strong><p>Free GPUs have queues and daily limits. Each reaction is generated separately. Make a small preview first and continue while quota is available.</p></div><p className="cloud-privacy">Generation uses Black Forest Labs’ public <a href={`https://huggingface.co/spaces/${CLOUD_SPACE}`} target="_blank" rel="noreferrer">Klein Space</a>. Finished packs are saved on this device. Download a ZIP to keep a backup.</p></div>
        <div className="form-card"><label className={`dropzone ${photoUrl ? 'has-photo' : ''}`} htmlFor="cloud-photo">{photoUrl ? <img src={photoUrl} alt="Your portrait reference" /> : <><span className="upload-icon">↑</span><strong>Choose your photo</strong><span>JPEG, PNG or WebP · up to 12 MB</span></>}<input id="cloud-photo" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy || !loaded} onChange={event => { choosePhoto(event.target.files?.[0]); event.target.value = '' }} /></label>
          <label className="cloud-field">Pack name<input value={pack.name} maxLength={80} disabled={busy} onChange={event => setPack({ ...pack, name: event.target.value })} onBlur={() => pack.photo && persist(pack)} /></label>
          <div className="cloud-selects"><label className="cloud-field">Style<select value={pack.style} disabled={busy || pack.stickers.length > 0} onChange={event => setPack({ ...pack, style: event.target.value })}>{Object.keys(STYLES).map(value => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select></label><label className="cloud-field">Tone<select value={pack.tone} disabled={busy || pack.stickers.length > 0} onChange={event => setPack({ ...pack, tone: event.target.value })}>{Object.keys(TONES).map(value => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select></label></div>
          <label className="cloud-check cloud-consent"><input type="checkbox" checked={consent} disabled={busy} onChange={event => setConsent(event.target.checked)} /><span>I have permission to use this photo and agree to send it to Hugging Face for generation.</span></label>
          <label className="cloud-field">Reaction<select value={reaction} disabled={busy} onChange={event => setReaction(event.target.value)}>{REACTIONS.map(item => <option value={item.key} key={item.key}>{item.emoji} {item.caption}</option>)}</select></label>
          <div className="cloud-generate"><button className="primary-button" disabled={!ready} onClick={() => generate([reaction])}>Generate reaction ↗</button><button className="secondary-button" disabled={!ready || !previewKeys.length} onClick={() => generate(previewKeys)}>Preview three</button></div>
          {busy && <button className="text-button cloud-stop" onClick={() => { cancelled.current = true; active.current?.cancel(); setStatus('Stopping after the current request…') }}>Stop generation</button>}
          {status && <p className="cloud-status" role="status" aria-live="polite">{busy && <span className="cloud-spinner" />}{status}</p>}
          {error && <p className="cloud-error" role="alert">{error}</p>}
        </div>
      </section>
      <section className="content-section cloud-collection"><div className="section-heading"><div><span className="eyebrow">MADE BY YOU</span><h2>{pack.name || 'My stickers'}</h2><p>{pack.stickers.length}/12 reactions · saved in this browser</p></div><div className="cloud-generate"><button className="secondary-button" disabled={!pack.stickers.length || busy} onClick={downloadPack}>Download ZIP ↓</button>{missing.length > 0 && pack.stickers.length > 0 && <button className="primary-button" disabled={!ready} onClick={() => generate(missing.slice(0, 3).map(item => item.key))}>Make next {Math.min(3, missing.length)}</button>}</div></div>
        {pack.stickers.length ? <div className="sticker-grid">{REACTIONS.flatMap(item => { const sticker = pack.stickers.find(value => value.key === item.key); return sticker ? [<StickerCard key={`${pack.id}-${item.key}`} sticker={sticker} disabled={busy} change={async changed => persist({ ...pack, stickers: pack.stickers.map(value => value.key === changed.key ? changed : value) })} redraw={() => { if (!consent) { setError('Confirm photo permission above before redrawing.'); document.getElementById('create')?.scrollIntoView({ behavior: 'smooth' }) } else generate([sticker.key]) }} />] : [] })}</div> : <div className="empty-state"><div className="empty-icon">✳</div><h3>Your collection starts here</h3><p>Upload your portrait and generate your first reaction.</p></div>}
        <button className="text-button" disabled={busy} onClick={() => { setPack(newPack()); setConsent(false); setError(''); setStatus(''); document.getElementById('create')?.scrollIntoView({ behavior: 'smooth' }) }}>Start a new pack</button>
        {packs.length > 0 && <label className="cloud-field cloud-saved">Saved packs<select value={packs.some(item => item.id === pack.id) ? pack.id : ''} disabled={busy} onChange={event => { const chosen = packs.find(item => item.id === event.target.value); if (chosen) { setPack(chosen); setConsent(false); setStatus(''); setError('') } }}><option value="" disabled>Choose a saved pack</option>{packs.map(item => <option key={item.id} value={item.id}>{item.name} · {item.stickers.length} stickers</option>)}</select></label>}
      </section>
    </main>
    <footer className="footer"><span>StickerMe · Free cloud demo</span><span>Check faces, hands and transparency before sharing.</span></footer>
  </div>
}
