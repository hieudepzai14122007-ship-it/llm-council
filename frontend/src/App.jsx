import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function emptyAnswer() {
  return {
    role: 'assistant',
    stage1: null,
    stage2: null,
    stage3: null,
    metadata: null,
    laya: null,
    usage: null,
    loading: {
      stage1: false,
      stage2: false,
      stage3: false,
    },
  };
}

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [usageSummary, setUsageSummary] = useState(null);

  // Load conversations and usage on mount
  useEffect(() => {
    loadConversations();
    loadUsage();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const loadUsage = async () => {
    try {
      setUsageSummary(await api.getUsage());
    } catch (error) {
      console.error('Failed to load usage:', error);
    }
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  // Apply a change to the answer being streamed (always the last message)
  const updateLastAnswer = (change) => {
    setCurrentConversation((prev) => {
      const messages = [...prev.messages];
      const last = { ...messages[messages.length - 1] };
      last.loading = { ...last.loading };
      change(last);
      messages[messages.length - 1] = last;
      return { ...prev, messages };
    });
  };

  const handleStreamEvent = (eventType, event) => {
    switch (eventType) {
      case 'laya_complete':
        updateLastAnswer((m) => { m.laya = event.data; });
        break;

      case 'stage1_start':
        updateLastAnswer((m) => { m.loading.stage1 = true; });
        break;

      case 'stage1_complete':
        updateLastAnswer((m) => {
          m.stage1 = event.data;
          m.loading.stage1 = false;
        });
        break;

      case 'stage2_start':
        updateLastAnswer((m) => { m.loading.stage2 = true; });
        break;

      case 'stage2_complete':
        updateLastAnswer((m) => {
          m.stage2 = event.data;
          m.metadata = event.metadata;
          m.loading.stage2 = false;
        });
        break;

      case 'stage3_start':
        updateLastAnswer((m) => { m.loading.stage3 = true; });
        break;

      case 'stage3_complete':
        updateLastAnswer((m) => {
          m.stage3 = event.data;
          m.loading.stage3 = false;
        });
        break;

      case 'usage_complete':
        updateLastAnswer((m) => { m.usage = event.data; });
        break;

      case 'title_complete':
        // Reload conversations to get updated title
        loadConversations();
        break;

      case 'complete':
        // Stream complete, reload conversations list and usage totals
        loadConversations();
        loadUsage();
        setIsLoading(false);
        break;

      case 'error':
        console.error('Stream error:', event.message);
        updateLastAnswer((m) => {
          m.stage3 = { model: 'error', response: `Error: ${event.message}` };
          m.loading = { stage1: false, stage2: false, stage3: false };
        });
        setIsLoading(false);
        break;

      default:
        console.log('Unknown event type:', eventType);
    }
  };

  const handleSendMessage = async (content, mode) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    // Optimistically add the question and an empty answer that fills in as events arrive
    setCurrentConversation((prev) => ({
      ...prev,
      messages: [...prev.messages, { role: 'user', content }, emptyAnswer()],
    }));

    try {
      await api.sendMessageStream(currentConversationId, content, mode, handleStreamEvent);
    } catch (error) {
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  // Answer the last question again on another route, replacing the last answer
  const handleRerun = async (mode) => {
    if (!currentConversationId || isLoading) return;

    setIsLoading(true);
    setCurrentConversation((prev) => ({
      ...prev,
      messages: [...prev.messages.slice(0, -1), emptyAnswer()],
    }));

    try {
      await api.rerunStream(currentConversationId, mode, handleStreamEvent);
    } catch (error) {
      console.error('Failed to re-run:', error);
      loadConversation(currentConversationId);
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        usage={usageSummary}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        onRerun={handleRerun}
        isLoading={isLoading}
      />
    </div>
  );
}

export default App;
