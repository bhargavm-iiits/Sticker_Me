export const CLOUD_SPACE = 'black-forest-labs/FLUX.2-klein-4B'
export const CLOUD_ORIGIN = 'https://black-forest-labs-flux-2-klein-4b.hf.space'

export const REACTIONS = [
  { key: 'greeting', caption: 'Hi!', emoji: '👋', expression: 'a cheerful smile', gesture: 'waving with one open hand beside the face' },
  { key: 'laughter', caption: 'LOL', emoji: '😂', expression: 'laughing with narrowed eyes and an open smile', gesture: 'one hand on the belly and one wiping a tear of laughter' },
  { key: 'surprise', caption: 'OMG!', emoji: '😮', expression: 'raised eyebrows and a gently open mouth', gesture: 'both hands raised beside the cheeks' },
  { key: 'agreement', caption: 'Yes!', emoji: '👍', expression: 'a confident happy grin', gesture: 'giving a thumbs up with one hand' },
  { key: 'refusal', caption: 'Nope', emoji: '🙅', expression: 'a firm disapproving frown', gesture: 'crossing both forearms in an X in front of the chest' },
  { key: 'thanks', caption: 'Thanks!', emoji: '🙏', expression: 'a grateful gentle smile', gesture: 'pressing both palms together in front of the chest' },
  { key: 'apology', caption: 'Sorry', emoji: '😔', expression: 'remorseful downcast eyes', gesture: 'one hand over the heart' },
  { key: 'affection', caption: 'Miss you', emoji: '❤️', expression: 'a warm affectionate smile', gesture: 'forming a heart shape with both hands in front of the chest' },
  { key: 'waiting', caption: 'Wait...', emoji: '⏳', expression: 'an impatient raised eyebrow', gesture: 'pointing to a wristwatch with the other hand' },
  { key: 'busy', caption: 'Busy!', emoji: '💼', expression: 'a focused expression', gesture: 'typing on a small laptop held at chest level' },
  { key: 'goodnight', caption: 'Good night', emoji: '🌙', expression: 'sleepy closed eyes and a soft smile', gesture: 'resting the cheek on both hands pressed together like a pillow' },
  { key: 'congrats', caption: 'Congrats!', emoji: '🎉', expression: 'a joyful beaming smile', gesture: 'raising both fists beside the head in celebration' },
] as const
export const STYLES: Record<string, string> = {
  realistic: 'a coherent photorealistic portrait with natural skin texture',
  likeness: 'a portrait illustration with subtle line art, realistic facial proportions and natural shading',
  cartoon: 'a clean 2D cartoon illustration with smooth bold outlines and cel shading',
  chibi: 'a cute chibi illustration with a large recognizable head and small upper body',
  comic: 'a colorful comic illustration with ink outlines and cel shading',
}
export const TONES: Record<string, string> = { playful: 'playful, lively and friendly', warm: 'gentle and warm', dramatic: 'theatrical but anatomically natural' }
export type CloudSticker = { key: string; caption: string; artwork: Blob; png: Blob; seed: number; reviewed: boolean; transparent: boolean }
export type CloudPack = { id: string; name: string; style: string; tone: string; photo: Blob | null; stickers: CloudSticker[] }

export function reactionPrompt(key: string, style: string, tone: string): string {
  const reaction = REACTIONS.find(item => item.key === key)
  if (!reaction || !STYLES[style] || !TONES[tone]) throw new Error('Choose a supported reaction, style and tone.')
  return `Use the uploaded portrait as the only reference for this exact person. Preserve their face shape, eye spacing, nose, lips, skin tone, apparent age, hairstyle, facial hair, clothes and visible accessories. Create ${STYLES[style]}. Expression: ${reaction.expression}. Pose: ${reaction.gesture}. Mood: ${TONES[tone]}. One person only. Chest-up framing with the whole head and all hands clearly inside the image, hands close to the chest or face. Exactly two arms and at most two anatomically plausible hands. Plain pure white background. No text, letters, logos, panels, duplicate people or border. Keep the person recognizable.`
}

// Remove white pixels connected to the frame, preserving enclosed white clothing/eyes.
export function removeEdgeWhite(data: Uint8ClampedArray, width: number, height: number, threshold = 230): void {
  const seen = new Uint8Array(width * height)
  const queue = new Int32Array(width * height)
  let head = 0, tail = 0
  function visit(index: number) {
    if (seen[index]) return
    seen[index] = 1
    const offset = index * 4
    const low = Math.min(data[offset], data[offset + 1], data[offset + 2])
    const high = Math.max(data[offset], data[offset + 1], data[offset + 2])
    if (data[offset + 3] === 0 || (low >= threshold && high - low < 25)) queue[tail++] = index
  }
  for (let x = 0; x < width; x++) { visit(x); visit((height - 1) * width + x) }
  for (let y = 0; y < height; y++) { visit(y * width); visit(y * width + width - 1) }
  while (head < tail) {
    const index = queue[head++]
    data[index * 4 + 3] = 0
    const x = index % width, y = Math.floor(index / width)
    if (x) visit(index - 1)
    if (x + 1 < width) visit(index + 1)
    if (y) visit(index - width)
    if (y + 1 < height) visit(index + width)
  }
}

