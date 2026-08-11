import { describe, expect, it } from 'vitest'
import { fmtDate, fmtMoney, fmtQty } from './format.ts'

describe('format helpers', () => {
  it('formats money with CNY symbol and 2 decimals', () => {
    expect(fmtMoney('116.5')).toBe('¥116.50')
    expect(fmtMoney(null)).toBe('—')
  })

  it('formats quantities with thousands separators', () => {
    expect(fmtQty('1200')).toBe('1,200')
    expect(fmtQty(undefined)).toBe('—')
  })

  it('formats dates without crashing on empty input', () => {
    expect(fmtDate(null)).toBe('—')
    expect(fmtDate('2026-08-11T08:00:00Z')).toContain('08/11')
  })
})
