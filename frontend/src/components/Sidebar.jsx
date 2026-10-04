import './Sidebar.css';

function UsageSummary({ usage }) {
  if (!usage || usage.answers === 0) return null;
  const r = usage.by_route;
  return (
    <div className="usage-summary">
      <div className="usage-summary-title">Usage so far</div>
      <div>
        {usage.answers} answers: {r.fast.answers} quick · {r.solo.answers} expert · {r.council.answers} council
      </div>
      <div>{usage.calls} Claude calls · ≈ ${usage.cost_usd.toFixed(2)} at API prices</div>
      {usage.saved ? (
        <div className="usage-saved">
          Laya saved ≈ {usage.saved.calls} calls, ${usage.saved.cost_usd.toFixed(2)} and{' '}
          {Math.round(usage.saved.seconds / 60)} min vs. sending everything to the council
        </div>
      ) : (
        <div className="usage-muted">Savings appear after the first council answer</div>
      )}
    </div>
  );
}

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  usage,
}) {
  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
            >
              <div className="conversation-title">
                {conv.title || 'New Conversation'}
              </div>
              <div className="conversation-meta">
                {conv.message_count} messages
              </div>
            </div>
          ))
        )}
      </div>

      <UsageSummary usage={usage} />
    </div>
  );
}
