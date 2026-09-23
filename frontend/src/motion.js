import { useSyncExternalStore } from 'react'

const query = '(prefers-reduced-motion: reduce)'
const reducedMotion = () => window.matchMedia(query).matches
const subscribe = (notify) => {
  const media = window.matchMedia(query)
  media.addEventListener('change', notify)
  return () => media.removeEventListener('change', notify)
}

export function useReducedMotion() {
  return useSyncExternalStore(subscribe, reducedMotion, () => true)
}

export function scrollToTop() {
  window.scrollTo({ top: 0, behavior: reducedMotion() ? 'instant' : 'smooth' })
}

export function scrollToSection(element) {
  element?.scrollIntoView({ block: 'start', behavior: reducedMotion() ? 'instant' : 'smooth' })
}
