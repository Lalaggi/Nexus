import { useEffect, useState } from 'react';
import { Download, ExternalLink, X } from 'lucide-react';
import Markdown from './Markdown';
import type { FileTarget } from '../api';

const TEXT_EXT = /\.(md|markdown|txt|log|csv|tsv|json|jsonl|ya?ml|toml|ini|cfg|py|ts|tsx|js|jsx|css|html?|xml|sh|sql|rs|go|java|c|h|cpp|rb|tex|rst|srt|vtt)$/i;
const CODE_EXT = /\.(py|ts|tsx|js|jsx|css|html?|xml|sh|sql|rs|go|java|c|h|cpp|rb|json|ya?ml|toml)$/i;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|avif|svg|bmp)$/i;

function mimeOf(name: string, provided?: string): string {
  if (provided) return provided;
  if (/\.md$/i.test(name)) return 'text/markdown';
  if (/\.pdf$/i.test(name)) return 'application/pdf';
  if (IMAGE_EXT.test(name)) return 'image/*';
  if (/\.csv$/i.test(name)) return 'text/csv';
  if (/\.json$/i.test(name)) return 'application/json';
  return TEXT_EXT.test(name) ? 'text/plain' : 'application/octet-stream';
}

export default function FilePreview({
  file,
  onClose,
}: {
  file: FileTarget | null;
  onClose: () => void;
}) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const mime = file ? mimeOf(file.name, (file as FileTarget & { mime?: string }).mime) : '';
  const isText = Boolean(file && (mime.startsWith('text/') || mime.includes('json') || mime.includes('xml') || TEXT_EXT.test(file.name)));
  const isMarkdown = Boolean(file && /\.(md|markdown)$/i.test(file.name));
  const isImage = Boolean(file && (mime.startsWith('image/') || IMAGE_EXT.test(file.name)));
  const isPdf = Boolean(file && (mime === 'application/pdf' || /\.pdf$/i.test(file.name)));
  const isVideo = Boolean(file && mime.startsWith('video/'));
  const isAudio = Boolean(file && mime.startsWith('audio/'));

  useEffect(() => {
    setText(null);
    setError(null);
    if (!file || !isText) return;
    const controller = new AbortController();
    setLoading(true);
    fetch(file.url, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((value) => setText(value))
      .catch((err) => {
        if (err.name !== 'AbortError') setError(String(err.message || err));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [file?.url, isText]);

  useEffect(() => {
    if (!file) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [file, onClose]);

  if (!file) return null;

  return (
    <>
      <div className="sheet-backdrop preview-backdrop" onClick={onClose} />
      <aside className="sheet preview-sheet" aria-label={`Preview of ${file.name}`}>
        <header className="sheet-head preview-head">
          <div className="preview-title">
            <span className="sheet-kicker">{file.kind}</span>
            <h2 title={file.path}>{file.name}</h2>
          </div>
          <div className="preview-actions">
            <a className="icon-btn" href={file.url} target="_blank" rel="noreferrer" title="Open raw">
              <ExternalLink size={17} />
            </a>
            <a className="icon-btn" href={`${file.url}?download=1`} title="Download" download>
              <Download size={17} />
            </a>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close preview">
              <X size={18} />
            </button>
          </div>
        </header>
        <div className="preview-body">
          {isImage && <img className="preview-image" src={file.url} alt={file.name} />}
          {isPdf && <iframe className="preview-pdf" src={file.url} title={file.name} />}
          {isVideo && <video className="preview-video" src={file.url} controls />}
          {isAudio && <audio src={file.url} controls />}
          {isText && (
            <>
              {loading && <div className="preview-loading">Loading…</div>}
              {error && <div className="message-error">Could not load file: {error}</div>}
              {text !== null &&
                (isMarkdown ? (
                  <div className="preview-markdown">
                    <Markdown content={text} />
                  </div>
                ) : (
                  <pre className={`preview-code ${CODE_EXT.test(file.name) ? 'code' : ''}`}>{text}</pre>
                ))}
            </>
          )}
          {!isImage && !isPdf && !isText && !isVideo && !isAudio && (
            <div className="preview-unsupported">
              <p>No inline preview for this file type.</p>
              <a className="btn-primary" href={`${file.url}?download=1`} download>
                <Download size={16} />
                Download {file.name}
              </a>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
