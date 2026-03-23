import { useState } from 'react';
import { cn } from '../../../lib/utils';
import { useAgentStore, selectResolvedFinalAnswer } from '../../../stores/agentStore';

interface FinalAnswerOverlayProps {
  onDismiss: () => void;
}

export function FinalAnswerOverlay({ onDismiss }: FinalAnswerOverlayProps) {
  const finalAnswer = useAgentStore(selectResolvedFinalAnswer);
  const selectedAgent = useAgentStore((s) => s.selectedAgent);
  const agents = useAgentStore((s) => s.agents);
  const voteDistribution = useAgentStore((s) => s.voteDistribution);
  const [followUp, setFollowUp] = useState('');

  const winnerAgent = selectedAgent ? agents[selectedAgent] : null;
  const winnerName = winnerAgent?.modelName
    ? `${selectedAgent} (${winnerAgent.modelName})`
    : selectedAgent;

  const handleFollowUp = (e: React.FormEvent) => {
    e.preventDefault();
    if (!followUp.trim()) return;
    // TODO: Wire to continueConversation
    setFollowUp('');
  };

  return (
    <div className="fixed inset-0 z-50 bg-v2-main flex flex-col animate-v2-overlay-backdrop">
      <div className="flex flex-col h-full animate-v2-overlay-content">
      {/* Header bar */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-v2-border bg-v2-surface shrink-0">
        <div className="flex items-center gap-3">
          {/* Trophy */}
          <span className="text-yellow-400">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2l3.1 6.3L22 9.3l-5 4.9 1.2 7L12 17.6 5.8 21.2 7 14.2 2 9.3l6.9-1L12 2z" />
            </svg>
          </span>
          <div>
            <h2 className="text-lg font-semibold text-v2-text">Final Answer</h2>
            {winnerName && (
              <p className="text-xs text-v2-text-muted">
                Winner: {winnerName}
              </p>
            )}
          </div>
        </div>

        <button
          onClick={onDismiss}
          className={cn(
            'flex items-center gap-2 text-sm px-3 py-1.5 rounded-v2-input',
            'text-v2-text-secondary hover:text-v2-text',
            'bg-v2-surface-raised hover:bg-v2-sidebar-hover',
            'border border-v2-border',
            'transition-colors duration-150'
          )}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M10 4l-4 4 4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back to agents
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto v2-scrollbar">
        <div className="max-w-4xl mx-auto px-6 py-8">
          {/* Vote breakdown */}
          {Object.keys(voteDistribution).length > 0 && (
            <div className="mb-8">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-v2-text-muted mb-3">
                Vote Breakdown
              </h3>
              <div className="flex gap-2 flex-wrap">
                {Object.entries(voteDistribution)
                  .sort(([, a], [, b]) => b - a)
                  .map(([agentId, votes], index) => {
                    const agent = agents[agentId];
                    const isWinner = agentId === selectedAgent;
                    return (
                      <div
                        key={agentId}
                        style={{ animationDelay: `${index * 100 + 200}ms`, animationFillMode: 'forwards' }}
                        className={cn(
                          'opacity-0 animate-v2-stagger-fade-in',
                          'flex items-center gap-2 px-3 py-1.5 rounded-v2-card text-sm',
                          isWinner
                            ? 'bg-yellow-500/10 border border-yellow-500/30 text-yellow-300'
                            : 'bg-v2-surface border border-v2-border text-v2-text-secondary'
                        )}
                      >
                        <span>{agent?.modelName || agentId}</span>
                        <span className="font-semibold">{votes}</span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Answer content */}
          {finalAnswer && finalAnswer !== '__PENDING__' ? (
            <div className="prose prose-invert max-w-none">
              <pre className="whitespace-pre-wrap font-mono text-sm text-v2-text-secondary leading-relaxed">
                {finalAnswer}
              </pre>
            </div>
          ) : (
            <div className="flex items-center justify-center py-12 text-v2-text-muted">
              <div className="flex items-center gap-2">
                <svg className="w-5 h-5 animate-spin" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="8" cy="8" r="6" strokeDasharray="20" strokeDashoffset="5" />
                </svg>
                Generating final answer...
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Follow-up input */}
      <div className="border-t border-v2-border px-6 py-4 bg-v2-surface shrink-0">
        <form onSubmit={handleFollowUp} className="max-w-4xl mx-auto flex gap-3">
          <input
            type="text"
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            placeholder="Ask a follow-up question..."
            className={cn(
              'flex-1 rounded-v2-input bg-[var(--v2-input-bg)] px-4 py-2.5',
              'text-sm text-v2-text placeholder:text-v2-text-muted',
              'border-none outline-none',
              'focus:ring-2 focus:ring-v2-accent/50',
              'transition-shadow duration-150'
            )}
          />
          <button
            type="submit"
            disabled={!followUp.trim()}
            className={cn(
              'rounded-v2-input px-4 py-2.5 text-sm font-medium',
              'bg-v2-accent text-white',
              'hover:bg-v2-accent-hover',
              'disabled:opacity-40 disabled:cursor-not-allowed',
              'transition-colors duration-150'
            )}
          >
            Continue
          </button>
        </form>
      </div>
      </div>
    </div>
  );
}
