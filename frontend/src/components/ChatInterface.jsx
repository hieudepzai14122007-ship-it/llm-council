import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import './ChatInterface.css';

const ROUTE_LABELS = {
  fast: 'Quick answer (Haiku)',
  solo: 'One expert (Sonnet)',
  council: 'Full council',
};

const MODE_OPTIONS = [
  ['auto', 'Auto: Laya decides'],
  ['fast', ROUTE_LABELS.fast],
  ['solo', ROUTE_LABELS.solo],
  ['council', ROUTE_LABELS.council],
];

function LayaBadge({ laya }) {
  const pct = (x) => (x == null ? '' : ` (${Math.round(x * 100)}%)`);
  return (
    <div className={`laya-badge ${laya.route}`}>
      <strong>Laya</strong>
      {laya.complexity != null && <span>complexity {laya.complexity.toFixed(1)}/5</span>}
      {laya.route !== 'fast' && <span>topic: {laya.domain}{pct(laya.domain_confidence)}</span>}
      <span>
        → {laya.route === 'council' ? `council: ${laya.members.join(', ')}` : laya.members[0]}
      </span>
      {laya.latency_ms != null && <span className="laya-muted">{laya.latency_ms} ms</span>}
      <span className="laya-muted">
        {laya.override
          ? `you chose ${ROUTE_LABELS[laya.route].toLowerCase()}; Laya said ${laya.laya_route}`
          : laya.reason}
      </span>
    </div>
  );
}

function formatTokens(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
}

function UsageLine({ usage }) {
  return (
    <div className="usage-line">
      {usage.calls} Claude call{usage.calls === 1 ? '' : 's'} ·{' '}
      {formatTokens(usage.input_tokens)} tokens in / {formatTokens(usage.output_tokens)} out ·{' '}
      ≈ ${usage.cost_usd.toFixed(3)} at API prices · {Math.round(usage.seconds)} s
    </div>
  );
}

function RerunBar({ route, onRerun }) {
  return (
    <div className="rerun-bar">
      <span>Not the right depth? Answer again with:</span>
      {['fast', 'solo', 'council']
        .filter((r) => r !== route)
        .map((r) => (
          <button key={r} className="rerun-button" onClick={() => onRerun(r)}>
            {ROUTE_LABELS[r]}
          </button>
        ))}
    </div>
  );
}

export default function ChatInterface({
  conversation,
  onSendMessage,
  onRerun,
  isLoading,
}) {
  const [input, setInput] = useState('');
  const [mode, setMode] = useState('auto');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input, mode);
      setInput('');
      setMode('auto');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  const lastIndex = conversation.messages.length - 1;

  return (
    <div className="chat-interface">
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Council</div>

                  {/* Laya gatekeeper decision */}
                  {msg.laya && <LayaBadge laya={msg.laya} />}

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                    />
                  )}

                  {/* Stage 3 (or the single answer on the fast / solo routes) */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>
                        {msg.laya?.route === 'council'
                          ? 'Running Stage 3: Final synthesis...'
                          : `Answering with ${msg.laya?.members?.[0] ?? 'one model'}...`}
                      </span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} route={msg.laya?.route} />}

                  {msg.usage && <UsageLine usage={msg.usage} />}

                  {index === lastIndex && !isLoading && msg.stage3 && msg.laya && (
                    <RerunBar route={msg.laya.route} onRerun={onRerun} />
                  )}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Working on it...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="input-form" onSubmit={handleSubmit}>
        <textarea
          className="message-input"
          placeholder={
            conversation.messages.length === 0
              ? 'Ask your question... (Shift+Enter for new line, Enter to send)'
              : 'Ask a follow-up... (Shift+Enter for new line, Enter to send)'
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          rows={3}
        />
        <div className="send-controls">
          <select
            className="mode-select"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            disabled={isLoading}
            title="Who answers this message"
          >
            {MODE_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <button
            type="submit"
            className="send-button"
            disabled={!input.trim() || isLoading}
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
