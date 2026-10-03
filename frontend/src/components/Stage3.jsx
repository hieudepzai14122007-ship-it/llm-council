import ReactMarkdown from 'react-markdown';
import './Stage3.css';

const TITLES = {
  fast: 'Quick Answer (council skipped)',
  solo: 'Expert Answer (council skipped)',
};

export default function Stage3({ finalResponse, route }) {
  if (!finalResponse) {
    return null;
  }

  const single = route === 'fast' || route === 'solo';

  return (
    <div className="stage stage3">
      <h3 className="stage-title">{TITLES[route] || 'Stage 3: Final Council Answer'}</h3>
      <div className="final-response">
        <div className="chairman-label">
          {single ? 'Model' : 'Chairman'}: {finalResponse.model.split('/')[1] || finalResponse.model}
        </div>
        <div className="final-text markdown-content">
          <ReactMarkdown>{finalResponse.response}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
