import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { removeEdgeWhite, reactionPrompt, REACTIONS } from '../src/cloudSticker.ts'

test('background removal preserves enclosed white details and subject RGB', () => {
  const size = 7, data = new Uint8ClampedArray(size * size * 4).fill(255)
  for (let y = 2; y <= 4; y++) for (let x = 2; x <= 4; x++) {
    if (x === 3 && y === 3) continue
    data.set([90, 45, 120, 255], (y * size + x) * 4)
  }
  removeEdgeWhite(data, size, size)
  assert.equal(data[3], 0)
  assert.deepEqual([...data.slice((3 * size + 3) * 4, (3 * size + 3) * 4 + 4)], [255, 255, 255, 255])
  assert.deepEqual([...data.slice((2 * size + 2) * 4, (2 * size + 2) * 4 + 4)], [90, 45, 120, 255])
})

test('bright colored artwork is retained', () => {
  const data = new Uint8ClampedArray([255, 231, 180, 255, 255, 255, 255, 255])
  removeEdgeWhite(data, 2, 1)
  assert.equal(data[3], 255)
  assert.equal(data[7], 0)
})

test('each of the twelve reactions uses a distinct expression/gesture', () => {
  const prompts = REACTIONS.map(item => reactionPrompt(item.key, 'cartoon', 'warm'))
  assert.equal(new Set(prompts).size, 12)
  assert.ok(prompts.every(prompt => prompt.includes('uploaded portrait') && prompt.includes('pure white background')))
  assert.throws(() => reactionPrompt('unknown', 'cartoon', 'warm'))
  assert.throws(() => reactionPrompt('greeting', 'unknown', 'warm'))
})
