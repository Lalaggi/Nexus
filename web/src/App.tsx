import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FolderOpen,
  ListTodo,
  Loader2,
  Menu,
  Plus,
  Settings as SettingsIcon,
  Sparkles,
  X,
} from 'lucide-react';
import { App as NativeApp } from '@capacitor/app';
import { Browser } from '@capacitor/browser';
import { StatusBar, Style } from '@capacitor/status-bar';
import { ApiError, api, streamRequest, uploadFile, type FileTarget } from './api';
import {
  IS_NATIVE,
  forgetServerUrl,
  forgetToken,
  getServerUrl,
  isConfigured,
  rememberToken,
  saveServerUrl,
  serverHost,
} from './server';
import type {
  Attachment,
  Chat,
  FileItem,
  Message,
  SettingsSnapshot,
  StreamEvent,
  TaskItem,
  TaskStatus,
} from './types';
import Sidebar from './components/Sidebar';
import Welcome from './components/Welcome';
import Composer from './components/Composer';
import ChatView from './components/ChatView';
import TasksPanel from './components/TasksPanel';
import FilePreview from './components/FilePreview';
import SettingsDialog, { type SettingsPatch, type TestResult } from './components/SettingsDialog';
import Login from './components/Login';
import Connect from './components/Connect';
import { Brandmark } from './components/Brandmark';
import { useSwipe } from './useGesture';

type Boot = 'loading' | 'login' | 'ready' | 'error';

function providerLabel(settings: SettingsSnapshot | null): string {
  if (!settings) return 'Nemotron';
  const available = settings.providers.filter((p) => p.available);
  if (settings.provider === 'nim') {
    return available.some((p) => p.id === 'nim') ? 'Nemotron · NIM' : 'Nemotron · no key';
  }
  if (settings.provider === 'openrouter') {
    return available.some((p) => p.id === 'openrouter')
      ? 'Nemotron · OpenRouter'
      : 'Nemotron · no key';
  }
  if (available.some((p) => p.id === 'nim')) return 'Nemotron · NIM';
  if (available.some((p) => p.id === 'openrouter')) return 'Nemotron · OpenRouter';
  return 'Nemotron · no key';
}

