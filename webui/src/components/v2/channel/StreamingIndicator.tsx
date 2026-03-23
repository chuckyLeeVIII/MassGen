interface StreamingIndicatorProps {
  visible: boolean;
}

export function StreamingIndicator({ visible }: StreamingIndicatorProps) {
  if (!visible) return null;

  return (
    <div className="sticky bottom-0 z-[1] px-4 pb-4 pt-2 animate-v2-fade-in">
      <div className="inline-flex items-center gap-2.5 rounded-full border border-v2-border-subtle bg-v2-surface/70 px-3 py-2 backdrop-blur-sm shadow-[0_10px_24px_rgba(0,0,0,0.16)]">
        <span className="flex gap-1" aria-hidden="true">
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-v2-online" />
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-v2-online" />
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-v2-online" />
        </span>
        <span className="text-sm font-medium text-v2-text-secondary">Generating</span>
      </div>
    </div>
  );
}
