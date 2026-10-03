/**
 * API client for the LLM Council backend.
 */

const API_BASE = 'http://127.0.0.1:8001';

/**
 * POST a JSON body and call onEvent(type, event) for each Server-Sent Event.
 */
async function streamEvents(path, body, onEvent) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    // An event can arrive split across chunks: only parse complete lines.
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6));
          onEvent(event.type, event);
        } catch (e) {
          console.error('Failed to parse SSE event:', e);
        }
      }
    }
  }
}

export const api = {
  /**
   * List all conversations.
   */
  async listConversations() {
    const response = await fetch(`${API_BASE}/api/conversations`);
    if (!response.ok) {
      throw new Error('Failed to list conversations');
    }
    return response.json();
  },

  /**
   * Create a new conversation.
   */
  async createConversation() {
    const response = await fetch(`${API_BASE}/api/conversations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error('Failed to create conversation');
    }
    return response.json();
  },

  /**
   * Get a specific conversation.
   */
  async getConversation(conversationId) {
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}`
    );
    if (!response.ok) {
      throw new Error('Failed to get conversation');
    }
    return response.json();
  },

  /**
   * Usage totals and estimated savings.
   */
  async getUsage() {
    const response = await fetch(`${API_BASE}/api/usage`);
    if (!response.ok) {
      throw new Error('Failed to get usage');
    }
    return response.json();
  },

  /**
   * Send a message and receive streaming updates.
   * @param {string} conversationId - The conversation ID
   * @param {string} content - The message content
   * @param {string} mode - "auto" (Laya decides), "fast", "solo" or "council"
   * @param {function} onEvent - Callback function for each event: (eventType, data) => void
   */
  sendMessageStream(conversationId, content, mode, onEvent) {
    return streamEvents(
      `/api/conversations/${conversationId}/message/stream`,
      { content, mode },
      onEvent
    );
  },

  /**
   * Answer the last question again on a different route, replacing the last answer.
   */
  rerunStream(conversationId, mode, onEvent) {
    return streamEvents(
      `/api/conversations/${conversationId}/rerun/stream`,
      { mode },
      onEvent
    );
  },
};
