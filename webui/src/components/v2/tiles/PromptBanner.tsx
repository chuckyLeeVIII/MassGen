import { useState } from 'react';
import { cn } from '../../../lib/utils';
import { useAgentStore } from '../../../stores/agentStore';

const MAX_DISPLAY_LENGTH = 60;

function truncateQuestion(q: string): string {
  const single = q.replace(/\n/g, ' ').trim();
  if (single.length <= MAX_DISPLAY_LENGTH) return single;
  return single.slice(0, MAX_DISPLAY_LENGTH - 1) + '\u2026';
}

export function PromptBanner() {
  const question = useAgentStore((s) => s.question);
  const turnNumber = useAgentStore((s) => s.turnNumber);
  const [expanded, setExpanded] = useState(false);

  if (!question) return null;

  return (
    <>
      {/* Collapsed pill */}
      <div
        data-testid="prompt-banner"
        className={cn(
          'absolute top-2 left-1/2 -translate-x-1/2 z-10 max-w-[50%]',
          'flex items-center gap-2 px-2.5 py-1 rounded cursor-pointer',
          'bg-v2-surface-raised/90 backdrop-blur-sm border border-v2-border',
          'text-xs text-v2-text-muted',
          'opacity-70 hover:opacity-100 transition-opacity duration-150'
        )}
        title="Click to view full prompt"
        onClick={() => setExpanded(true)}
      >
        <span className="text-v2-accent font-medium shrink-0">
          Turn {turnNumber}
        </span>
        <span className="text-v2-border">|</span>
        <span className="italic truncate">
          {truncateQuestion(question)}
        </span>
      </div>

      {/* Expanded overlay */}
      {expanded && (
        <div
          data-testid="prompt-expanded"
          className={cn(
            'absolute top-2 right-2 z-20 w-[min(480px,60%)]',
            'rounded-lg border border-v2-border shadow-lg',
            'bg-v2-surface-raised/95 backdrop-blur-sm',
            'animate-v2-tile-enter'
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-v2-border">
            <span className="text-xs font-medium text-v2-accent">
              Turn {turnNumber} — Prompt
            </span>
            <button
              data-testid="prompt-expanded-close"
              onClick={() => setExpanded(false)}
              className={cn(
                'flex items-center justify-center w-5 h-5 rounded',
                'text-v2-text-muted hover:text-v2-text hover:bg-v2-sidebar-hover',
                'transition-colors duration-150'
              )}
            >
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M2 2l8 8M10 2l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          {/* Full question body */}
          <div className="px-3 py-2.5 max-h-48 overflow-y-auto v2-scrollbar">
            <p className="text-sm text-v2-text whitespace-pre-wrap break-words">
              {question}
            </p>
          </div>
        </div>
      )}
    </>
  );
}
