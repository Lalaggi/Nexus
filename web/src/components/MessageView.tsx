import { useState } from 'react';
import {
  Check,
  Copy,
  Edit2,
  FileText,
  Image as ImageIcon,
  Loader2,
  RotateCcw,
} from 'lucide-react';
import type { Attachment, Message } from '../types';
import { attachmentKind, formatBytes, hostOf, type FileTarget } from '../api';
import Markdown from './Markdown';
import ToolTimeline, { sourceList } from './ToolTimeline';
import { Brandmark } from './Brandmark';
import { openExternal } from '../server';

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

function formatRetryDelay(ms: number): string {
  const seconds = Math.max(1, Math.ceil(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

export default function MessageView({
  message,
  streaming,
  isLast,
  isLastUser,
  onRegenerate,
  onEdit,
  onOpenFile,
}: {
  message: Message;
  streaming?: boolean;
  isLast?: boolean;
  isLastUser?: boolean;
  onRegenerate?: () => void;
  onEdit?: (message: Message) => void;
  onOpenFile?: (file: FileTarget) => void;
}) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const sources = sourceList(message.tool_events || []);
  const hasVisibleContent = Boolean(message.content?.trim());

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  const handleEdit = () => {
    onEdit?.(message);
  };

  const handleRegenerate = () => {
    onRegenerate?.();
  };

  if (isUser) {
    return (
      <div className="message user-message">
        <div className="user-bubble">
          <AttachmentGrid attachments={message.attachments} onOpenFile={onOpenFile} />
          {message.content && <div className="user-text">{message.content}</div>}
        </div>
        {!streaming && hasVisibleContent && (
          <div className="message-actions message-actions-user">
            <button
              type="button"
              onClick={copy}
              title="Copy message"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
            {isLastUser && onEdit && (
              <button
                type="button"
                onClick={handleEdit}
                title="Edit message"
              >
                <Edit2 size={14} />
                <span>Edit</span>
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="message nexus-message">
      <Brandmark />
      <div className="nexus-body">
        <div className="nexus-name">Nexus</div>

        <ToolTimeline
          events={message.tool_events || []}
          reasoning={message.reasoning}
          durationMs={message.duration_ms}
          running={streaming}
          onOpenFile={onOpenFile}
        />

        {message.retry && (
          <div className="retry-status" role="status" title={message.retry.message || undefined}>
            <Loader2 size={13} className="spin" />
            <span>
              Retrying in {formatRetryDelay(message.retry.delay_ms)} · attempt{' '}
              {message.retry.attempt} of {message.retry.max_attempts}
            </span>
          </div>
        )}

        {hasVisibleContent ? (
          <Markdown content={message.content} onOpenFile={onOpenFile} />
        ) : streaming && message.retry ? null : streaming ? (
          <div className="thinking" aria-label="Nexus is thinking">
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
                  onClick={(event) => {
                    event.preventDefault();
                    void openExternal(source.url);
                  }}
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
          <div className="message-actions message-actions-nexus">
            <button
              type="button"
              onClick={copy}
              title="Copy response"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
            {isLast && onRegenerate && (
              <button
                type="button"
                onClick={handleRegenerate}
                title="Regenerate response"
              >
                <RotateCcw size={14} />
                <span>Regenerate</span>
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