function canvas(width = 512, height = 512) {
  const surface = document.createElement('canvas')
  surface.width = width; surface.height = height
  const context = surface.getContext('2d', { willReadFrequently: true })
  if (!context) throw new Error('Your browser could not create an image canvas.')
  return { surface, context }
}

export async function validatePhoto(file: File): Promise<void> {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Choose a JPEG, PNG or WebP photo.')
  if (file.size > 12 * 1024 * 1024) throw new Error('Choose a photo under 12 MB.')
  const image = await createImageBitmap(file)
  try {
    if (Math.min(image.width, image.height) < 256 || image.width * image.height > 20_000_000) throw new Error('Choose a photo at least 256 pixels wide and tall, and under 20 megapixels.')
  } finally { image.close() }
}

export async function composeCloudSticker(artwork: Blob, caption: string, transparent = true): Promise<Blob> {
  caption = caption.trim()
  if ([...caption].length > 48) throw new Error('Keep captions under 48 characters.')
  const image = await createImageBitmap(artwork)
  const cutout = canvas()
  try { cutout.context.drawImage(image, 0, 0, 512, 512) } finally { image.close() }
  const pixels = cutout.context.getImageData(0, 0, 512, 512)
  if (transparent) removeEdgeWhite(pixels.data, 512, 512)
  cutout.context.putImageData(pixels, 0, 0)
  let left = 512, top = 512, right = 0, bottom = 0
  for (let y = 0; y < 512; y++) for (let x = 0; x < 512; x++) {
    if (pixels.data[(y * 512 + x) * 4 + 3] > 20) { left = Math.min(left, x); right = Math.max(right, x + 1); top = Math.min(top, y); bottom = Math.max(bottom, y + 1) }
  }
  if (right <= left || bottom <= top) throw new Error('The generated image has no usable subject. Try redrawing it.')
  const output = canvas()
  let lines: string[] = [], fontSize = 42
  if (caption) {
    for (; fontSize >= 20; fontSize -= 2) {
      output.context.font = `800 ${fontSize}px Arial, sans-serif`
      lines = []; let line = ''
      for (const word of caption.split(/\s+/)) {
        const candidate = line ? `${line} ${word}` : word
        if (output.context.measureText(candidate).width > 450 && line) { lines.push(line); line = word } else line = candidate
      }
      if (line) lines.push(line)
      if (lines.length <= 2 && lines.every(item => output.context.measureText(item).width <= 450)) break
    }
    if (fontSize < 20) throw new Error('This caption is too wide. Try a shorter caption.')
  }
  const textHeight = caption ? lines.length * (fontSize + 8) + 8 : 0
  const scale = Math.min(466 / (right - left), (466 - textHeight) / (bottom - top))
  const width = Math.round((right - left) * scale), height = Math.round((bottom - top) * scale)
  const x = (512 - width) / 2, y = (512 - height - textHeight) / 2
  const outline = canvas()
  for (let angle = 0; angle < 360; angle += 20) {
    const radians = angle * Math.PI / 180
    outline.context.drawImage(cutout.surface, left, top, right - left, bottom - top, x + 7 * Math.cos(radians), y + 7 * Math.sin(radians), width, height)
  }
  outline.context.globalCompositeOperation = 'source-in'; outline.context.fillStyle = 'white'; outline.context.fillRect(0, 0, 512, 512)
  output.context.drawImage(outline.surface, 0, 0)
  output.context.drawImage(cutout.surface, left, top, right - left, bottom - top, x, y, width, height)
  output.context.font = `800 ${fontSize}px Arial, sans-serif`
  output.context.textAlign = 'center'; output.context.textBaseline = 'top'
  output.context.lineJoin = 'round'; output.context.lineWidth = 8
  output.context.strokeStyle = '#38215f'; output.context.fillStyle = 'white'
  lines.forEach((line, index) => { const textY = y + height + 12 + index * (fontSize + 8); output.context.strokeText(line, 256, textY); output.context.fillText(line, 256, textY) })
  return new Promise((resolve, reject) => output.surface.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not save this sticker.')), 'image/png'))
}

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('stickerme-free-cloud', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('packs', { keyPath: 'id' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('Browser storage is unavailable. Download your stickers before leaving.'))
  })
}

export async function savedCloudPacks(): Promise<CloudPack[]> {
  const db = await database()
  try { return await new Promise((resolve, reject) => { const request = db.transaction('packs').objectStore('packs').getAll(); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error) }) } finally { db.close() }
}

export async function saveCloudPack(pack: CloudPack): Promise<void> {
  const db = await database()
  try { await new Promise<void>((resolve, reject) => { const transaction = db.transaction('packs', 'readwrite'); transaction.objectStore('packs').put(pack); transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(new Error('Could not save to this browser. Download your stickers before leaving.')); transaction.onabort = () => reject(new Error('Browser storage is full. Download your stickers.')) }) } finally { db.close() }
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob), link = document.createElement('a')
  link.href = url; link.download = filename; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
