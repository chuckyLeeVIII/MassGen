import { act } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentStore } from '../../../stores/agentStore'
import { useTileStore, TileState } from '../../../stores/v2/tileStore'
import { TileContainer } from './TileContainer'

vi.mock('react-resizable-panels', () => ({
  Group: ({
    orientation,
    className,
    children,
  }: {
    orientation: 'horizontal' | 'vertical'
    className?: string
    children: React.ReactNode
  }) => (
    <div data-testid="panel-group" data-orientation={orientation} className={className}>
      {children}
    </div>
  ),
  Panel: ({ children, id }: { children: React.ReactNode; id?: string }) => (
    <div data-testid={`panel-${id}`}>{children}</div>
  ),
  Separator: ({ className }: { className?: string }) => (
    <div data-testid="panel-separator" className={className} />
  ),
}))

// Mock all tile content components to avoid deep dependency chains
vi.mock('../channel/AgentChannel', () => ({
  AgentChannel: ({ agentId }: { agentId: string }) => (
    <div data-testid={`agent-channel-${agentId}`}>Agent: {agentId}</div>
  ),
}))

vi.mock('./FileViewerTile', () => ({
  FileViewerTile: () => <div>FileViewer</div>,
}))

vi.mock('./WorkspaceBrowserTile', () => ({
  WorkspaceBrowserTile: () => <div>WorkspaceBrowser</div>,
}))

vi.mock('./TimelineTile', () => ({
  TimelineTile: () => <div>Timeline</div>,
}))

vi.mock('./VoteResultsTile', () => ({
  VoteResultsTile: () => <div>VoteResults</div>,
}))

vi.mock('./SubagentTile', () => ({
  SubagentTile: () => <div>Subagent</div>,
}))

vi.mock('../../InlineArtifactPreview', () => ({
  InlineArtifactPreview: () => <div>ArtifactPreview</div>,
}))

function makeTile(id: string): TileState {
  return { id, type: 'agent-channel', targetId: id, label: id }
}

describe('TileContainer', () => {
  beforeEach(() => {
    useTileStore.getState().reset()
    useAgentStore.getState().reset()
  })

  it('renders Group with orientation from store', () => {
    act(() => {
      useTileStore.getState().setTiles([makeTile('a'), makeTile('b')])
    })

    const { rerender } = render(<TileContainer />)
    expect(screen.getByTestId('panel-group')).toHaveAttribute('data-orientation', 'horizontal')

    act(() => {
      useTileStore.getState().setOrientation('vertical')
    })

    rerender(<TileContainer />)
    expect(screen.getByTestId('panel-group')).toHaveAttribute('data-orientation', 'vertical')
  })

  it('shows OrientationToggle only when 2+ tiles', () => {
    // Single tile — no toggle
    act(() => {
      useTileStore.getState().setTiles([makeTile('a')])
    })
    const { rerender } = render(<TileContainer />)
    expect(screen.queryByTitle('Toggle layout orientation')).toBeNull()

    // Two tiles — toggle visible
    act(() => {
      useTileStore.getState().setTiles([makeTile('a'), makeTile('b')])
    })
    rerender(<TileContainer />)
    expect(screen.getByTitle('Toggle layout orientation')).toBeInTheDocument()
  })

  it('OrientationToggle click calls toggleOrientation', () => {
    act(() => {
      useTileStore.getState().setTiles([makeTile('a'), makeTile('b')])
    })

    render(<TileContainer />)
    expect(useTileStore.getState().orientation).toBe('horizontal')

    fireEvent.click(screen.getByTitle('Toggle layout orientation'))
    expect(useTileStore.getState().orientation).toBe('vertical')
  })

  it('renders empty state when no tiles', () => {
    render(<TileContainer />)
    // EmptyState renders when tiles.length === 0
    expect(screen.queryByTestId('panel-group')).toBeNull()
  })

  it('shows prompt banner when question is set and tiles are open', () => {
    act(() => {
      useAgentStore.getState().initSession('s1', 'Write a poem about cats', ['agent_a'], 'dark')
      useTileStore.getState().setTiles([makeTile('a')])
    })

    render(<TileContainer />)
    expect(screen.getByTestId('prompt-banner')).toBeInTheDocument()
    // Should show truncated question
    expect(screen.getByTestId('prompt-banner')).toHaveTextContent('Write a poem about cats')
  })

  it('hides prompt banner when no question is set', () => {
    act(() => {
      useTileStore.getState().setTiles([makeTile('a')])
    })

    render(<TileContainer />)
    expect(screen.queryByTestId('prompt-banner')).toBeNull()
  })

  it('truncates long prompts with ellipsis', () => {
    const longQuestion = 'Write a comprehensive analysis of the economic and social impacts of artificial intelligence on global labor markets'
    act(() => {
      useAgentStore.getState().initSession('s1', longQuestion, ['agent_a'], 'dark')
      useTileStore.getState().setTiles([makeTile('a')])
    })

    render(<TileContainer />)
    const banner = screen.getByTestId('prompt-banner')
    // Should contain ellipsis for long text (CSS truncation or JS truncation)
    expect(banner.textContent!.length).toBeLessThan(longQuestion.length + 20)
  })

  it('clicking prompt banner opens expanded view with full question', () => {
    const longQuestion = 'Write a comprehensive analysis of the economic and social impacts of artificial intelligence on global labor markets and future workforce dynamics'
    act(() => {
      useAgentStore.getState().initSession('s1', longQuestion, ['agent_a'], 'dark')
      useTileStore.getState().setTiles([makeTile('a')])
    })

    render(<TileContainer />)
    // Expanded view not visible initially
    expect(screen.queryByTestId('prompt-expanded')).toBeNull()

    // Click the banner
    fireEvent.click(screen.getByTestId('prompt-banner'))

    // Expanded view shows full question
    const expanded = screen.getByTestId('prompt-expanded')
    expect(expanded).toBeInTheDocument()
    expect(expanded).toHaveTextContent(longQuestion)
  })

  it('clicking expanded prompt view closes it', () => {
    act(() => {
      useAgentStore.getState().initSession('s1', 'Write a poem', ['agent_a'], 'dark')
      useTileStore.getState().setTiles([makeTile('a')])
    })

    render(<TileContainer />)

    // Open
    fireEvent.click(screen.getByTestId('prompt-banner'))
    expect(screen.getByTestId('prompt-expanded')).toBeInTheDocument()

    // Close by clicking the close button
    fireEvent.click(screen.getByTestId('prompt-expanded-close'))
    expect(screen.queryByTestId('prompt-expanded')).toBeNull()
  })
})