export default function App() {
  const [boot, setBoot] = useState<Boot>('loading');
  const [bootError, setBootError] = useState('');
  const [connected, setConnected] = useState<boolean | null>(null);
  const [settings, setSettings] = useState<SettingsSnapshot | null>(null);
  const [selectedModelId, setSelectedModelId] = useState<string>('');
  const [searxngOk, setSearxngOk] = useState<boolean | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeChat, setActiveChat] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [goal, setGoal] = useState('');
  const [draft, setDraft] = useState('');
  const [draftAttachments, setDraftAttachments] = useState<Attachment[]>([]);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [panel, setPanel] = useState<'tasks' | 'files' | null>(null);
  const [panelTab, setPanelTab] = useState<'tasks' | 'files'>('tasks');
  const [files, setFiles] = useState<FileItem[]>([]);
  const [fileKind, setFileKind] = useState<'outputs' | 'uploads'>('outputs');
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [preview, setPreview] = useState<FileTarget | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const streamingIdRef = useRef<string | null>(null);

  const availableModels = useMemo(() => {
    if (!settings) return [];
    const models = [...settings.models];
    // Show every custom model added in Settings → Provider in the composer
    // selector, not just the one currently set as custom_model_id.
    for (const custom of settings.custom_models) {
      if (!models.find((m) => m.id === custom.model_id)) {
        models.push({ id: custom.model_id, name: custom.name });
      }
    }
    return models;
  }, [settings]);
  const toastTimer = useRef<number | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const appRef = useRef<HTMLDivElement>(null);
  const loadChatRef = useRef<(id: string) => Promise<void>>(async () => {});

  useEffect(() => {
    if (IS_NATIVE) setConnected(isConfigured());
  }, []);

  useEffect(() => {
    if (IS_NATIVE && connected) {
      const handleStatusChange = async (state: { isExitApp: boolean }) => {
        if (state.isExitApp) {
          // App is being backgrounded/exited; drop the remembered session so a
          // relaunch re-prompts for the server when the token is no longer valid.
          forgetToken();
          setConnected(false);
        }
      };
      (NativeApp as any).addListener('appStatusChange', handleStatusChange);
      return () => (NativeApp as any).removeListener('appStatusChange', handleStatusChange);
    }
    return undefined;
  }, [IS_NATIVE, connected]);

  const handleConnect = async (url: string) => {
    saveServerUrl(url);
    setConnected(true);
    void bootApp();
  };

  const handleSignOut = async () => {
    try {
      await api('/api/logout', { method: 'POST' });
    } catch {
      /* ignore */
    }
    forgetToken();
    setConnected(false);
    setBoot('loading');
    setConnected(false);
  };

  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4500);
  }, []);

  useEffect(() => {
    if (window.innerWidth < 900) setSidebarOpen(false);
    const onPop = () => {
      const id = new URLSearchParams(window.location.search).get('c');
      if (id) void loadChatRef.current(id);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handle = () => setReduceMotion(mq.matches);
    mq.addEventListener('change', handle);
    handle();
    return () => mq.removeEventListener('change', handle);
  }, []);

  // Swipe right from the left edge opens the chats sidebar; swipe left closes it.
  // Passive listeners, so scrolling and taps are never blocked.
  const handleSwipe = useCallback(
    (direction: 'left' | 'right' | 'up' | 'down', distance: number, startX: number) => {
      if (direction === 'right' && startX < 32) {
        setSidebarOpen(true);
      } else if (direction === 'left') {
        setSidebarOpen(false);
      }
    },
    [],
  );
  useSwipe({ element: appRef.current, edge: 'left', threshold: 44, onSwipe: handleSwipe });

  useEffect(() => {
    if (boot === 'ready') window.setTimeout(() => inputRef.current?.focus(), 80);
  }, [boot]);

  const refreshChats = useCallback(async () => {
    try {
      const list = await api<Chat[]>('/api/chats');
      setChats(list);
      setActiveChat((previous) =>
        previous ? list.find((chat) => chat.id === previous.id) ?? previous : previous,
      );
    } catch {
      /* a stale list is harmless */
    }
  }, []);

  const toggleSidebar = useCallback(() => {
    if (!sidebarOpen) void refreshChats();
    setSidebarOpen((value) => !value);
  }, [refreshChats, sidebarOpen]);

  const resetToNew = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    const id = activeIdRef.current;
    if (id) void fetch(`/api/chats/${id}/stop`, { method: 'POST' }).catch(() => {});
    setStreaming(false);
    streamingIdRef.current = null;
    setActiveChat(null);
    activeIdRef.current = null;
    setMessages([]);
    setTasks([]);
    setGoal('');
    setDraft('');
    setDraftAttachments([]);
    setEditingMessageId(null);
    setSelectedModelId(settings?.custom_model_id || settings?.model.id || '');
    setPanel(null);
    setPreview(null);
    setFiles([]);
    window.history.pushState({}, '', '/');
    window.setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  const loadChat = useCallback(
    async (id: string) => {
      if (streaming) {
        notify('Stop the current response before switching chats.');
        return;
      }
      try {
        const data = await api<{ chat: Chat; messages: Message[]; tasks: TaskItem[] }>(
          `/api/chats/${id}`,
        );
        setActiveChat(data.chat);
        activeIdRef.current = data.chat.id;
        setMessages(
          data.messages.filter(
            (message) => message.role === 'user' || message.content || message.tool_events?.length,
          ),
        );
        setTasks(data.tasks);
        setGoal(data.chat.goal || '');
        setSelectedModelId(data.chat.model || settings?.custom_model_id || settings?.model.id || '');
        setPreview(null);
        setFiles([]);
        setEditingMessageId(null);
        window.history.pushState({}, '', `?c=${data.chat.id}`);
        if (window.innerWidth < 900) setSidebarOpen(false);
      } catch (error) {
        notify(error instanceof Error ? error.message : 'Could not open that chat.');
      }
    },
    [notify, streaming],
  );
  loadChatRef.current = loadChat;

  const bootApp = useCallback(async () => {
    setBoot('loading');
    setBootError('');
    try {
      const auth = await api<{ required: boolean; authenticated: boolean }>('/api/auth');
      if (auth.required && !auth.authenticated) {
        setBoot('login');
        return;
      }
      const [snapshot, list] = await Promise.all([
        api<SettingsSnapshot>('/api/settings'),
        api<Chat[]>('/api/chats'),
      ]);
      setSettings(snapshot);
      setSelectedModelId(snapshot.custom_model_id || snapshot.model.id || '');
      setChats(list);
      setBoot('ready');
      const id = new URLSearchParams(window.location.search).get('c');
      if (id) {
        window.setTimeout(() => void loadChatRef.current(id), 0);
      }
      try {
        const health = await api<{ searxng: boolean; sandbox: SettingsSnapshot['sandbox'] }>(
          '/api/health',
        );
        setSearxngOk(health.searxng);
        setSettings((previous) => (previous ? { ...previous, sandbox: health.sandbox } : previous));
      } catch {
        setSearxngOk(false);
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setBoot('login');
        return;
      }
      setBootError(error instanceof Error ? error.message : 'Could not reach the server.');
      setBoot('error');
    }
  }, []);

  useEffect(() => {
    // On native, only boot once a server URL has been saved (or built in);
    // otherwise the Connect screen is shown and bootApp is triggered by
    // handleConnect after the user provides one.
    if (IS_NATIVE && !isConfigured()) return;
    void bootApp();
  }, [bootApp]);

  const login = async (password: string) => {
    const data = await api<{ ok: boolean; token?: string }>('/api/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    });
    if (data.token) rememberToken(data.token);
    await bootApp();
  };

  const startStream = (
    chatId: string,
    path: string,
    method: 'POST',
    body: Record<string, unknown> | undefined,
    userLocalId?: string,
  ) => {
    const localAssistantId = `local-a-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    streamingIdRef.current = localAssistantId;
    let serverAssistantId = localAssistantId;

    const placeholder: Message = {
      id: localAssistantId,
      role: 'assistant',
      content: '',
      reasoning: '',
      tool_events: [],
      attachments: [],
      created_at: new Date().toISOString(),
    };
    setMessages((previous) => [...previous, placeholder]);
    setStreaming(true);

    const pending = { text: '', reasoning: '' };
    let frame: number | null = null;

    const flush = () => {
      frame = null;
      if (!pending.text && !pending.reasoning) return;
      const text = pending.text;
      const reasoning = pending.reasoning;
      pending.text = '';
      pending.reasoning = '';
      setMessages((previous) =>
        previous.map((message) =>
          message.id === localAssistantId
            ? {
                ...message,
                content: message.content + text,
                reasoning: message.reasoning + reasoning,
                retry: undefined,
              }
            : message,
        ),
      );
    };

    const schedule = () => {
      if (frame === null) frame = window.requestAnimationFrame(flush);
    };

    const handleEvent = (event: StreamEvent) => {
      switch (event.type) {
        case 'user_message': {
          const message = event.message as Message;
          if (userLocalId) {
            setMessages((previous) =>
              previous.map((item) => (item.id === userLocalId ? message : item)),
            );
          }
          const chat = event.chat as Chat | undefined;
          if (chat) {
            setActiveChat(chat);
            setChats((previous) =>
              previous.map((item) => (item.id === chat.id ? { ...item, ...chat } : item)),
            );
          }
          break;
        }
        case 'meta': {
          serverAssistantId = String(event.message_id ?? localAssistantId);
          break;
        }
        case 'title': {
          const newTitle = String(event.title ?? '');
          const id = String(event.chat_id ?? '');
          if (newTitle && id) {
            setActiveChat((previous) =>
              previous ? { ...previous, title: newTitle } : previous,
            );
            setChats((previous) =>
              previous.map((item) =>
                item.id === id ? { ...item, title: newTitle } : item,
              ),
            );
          }
          break;
        }
        case 'delta': {
          pending.text += String(event.text ?? '');
          schedule();
          break;
        }
        case 'reasoning': {
          pending.reasoning += String(event.text ?? '');
          schedule();
          break;
        }
        case 'retry': {
          flush();
          setMessages((previous) =>
            previous.map((message) =>
              message.id === localAssistantId
                ? {
                    ...message,
                    retry: {
                      attempt: Number(event.attempt ?? 0) || 1,
                      max_attempts: Number(event.max_attempts ?? 0) || 1,
                      delay_ms: Number(event.delay_ms ?? 0) || 0,
                      message: String(event.message ?? ''),
                    },
                  }
                : message,
            ),
          );
          break;
        }
        case 'tool_call': {
          flush();
          setMessages((previous) =>
            previous.map((message) =>
              message.id === localAssistantId
                ? {
                    ...message,
                    tool_events: [
                      ...message.tool_events,
                      {
                        id: String(event.id ?? ''),
                        name: String(event.name ?? 'tool'),
                        args: (event.args as Record<string, unknown>) ?? {},
                        status: 'running',
                      },
                    ],
                  }
                : message,
            ),
          );
          break;
        }
        case 'tool_result': {
          setMessages((previous) =>
            previous.map((message) =>
              message.id === localAssistantId
                ? {
                    ...message,
                    tool_events: message.tool_events.map((tool) =>
                      tool.id === String(event.id ?? '')
                        ? {
                            ...tool,
                            status: 'done',
                            ok: Boolean(event.ok),
                            summary: String(event.summary ?? ''),
                            duration: Number(event.duration ?? 0) || undefined,
                            data: event.data as typeof tool.data,
                          }
                        : tool,
                    ),
                  }
                : message,
            ),
          );
          break;
        }
        case 'tasks': {
          setTasks((event.tasks as TaskItem[]) ?? []);
          setGoal(String(event.goal ?? ''));
          break;
        }
        case 'error': {
          const text = String(event.message ?? 'Something went wrong.');
          notify(text);
          setMessages((previous) =>
            previous.map((message) =>
              message.id === localAssistantId
                ? { ...message, error: text, retry: undefined }
                : message,
            ),
          );
          break;
        }
        case 'done': {
          if (frame !== null) {
            window.cancelAnimationFrame(frame);
            frame = null;
          }
          pending.text = '';
          pending.reasoning = '';
          const finalContent = String(event.content ?? '');
          const finalReasoning = String(event.reasoning ?? '');
          const finalTools = (event.tool_events as Message['tool_events']) ?? [];
          const cancelled = Boolean(event.cancelled);
          setMessages((previous) =>
            previous.map((message) =>
              message.id === localAssistantId
                ? {
                    ...message,
                    id: serverAssistantId,
                    content:
                      finalContent ||
                      (cancelled || message.content ? message.content : '_Stopped._'),
                    reasoning: finalReasoning || message.reasoning,
                    tool_events: finalTools.length ? finalTools : message.tool_events,
                    duration_ms: Number(event.duration_ms ?? message.duration_ms ?? 0) || undefined,
                    retry: undefined,
                  }
                : message,
            ),
          );
          setStreaming(false);
          streamingIdRef.current = null;
          void refreshChats();
          break;
        }
        default:
          break;
      }
    };

    const controller = new AbortController();
    abortRef.current = controller;

    void streamRequest(
      path,
      {
        method,
        body: body ? JSON.stringify(body) : undefined,
      },
      handleEvent,
      controller.signal,
    )
      .catch((error) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        if (error instanceof ApiError && error.status === 401) {
          setBoot('login');
          return;
        }
        notify(error instanceof Error ? error.message : 'The response stream failed.');
      })
      .finally(() => {
        if (abortRef.current === controller) abortRef.current = null;
        setStreaming(false);
        streamingIdRef.current = null;
        setMessages((previous) =>
          previous.map((message) =>
            message.id === localAssistantId && !message.content && !message.tool_events.length
              ? { ...message, content: '_No response._', retry: undefined }
              : message.id === localAssistantId
                ? { ...message, retry: undefined }
                : message,
          ),
        );
        void refreshChats();
      });
  };

  const send = async () => {
    const content = draft.trim();
    if ((!content && draftAttachments.length === 0) || streaming || uploading) return;

    if (editingMessageId && activeChat) {
      const editId = editingMessageId;
      try {
        await api(`/api/messages/${editId}`, {
          method: 'PATCH',
          body: JSON.stringify({ content }),
        });
      } catch {
        notify('Failed to save edited message.');
        return;
      }
      setEditingMessageId(null);
      setDraft('');
      setDraftAttachments([]);
      return;
    }

    let chat = activeChat;
    if (!chat) {
      try {
        chat = await api<Chat>('/api/chats', {
          method: 'POST',
          body: JSON.stringify({ title: 'New chat' }),
        });
        setActiveChat(chat);
        activeIdRef.current = chat.id;
        setChats((previous) => [chat!, ...previous]);
        window.history.pushState({}, '', `?c=${chat.id}`);
      } catch (error) {
        notify(error instanceof Error ? error.message : 'Could not create a chat.');
        return;
      }
    }

    const localUserId = `local-u-${Date.now()}`;
    const attachments = draftAttachments;
    const optimistic: Message = {
      id: localUserId,
      role: 'user',
      content,
      reasoning: '',
      tool_events: [],
      attachments,
      created_at: new Date().toISOString(),
    };
    setMessages((previous) => [...previous, optimistic]);
    setDraft('');
    setDraftAttachments([]);
    startStream(chat.id, `/api/chats/${chat.id}/messages`, 'POST', {
      content,
      attachment_ids: attachments.map((attachment) => attachment.id),
      model: selectedModelId,
    }, localUserId);
  };

  const regenerate = () => {
    if (!activeChat || streaming) return;
    setMessages((previous) => {
      let lastUser = previous.length - 1;
      while (lastUser >= 0 && previous[lastUser].role !== 'user') lastUser -= 1;
      return previous.slice(0, lastUser + 1);
    });
    startStream(activeChat.id, `/api/chats/${activeChat.id}/regenerate`, 'POST', undefined);
  };

  const stopStream = () => {
    const id = activeIdRef.current;
    if (id) void fetch(`/api/chats/${id}/stop`, { method: 'POST' }).catch(() => {});
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
    const streamingId = streamingIdRef.current;
    setMessages((previous) =>
      previous.map((message) =>
        message.id === streamingId
          ? { ...message, content: message.content || '_Stopped._', retry: undefined }
          : message,
      ),
    );
    streamingIdRef.current = null;
  };

  const upload = async (incoming: FileList | File[]) => {
    const list = Array.from(incoming).slice(0, 10);
    if (!list.length) return;
    setUploading(true);
    for (const file of list) {
      try {
        const attachment = await uploadFile(file);
        setDraftAttachments((previous) => [...previous, attachment]);
      } catch (error) {
        notify(
          `${file.name}: ${error instanceof Error ? error.message : 'upload failed'}`,
        );
      }
    }
    setUploading(false);
    window.setTimeout(() => inputRef.current?.focus(), 40);
  };

  const deleteChat = async (id: string) => {
    const chat = chats.find((item) => item.id === id);
    if (!window.confirm(`Delete "${chat?.title || 'this chat'}"?`)) return;
    try {
      await api(`/api/chats/${id}`, { method: 'DELETE' });
      setChats((previous) => previous.filter((item) => item.id !== id));
      if (activeIdRef.current === id) resetToNew();
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not delete that chat.');
    }
  };

  const fetchFiles = useCallback(async (kind: 'outputs' | 'uploads') => {
    setLoadingFiles(true);
    try {
      const url = activeChat?.id
        ? `/api/files/list?kind=${kind}&chat_id=${encodeURIComponent(activeChat.id)}`
        : `/api/files/list?kind=${kind}`;
      const data = await api<{ files: FileItem[] }>(url);
      setFiles(data.files);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not list files.');
    } finally {
      setLoadingFiles(false);
    }
  }, [notify, activeChat?.id]);

  // Files are scoped to a chat. Refresh when switching chats while the file
  // panel is open so the list never shows another conversation's files.
  useEffect(() => {
    if (panel === null || panelTab !== 'files') return;
    void fetchFiles(fileKind);
  }, [activeChat?.id, fetchFiles, fileKind, panel, panelTab]);

  const openPanel = (tab: 'tasks' | 'files') => {
    if (panel === tab) {
      setPanel(null);
      return;
    }
    setPanel(tab);
    setPanelTab(tab);
  };

  const changeFileKind = (kind: 'outputs' | 'uploads') => {
    setFileKind(kind);
  };

  const updateTask = async (id: string, status: TaskStatus) => {
    try {
      const data = await api<{ tasks: TaskItem[] }>(`/api/tasks/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      setTasks(data.tasks);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not update the task.');
    }
  };

  const saveSettings = async (patch: SettingsPatch) => {
    try {
      const snapshot = await api<SettingsSnapshot>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(patch),
      });
      setSettings(snapshot);
      notify('Settings saved.');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not save settings.');
      throw error;
    }
  };

  const testConnection = async (provider: string): Promise<TestResult> => {
    return api<TestResult>('/api/settings/test', {
      method: 'POST',
      body: JSON.stringify({ provider }),
    });
  };

  const pickSuggestion = (prompt: string) => {
    setDraft(prompt);
    window.setTimeout(() => {
      inputRef.current?.focus();
      const length = prompt.length;
      inputRef.current?.setSelectionRange(length, length);
    }, 40);
  };

  if (IS_NATIVE && connected === false) {
    return (
      <Connect
        initialUrl={getServerUrl() || ''}
        onConnect={handleConnect}
      />
    );
  }

  if (boot === 'login') return <Login onLogin={login} />;

  if (boot === 'loading') {
    return (
      <div className="boot-screen">
        <Brandmark size={48} />
        <Loader2 className="spin" size={20} />
        <span>Starting Nexus…</span>
      </div>
    );
  }

  if (boot === 'error') {
    return (
      <div className="boot-screen">
        <Brandmark size={48} />
        <h1>Cannot reach Nexus</h1>
        <p>{bootError}</p>
        <button type="button" className="btn-primary" onClick={() => void bootApp()}>
          Retry
        </button>
      </div>
    );
  }

  const providerReady = Boolean(settings?.providers.some((provider) => provider.available));
  const taskCount = tasks.filter((task) => task.status === 'in_progress').length;
  const hasMessages = messages.length > 0;

  return (
    <div
      className={`app ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}${
        reduceMotion ? ' reduce-motion' : ''
      }`}
      ref={appRef}
    >
      <Sidebar
        chats={chats}
        activeId={activeChat?.id ?? null}
        settings={settings}
        onSelect={(id) => void loadChat(id)}
        onNew={resetToNew}
        onDelete={(id) => void deleteChat(id)}
        onRefresh={() => void refreshChats()}
        onSettings={() => setSettingsOpen(true)}
        onCollapse={() => setSidebarOpen(false)}
      />
      <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />

      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="icon-btn menu-btn"
              onClick={toggleSidebar}
              aria-label="Toggle sidebar"
            >
              <Menu size={19} />
            </button>
            <div className="topbar-title">
              <h1 title={activeChat?.title}>{activeChat?.title || 'Nexus'}</h1>
              <span className="topbar-sub">
                {activeChat ? `${messages.length} messages` : 'Ready when you are'}
              </span>
            </div>
          </div>
          <div className="topbar-actions">
            <span className={`provider-chip ${providerReady ? 'ready' : ''}`}>
              <i className="dot" />
              {providerReady ? providerLabel(settings).replace('Nemotron · ', '') : 'No key'}
            </span>
            <button
              type="button"
              className={`icon-btn ${panel === 'tasks' ? 'is-active' : ''}`}
              onClick={() => openPanel('tasks')}
              aria-label="Tasks"
              title="Tasks"
            >
              <ListTodo size={18} />
              {taskCount > 0 && <span className="icon-badge">{taskCount}</span>}
            </button>
            <button
              type="button"
              className={`icon-btn ${panel === 'files' ? 'is-active' : ''}`}
              onClick={() => openPanel('files')}
              aria-label="Files"
              title="Files"
            >
              <FolderOpen size={18} />
            </button>
            <button
              type="button"
              className="icon-btn"
              onClick={() => void resetToNew()}
              aria-label="New chat"
              title="New chat"
            >
              <Plus size={18} />
            </button>
          </div>
        </header>

        {hasMessages ? (
          <>
            <ChatView
              messages={messages}
              streaming={streaming}
              onRegenerate={regenerate}
              onEdit={(message) => {
                setDraft(message.content || '');
                setDraftAttachments(message.attachments || []);
                setEditingMessageId(message.id);
                setMessages((previous) =>
                  previous.map((m) =>
                    m.id === message.id ? { ...m, content: message.content || '' } : m,
                  ),
                );
                window.setTimeout(() => inputRef.current?.focus(), 50);
              }}
              onOpenFile={setPreview}
            />
            <div className="composer-dock">
              <Composer
                value={draft}
                onChange={setDraft}
                attachments={draftAttachments}
                uploading={uploading}
                streaming={streaming}
                providerName={providerLabel(settings)}
                providerReady={providerReady}
                models={availableModels}
                selectedModelId={selectedModelId}
                onModelChange={(modelId) => {
                  if (modelId === 'custom') {
                    setSettingsOpen(true);
                    return;
                  }
                  setSelectedModelId(modelId);
                }}
                onSend={() => void send()}
                onStop={stopStream}
                onUpload={(files) => void upload(files)}
                onRemoveAttachment={(id) =>
                  setDraftAttachments((previous) =>
                    previous.filter((attachment) => attachment.id !== id),
                  )
                }
                onOpenSettings={() => setSettingsOpen(true)}
                inputRef={inputRef}
                editing={editingMessageId !== null}
                onCancelEdit={() => {
                  setEditingMessageId(null);
                  setDraft('');
                  setDraftAttachments([]);
                }}
              />
            </div>
          </>
        ) : (
          <div className="landing">
            <Welcome userName={settings?.user_name || 'there'} onPick={pickSuggestion} />
            <Composer
              value={draft}
              onChange={setDraft}
              attachments={draftAttachments}
              uploading={uploading}
              streaming={streaming}
              providerName={providerLabel(settings)}
              providerReady={providerReady}
              models={availableModels}
              selectedModelId={selectedModelId}
              onModelChange={(modelId) => {
                if (modelId === 'custom') {
                  // Open settings to set custom model ID
                  setSettingsOpen(true);
                  return;
                }
                setSelectedModelId(modelId);
              }}
              onSend={() => void send()}
              onStop={stopStream}
              onUpload={(files) => void upload(files)}
              onRemoveAttachment={(id) =>
                setDraftAttachments((previous) =>
                  previous.filter((attachment) => attachment.id !== id),
                )
              }
              onOpenSettings={() => setSettingsOpen(true)}
              inputRef={inputRef}
            />
          </div>
        )}
      </main>

      <TasksPanel
        open={panel !== null}
        tab={panelTab}
        tasks={tasks}
        goal={goal}
        files={files}
        fileKind={fileKind}
        loadingFiles={loadingFiles}
        hasActiveChat={Boolean(activeChat)}
        onTab={(tab) => {
          setPanelTab(tab);
        }}
        onClose={() => setPanel(null)}
        onOpenFile={setPreview}
        onRefreshFiles={() => void fetchFiles(fileKind)}
        onFileKind={changeFileKind}
        onTaskUpdate={(id, status) => void updateTask(id, status)}
      />

      <FilePreview file={preview} onClose={() => setPreview(null)} />

      <SettingsDialog
        open={settingsOpen}
        settings={settings}
        searxngOk={searxngOk}
        onClose={() => setSettingsOpen(false)}
        onSave={saveSettings}
        onTest={testConnection}
        onNotify={notify}
        onSignOut={handleSignOut}
      />

      {toast && (
        <div className="toast" role="status">
          <Sparkles size={15} />
          <span>{toast}</span>
          <button type="button" onClick={() => setToast(null)} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
