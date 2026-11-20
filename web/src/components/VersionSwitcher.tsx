/*
 * Copyright (C) 2026 Ellie Wells <elilovescomputers@gmail.com>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronLeft, ChevronRight } from 'lucide-react';
import type { MessageVersion } from '../types';
import { relativeTime } from '../api';

const SOURCE_LABELS: Record<string, string> = {
  original: 'Original',
  edit: 'Edited',
  regenerate: 'Regenerated',
  draft: 'Draft',
};

function preview(version: MessageVersion): string {
  const content = (version.content || '').replace(/\s+/g, ' ').trim();
  if (content) return content;
  const reasoning = (version.reasoning || '').replace(/\s+/g, ' ').trim();
  if (reasoning) return reasoning;
  const tools = (version.tool_events || []).map((event) => event.name).filter(Boolean);
  if (tools.length) return `Used ${tools.join(', ')}`;
  return 'Empty version';
}

export default function VersionSwitcher({
  versions,
  activeVersionId,
  disabled,
  align = 'left',
  onActivate,
}: {
  versions?: MessageVersion[];
  activeVersionId?: string;
  disabled?: boolean;
  align?: 'left' | 'right';
  onActivate: (versionId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!versions || versions.length < 2) return null;

  const ordered = [...versions].sort((a, b) => a.version - b.version);
  const index = Math.max(
    0,
    ordered.findIndex((version) => version.id === activeVersionId),
  );
  const active = ordered[index];
  const canGoBack = !disabled && index > 0;
  const canGoForward = !disabled && index < ordered.length - 1;

  const go = (delta: number) => {
    const next = ordered[index + delta];
    if (next) onActivate(next.id);
  };

  return (
    <div
      className={`version-switcher ${align === 'right' ? 'align-right' : ''}`}
      ref={wrapRef}
    >
      <button
        type="button"
        className="version-arrow"
        onClick={() => go(-1)}
        disabled={!canGoBack}
        aria-label="Previous version"
        title="Previous version"
      >
        <ChevronLeft size={14} />
      </button>
      <button
        type="button"
        className="version-label"
        onClick={() => setOpen((value) => !value)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        title={`Version ${index + 1} of ${ordered.length} — browse versions`}
      >
        {index + 1} / {ordered.length}
      </button>
      <button
        type="button"
        className="version-arrow"
        onClick={() => go(1)}
        disabled={!canGoForward}
        aria-label="Next version"
        title="Next version"
      >
        <ChevronRight size={14} />
      </button>

      {open && (
        <div className="version-menu" role="menu">
          <div className="version-menu-title">Message versions</div>
          {ordered.map((version) => {
            const isActive = version.id === activeVersionId;
            return (
              <button
                key={version.id}
                type="button"
                role="menuitem"
                className={`version-item ${isActive ? 'is-active' : ''}`}
                onClick={() => {
                  onActivate(version.id);
                  setOpen(false);
                }}
              >
                <span className="version-item-num">v{version.version}</span>
                <span className="version-item-body">
                  <span className="version-item-meta">
                    <span>{SOURCE_LABELS[version.source || 'original'] || 'Version'}</span>
                    {version.created_at && <span>· {relativeTime(version.created_at)}</span>}
                  </span>
                  <span className="version-item-preview">{preview(version)}</span>
                </span>
                {isActive && <Check size={14} className="version-check" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
