import { fields } from './fields'

// Presentation metadata only. Scores and persisted cards remain backend-owned.
// Keep existing browser storage identifiers across the product rename.
const prefix = 'ai-sana:pending-readiness:v1:'

export function markReadinessPending(id, pending) {
  try {
    if (pending) localStorage.setItem(prefix + id, '1')
    else localStorage.removeItem(prefix + id)
  } catch { /* Current-tab state works even when browser storage is unavailable. */ }
}

export function isReadinessPending(card) {
  try {
    return localStorage.getItem(prefix + card.id) === '1'
      && !card.published && card.readiness_score === 0
      && fields.every(([key]) => !card[key]?.trim())
  } catch { return false }
}
