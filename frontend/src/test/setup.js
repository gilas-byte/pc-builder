import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { setLanguage } from '../i18n/index.jsx'

window.scrollTo = () => {}  // jsdom não implementa

afterEach(() => {
  cleanup()
  setLanguage('pt-BR')
  vi.restoreAllMocks()
  window.location.hash = ''
})
