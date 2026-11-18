import { useMemo, useRef, useState } from 'react';
import { MessageSquare, PanelLeftClose, Plus, Search, Settings, Trash2, X } from 'lucide-react';
import type { Chat, SettingsSnapshot } from '../types';
import { relativeTime } from '../api';

function initials(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join('') || 'U'
  );
}

export default function Sidebar({
  chats,
  activeId,
  settings,
  onSelect,
  onNew,
  onDelete,
  onSettings,
  onCollapse,
}: {
  chats: Chat[];
  activeId: string | null;
  settings: SettingsSnapshot | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onSettings: () => void;
  onCollapse: () => void;
}) {
  const [searching, setSearching] = useState(false);
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return chats;
    return chats.filter(
      (chat) =>
        chat.title.toLowerCase().includes(needle) ||
        (chat.preview ?? '').toLowerCase().includes(needle),
    );
  }, [chats, query]);

  const provider = settings?.provider === 'nim' ? 'NIM' : settings?.provider === 'openrouter' ? 'OpenRouter' : 'Auto';

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        {searching ? (
          <div className="sidebar-search">
            <Search size={16} />
            <input
              ref={inputRef}
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search chats"
              aria-label="Search chats"
            />
            <button
              type="button"
              className="icon-btn tiny"
              onClick={() => {
                setSearching(false);
                setQuery('');
              }}
              aria-label="Close search"
            >
              <X size={15} />
            </button>
          </div>
        ) : (
          <div className="sidebar-tools">
            <button
              type="button"
              className="icon-btn"
              onClick={() => {
                setSearching(true);
                window.setTimeout(() => inputRef.current?.focus(), 30);
              }}
              aria-label="Search chats"
              title="Search chats"
            >
              <Search size={18} />
            </button>
            <button
              type="button"
              className="icon-btn collapse-btn"
              onClick={onCollapse}
              aria-label="Collapse sidebar"
              title="Collapse sidebar"
            >
              <PanelLeftClose size={18} />
            </button>
          </div>
        )}
      </div>

      <button type="button" className="new-chat" onClick={onNew}>
        <Plus size={17} />
        <span>New chat</span>
      </button>

      <h2 className="sidebar-heading">Chats</h2>

      <div className="chat-list">
        {filtered.length === 0 && (
          <div className="chat-list-empty">
            <MessageSquare size={20} />
            <span>{query ? 'No matching chats' : 'Your conversations will appear here'}</span>
          </div>
        )}
        {filtered.map((chat) => (
          <div key={chat.id} className={`chat-item ${chat.id === activeId ? 'is-active' : ''}`}>
            <button type="button" className="chat-open" onClick={() => onSelect(chat.id)}>
              <span className="chat-title">{chat.title || 'New chat'}</span>
              <span className="chat-meta">
                {chat.preview ? <span className="chat-preview">{chat.preview}</span> : null}
                <span className="chat-time">{relativeTime(chat.updated_at)}</span>
              </span>
            </button>
            <button
              type="button"
              className="chat-delete"
              aria-label={`Delete ${chat.title}`}
              title="Delete chat"
              onClick={() => onDelete(chat.id)}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      <div className="sidebar-footer">
        <span className="avatar" aria-hidden="true">
          {initials(settings?.user_name ?? 'User')}
        </span>
        <div className="user-meta">
          <span className="user-name">{settings?.user_name ?? 'User'}</span>
          <span className="provider-label">
            <i className={settings?.providers.some((p) => p.available) ? 'dot on' : 'dot'} />
            {settings?.providers.some((p) => p.available) ? `Nemotron · ${provider}` : 'Add an API key'}
          </span>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onSettings}
          aria-label="Settings"
          title="Settings"
        >
          <Settings size={17} />
        </button>
      </div>
    </aside>
  );
}
