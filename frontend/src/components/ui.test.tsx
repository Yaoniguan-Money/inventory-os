import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Badge, Card } from './ui.tsx'

describe('UI primitives', () => {
  it('renders a card with title', () => {
    render(<Card title="库存">内容</Card>)
    expect(screen.getByText('库存')).toBeInTheDocument()
    expect(screen.getByText('内容')).toBeInTheDocument()
  })

  it('renders badges with tone classes', () => {
    render(<Badge tone="red">HIGH</Badge>)
    const badge = screen.getByText('HIGH')
    expect(badge.className).toContain('text-red-300')
  })
})
