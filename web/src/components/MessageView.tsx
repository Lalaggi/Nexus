import { useState } from 'react';
import {
  Check,
  Copy,
  Edit2,
  FileText,
  Image as ImageIcon,
  MoreVertical,
  RotateCcw,
} from 'lucide-react';
import type { Attachment, Message } from '../types';
import { attachmentKind, formatBytes, hostOf, type FileTarget } from '../api';
import Markdown from './Markdown';
import ToolTimeline, { sourceList } from './ToolTimeline';
import { Brandmark } from './Brandmark';

function AttachmentGrid({
  attachments,
  onOpenFile,
}: {
  attachments: Attachment[];
  onOpenFile?: (file: FileTarget) => void;
}) {
  if (!attachments.length) return null;
  return (
    <div className="attachments">
      {attachments.map((attachment) => {
        const kind = attachmentKind(attachment.mime);
        const target: FileTarget = {
          kind: 'uploads',
          path: attachment.name,
          name: attachment.name,
          url: attachment.url,
        };
        if (kind === 'image') {
          return (
            <button
              key={attachment.id}
              type="button"
              className="attachment-image"
              onClick={() => onOpenFile?.(target)}
              title={attachment.name}
            >
              <img src={attachment.url} alt={attachment.name} loading="lazy" />
              <span>{attachment.name}</span>
            </button>
          );
        }
        return (
          <button
            key={attachment.id}
            type="button"
            className="file-chip attachment-file"
            onClick={() => onOpenFile?.(target)}
            title={attachment.name}
          >
            {kind === 'pdf' ? <FileText size={15} /> : kind === 'text' ? <FileText size={15} /> : <ImageIcon size={15} />}
            <span className="file-chip-name">{attachment.name}</span>
            <span className="file-chip-size">{formatBytes(attachment.size)}</span>
          </button>
        );
      })}
    </div>
  );
}

export default function MessageView({
  message,
  streaming,
  isLast,
  onRegenerate,
  onEdit,
  onOpenFile,
}: {
  message: Message;
  streaming?: boolean;
  isLast?: boolean;
  onRegenerate?: () => void;
  onEdit?: (message: Message) => void;
  onOpenFile?: (file: FileTarget) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const isUser = message.role === 'user';
  const sources = sourceList(message.tool_events || []);
  const hasVisibleContent = Boolean(message.content?.trim());

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setMenuOpen(false);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  const handleEdit = () => {
    setMenuOpen(false);
    onEdit?.(message);
  };

  const handleRegenerate = () => {
    setMenuOpen(false);
    onRegenerate?.();
  };

  const toggleMenu = () => {
    setMenuOpen((prev) => !prev);
  };

  const closeMenu = () => {
    setMenuOpen(false);
  };

  if (isUser) {
    return (
      <div className="message user-message">
        <div className="user-bubble">
          <AttachmentGrid attachments={message.attachments} onOpenFile={onOpenFile} />
          {message.content && <div className="user-text">{message.content}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="message assistant-message">
      <Brandmark />
      <div className="assistant-body">
        <div className="assistant-name">Assistant</div>

        <ToolTimeline
          events={message.tool_events || []}
          reasoning={message.reasoning}
          durationMs={message.duration_ms}
          running={streaming}
          onOpenFile={onOpenFile}
        />

        {hasVisibleContent ? (
          <Markdown content={message.content} onOpenFile={onOpenFile} />
        ) : streaming ? (
          <div className="thinking" aria-label="Assistant is thinking">
            <span />
            <span />
            <span />
          </div>
        ) : message.error ? (
          <div className="message-error">{message.error}</div>
        ) : null}

        {streaming && hasVisibleContent && <span className="stream-cursor" />}

        {sources.length > 0 && (
          <div className="sources">
            <span className="sources-label">Sources</span>
            <div className="source-row">
              {sources.map((source) => (
                <a
                  key={source.url}
                  href={source.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="source-chip"
                  title={source.title}
                >
                  <span className="source-favicon">{hostOf(source.url).slice(0, 1).toUpperCase()}</span>
                  <span>{hostOf(source.url)}</span>
                </a>
              ))}
            </div>
          </div>
        )}

        {!streaming && hasVisibleContent && (
          <div className="message-actions">
            <button
              type="button"
              className={`message-menu-button ${menuOpen ? 'is-open' : ''}`}
              onClick={toggleMenu}
              aria-label="Message actions"
              aria-expanded={menuOpen}
            >
              <MoreVertical size={16} />
            </button>
            {menuOpen && (
              <div className="message-menu" onClick={closeMenu}>
                <div className="message-menu-inner" onClick={(e) => e.stopPropagation()}>
                  {streaming ? (
                    <button
                      type="button"
                      className="menu-item"
                      onClick={() => {
                        setMenuOpen(false);
                        onRegenerate?.();
                      }}
                    >
                      <span>Stop generating</span>
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="menu-item"
                        onClick={copy}
                      >
                        <Copy size={14} />
                        <span>{copied ? 'Copied' : 'Copy'}</span>
                      </button>
                      {isLast && onEdit && (
                        <button
                          type="button"
                          className="menu-item"
                          onClick={handleEdit}
                        >
                          <Edit2 size={14} />
                          <span>Edit</span>
                        </button>
                      )}
                      {isLast && onRegenerate && (
                        <button
                          type="button"
                          className="menu-item"
                          onClick={handleRegenerate}
                        >
                          <RotateCcw size={14} />
                          <span>Regenerate</span>
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
