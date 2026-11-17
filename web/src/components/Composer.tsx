import { useEffect, useRef, useState } from 'react';
import {
  ArrowUp,
  FileText,
  KeyRound,
  Paperclip,
  Sparkles,
  Square,
  X,
} from 'lucide-react';
import type { Attachment } from '../types';
import { attachmentKind, formatBytes } from '../api';

export default function Composer({
  value,
  onChange,
  attachments,
  uploading,
  streaming,
  providerName,
  providerReady,
  onSend,
  onStop,
  onUpload,
  onRemoveAttachment,
  onOpenSettings,
  inputRef,
}: {
  value: string;
  onChange: (value: string) => void;
  attachments: Attachment[];
  uploading: boolean;
  streaming: boolean;
  providerName: string;
  providerReady: boolean;
  onSend: () => void;
  onStop: () => void;
  onUpload: (files: FileList | File[]) => void;
  onRemoveAttachment: (id: string) => void;
  onOpenSettings: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(220, node.scrollHeight)}px`;
  }, [value, inputRef]);

  const canSend = Boolean(value.trim() || attachments.length) && !uploading && !streaming;

  return (
    <div className="composer-wrap">
      {!providerReady && (
        <button type="button" className="composer-warning" onClick={onOpenSettings}>
          <KeyRound size={15} />
          <span>Add an NVIDIA NIM or OpenRouter API key to start</span>
          <strong>Open settings</strong>
        </button>
      )}

      <div
        className={`composer ${dragging ? 'is-dragging' : ''}`}
        onDragOver={(event) => {
          if (event.dataTransfer?.types.includes('Files')) {
            event.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (event.dataTransfer?.files?.length) onUpload(event.dataTransfer.files);
        }}
      >
        {dragging && <div className="drop-hint">Drop files to attach</div>}

        {(attachments.length > 0 || uploading) && (
          <div className="composer-attachments">
            {attachments.map((attachment) => {
              const kind = attachmentKind(attachment.mime);
              return (
                <span key={attachment.id} className={`pending-file ${kind}`}>
                  {kind === 'image' ? (
                    <img src={attachment.url} alt="" />
                  ) : (
                    <FileText size={15} />
                  )}
                  <span className="pending-name">{attachment.name}</span>
                  <span className="pending-size">{formatBytes(attachment.size)}</span>
                  <button
                    type="button"
                    onClick={() => onRemoveAttachment(attachment.id)}
                    aria-label={`Remove ${attachment.name}`}
                  >
                    <X size={13} />
                  </button>
                </span>
              );
            })}
            {uploading && <span className="pending-file uploading">Uploading…</span>}
          </div>
        )}

        <textarea
          ref={inputRef}
          value={value}
          rows={1}
          placeholder="Message assistant"
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (canSend) onSend();
            }
          }}
          onPaste={(event) => {
            if (event.clipboardData?.files?.length) {
              event.preventDefault();
              onUpload(event.clipboardData.files);
            }
          }}
          aria-label="Message assistant"
        />

        <div className="composer-bar">
          <div className="composer-left">
            <button
              type="button"
              className="icon-btn attach"
              onClick={() => fileRef.current?.click()}
              title="Attach files"
              aria-label="Attach files"
            >
              <Paperclip size={18} />
            </button>
            <button type="button" className="model-pill" onClick={onOpenSettings} title="Model settings">
              <Sparkles size={14} />
              <span>{providerName}</span>
            </button>
          </div>
          <div className="composer-right">
            {streaming ? (
              <button type="button" className="send-btn stop" onClick={onStop} aria-label="Stop generating">
                <Square size={15} fill="currentColor" />
              </button>
            ) : (
              <button
                type="button"
                className="send-btn"
                disabled={!canSend}
                onClick={onSend}
                aria-label="Send message"
              >
                <ArrowUp size={20} strokeWidth={2.4} />
              </button>
            )}
          </div>
        </div>
      </div>

      <input
        ref={fileRef}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          if (event.target.files?.length) onUpload(event.target.files);
          event.target.value = '';
        }}
      />
      <p className="composer-note">
        {streaming ? 'Generating — press the square to stop' : 'Enter to send · Shift+Enter for a new line'}
      </p>
    </div>
  );
}
