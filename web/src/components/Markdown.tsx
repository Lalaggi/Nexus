import { useEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { Check, Copy } from 'lucide-react';
import { fileTargetFromHref, type FileTarget } from '../api';
import { copyText } from '../clipboard';
import { openExternal } from '../server';

function hastText(node: any): string {
  if (!node) return '';
  if (typeof node.value === 'string') return node.value;
  const children = node.children ?? [];
  return children.map(hastText).join('');
}

/**
 * react-markdown's default transform only permits http(s), mailto and a few
 * other schemes, so it silently drops the file:// links the model produces.
 * Allow file:// explicitly but keep everything else on the same safe list.
 */
const SAFE_PROTOCOL = /^(https?|ircs?|mailto|xmpp|file)$/i;

function safeUrlTransform(value: string): string {
  const colon = value.indexOf(':');
  const questionMark = value.indexOf('?');
  const numberSign = value.indexOf('#');
  const slash = value.indexOf('/');
  if (
    colon === -1 ||
    (slash !== -1 && colon > slash) ||
    (questionMark !== -1 && colon > questionMark) ||
    (numberSign !== -1 && colon > numberSign) ||
    SAFE_PROTOCOL.test(value.slice(0, colon))
  ) {
    return value;
  }
  return '';
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'error'>('idle');
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    const ok = await copyText(text);
    setState(ok ? 'copied' : 'error');
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState('idle'), 1600);
  };

  return (
    <button
      type="button"
      className="code-copy"
      aria-label={state === 'error' ? 'Copy failed' : 'Copy code'}
      onClick={copy}
    >
      {state === 'copied' ? <Check size={14} /> : <Copy size={14} />}
      <span>{state === 'copied' ? 'Copied' : state === 'error' ? 'Copy failed' : 'Copy'}</span>
    </button>
  );
}

interface MarkdownProps {
  content: string;
  onOpenFile?: (file: FileTarget) => void;
}

export default function Markdown({ content, onOpenFile }: MarkdownProps) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        urlTransform={safeUrlTransform}
        components={{
          a({ href, children, ...props }) {
            const target = href ? fileTargetFromHref(href) : null;
            if (target) {
              return (
                <a
                  href={target.url}
                  className="file-link"
                  onClick={(event) => {
                    if (onOpenFile) {
                      event.preventDefault();
                      onOpenFile(target);
                    }
                  }}
                  {...props}
                >
                  {children}
                </a>
              );
            }
            if (href?.startsWith('file:')) {
              // A file link outside the outputs/uploads roots: show it as text
              // rather than letting the browser navigate to a dead file URL.
              return <span className="file-link-unavailable">{children}</span>;
            }
            return (
              <a
                href={href}
                onClick={(event) => {
                  event.preventDefault();
                  void openExternal(href ?? '');
                }}
                {...props}
              >
                {children}
              </a>
            );
          },
          pre({ node, children }) {
            const element: any = node;
            const text = hastText(element);
            const codeNode = element?.children?.find((child: any) => child.tagName === 'code');
            const classes = codeNode?.properties?.className ?? [];
            const languageClass = Array.isArray(classes)
              ? classes.find((c: any) => String(c).startsWith('language-'))
              : null;
            const language =
              languageClass
                ? String(languageClass).replace('language-', '')
                : '';
            return (
              <div className="code-block">
                <div className="code-head">
                  <span>{language || 'code'}</span>
                  <CopyButton text={text} />
                </div>
                <pre>{children}</pre>
              </div>
            );
          },
          table({ children }) {
            return (
              <div className="table-wrap">
                <table>{children}</table>
              </div>
            );
          },
          img({ src, alt }) {
            const target = typeof src === 'string' ? fileTargetFromHref(src) : null;
            const source = target ? target.url : src;
            return (
              <a
                href={source}
                onClick={(event) => {
                  event.preventDefault();
                  void openExternal(source ?? '');
                }}
              >
                <img src={source} alt={alt ?? ''} loading="lazy" />
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export function InlineMarkdown({ children }: { children: ReactNode }) {
  return <div className="markdown inline">{children}</div>;
}
