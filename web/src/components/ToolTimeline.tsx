import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Check,
  ChevronDown,
  ExternalLink,
  FilePlus2,
  FileText,
  FolderTree,
  Globe2,
  Loader2,
  ListTodo,
  Search,
  Target,
  TerminalSquare,
  Wrench,
} from 'lucide-react';
import type { ToolEvent } from '../types';
import { fileTargetFromHref, formatBytes, hostOf, type FileTarget } from '../api';
import { openExternal } from '../server';

type GroupKind = 'goal' | 'tasks' | 'search' | 'fetch' | 'write' | 'read' | 'list' | 'code' | 'other';

interface Group {
  key: string;
  kind: GroupKind;
  events: ToolEvent[];
}

const KIND_ORDER: Record<string, GroupKind> = {
  set_goal: 'goal',
  task_create: 'tasks',
  task_update: 'tasks',
  task_list: 'tasks',
  web_search: 'search',
  web_fetch: 'fetch',
  write_file: 'write',
  read_file: 'read',
  list_files: 'list',
  sandbox: 'code',
  run_python: 'code',
};

function kindOf(event: ToolEvent): GroupKind {
  return KIND_ORDER[event.name] ?? 'other';
}

function iconFor(kind: GroupKind) {
  switch (kind) {
    case 'goal':
      return <Target size={14} />;
    case 'tasks':
      return <ListTodo size={14} />;
    case 'search':
      return <Search size={14} />;
    case 'fetch':
      return <Globe2 size={14} />;
    case 'write':
      return <FilePlus2 size={14} />;
    case 'read':
      return <FileText size={14} />;
    case 'list':
      return <FolderTree size={14} />;
    case 'code':
      return <TerminalSquare size={14} />;
    default:
      return <Wrench size={14} />;
  }
}

function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function formatDuration(ms?: number): string {
  if (!ms || ms < 0) return '';
  const seconds = ms / 1000;
  if (seconds < 1) return 'under a second';
  if (seconds < 60) {
    const rounded = Math.round(seconds);
    return `${rounded} second${rounded === 1 ? '' : 's'}`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

function groupEvents(events: ToolEvent[]): Group[] {
  const groups: Group[] = [];
  for (const event of events) {
    const kind = kindOf(event);
    const last = groups[groups.length - 1];
    if (last && last.kind === kind) {
      last.events.push(event);
    } else {
      groups.push({ key: `${kind}-${event.id || groups.length}`, kind, events: [event] });
    }
  }
  return groups;
}

function totalDuration(events: ToolEvent[]): number {
  return events.reduce((total, event) => total + (event.duration || 0), 0);
}

function groupTitle(group: Group): string {
  const { kind, events } = group;
  const count = events.length;
  switch (kind) {
    case 'goal':
      return count === 1 ? 'Set goal' : `${count} goals`;
    case 'tasks': {
      const created = events.filter((event) => event.name === 'task_create').length;
      const updated = events.filter((event) => event.name === 'task_update').length;
      if (created && updated) return `Created ${created} & updated ${updated} tasks`;
      if (created) return `Created ${plural(created, 'task')}`;
      if (updated) return `Updated ${plural(updated, 'task')}`;
      return 'Checked tasks';
    }
    case 'search':
      return count === 1 ? 'Searched the web' : `Searched the web ${count} times`;
    case 'fetch':
      return count === 1 ? 'Read 1 web page' : `Read ${count} web pages`;
    case 'write':
      return count === 1 ? 'Wrote 1 file' : `Wrote ${count} files`;
    case 'read':
      return count === 1 ? 'Read 1 file' : `Read ${count} files`;
    case 'list':
      return count === 1 ? 'Listed files' : `Listed files ${count} times`;
    case 'code': {
      const allPython = events.every((event) => event.name === 'run_python');
      if (allPython) return count === 1 ? 'Ran Python' : `Ran Python ${count} times`;
      return count === 1 ? 'Ran a command' : `Ran ${count} commands`;
    }
    default: {
      const name = events[0]?.name ?? 'Tool';
      return count === 1 ? name : `${name} ×${count}`;
    }
  }
}

function groupPreview(group: Group): string {
  const first = group.events[0];
  const args = first?.args || {};
  switch (group.kind) {
    case 'goal':
      return String(args.goal ?? first?.data?.goal ?? '').slice(0, 110);
    case 'tasks':
      return String(
        first?.data?.task?.title ??
          args.title ??
          (group.events.length > 1 ? `${group.events.length} changes` : ''),
      ).slice(0, 110);
    case 'search':
      return group.events
        .map((event) => String(event.data?.query ?? event.args?.query ?? ''))
        .filter(Boolean)
        .join(' · ')
        .slice(0, 110);
    case 'fetch':
      return group.events
        .map((event) => hostOf(String(event.data?.url ?? event.args?.url ?? '')))
        .filter(Boolean)
        .join(' · ')
        .slice(0, 110);
    case 'write':
      return group.events
        .map((event) => String(event.data?.files?.[0]?.name ?? event.args?.path ?? ''))
        .filter(Boolean)
        .join(', ')
        .slice(0, 110);
    case 'read':
      return group.events
        .map((event) => String(event.data?.files?.[0]?.name ?? event.args?.path ?? ''))
        .filter(Boolean)
        .join(', ')
        .slice(0, 110);
    case 'code': {
      const command = String(first?.args?.command ?? first?.args?.code ?? '').trim();
      if (!command) return '';
      const line = command.split('\n').find((part) => part.trim()) ?? command;
      return line.slice(0, 110);
    }
    default:
      return String(first?.summary ?? '').slice(0, 110);
  }
}

function GroupStatus({ events }: { events: ToolEvent[] }) {
  if (events.some((event) => event.status === 'running')) {
    return <Loader2 size={13} className="spin work-status" />;
  }
  if (events.some((event) => event.ok === false)) {
    return <AlertCircle size={13} className="tool-error work-status" />;
  }
  return <Check size={13} className="tool-ok work-status" />;
}

function FileLinks({
  files,
  onOpenFile,
}: {
  files?: Array<{ name: string; path: string; url: string }>;
  onOpenFile?: (file: FileTarget) => void;
}) {
  if (!files?.length) return null;
  return (
    <div className="tool-files">
      {files.map((file) => {
        const target = fileTargetFromHref(file.url);
        // A failed tool used to fabricate {name: "file", path: "", url: ""},
        // which rendered as a bogus extra chip. Ignore empty entries.
        if (!file.path && !file.url) return null;
        return (
          <button
            key={file.path || file.name}
            type="button"
            className="file-chip"
            onClick={() => target && onOpenFile?.(target)}
          >
            <FileText size={14} />
            <span>{file.name}</span>
          </button>
        );
      })}
    </div>
  );
}

function StatusDot({ status }: { status?: string }) {
  const value = status || 'pending';
  return <span className={`task-dot ${value}`} title={value} />;
}

function GoalBody({ event }: { event: ToolEvent }) {
  const goal = String(event.data?.goal ?? event.args?.goal ?? event.summary ?? '');
  if (!goal) return null;
  return <div className="work-text">{goal}</div>;
}

function TasksBody({
  events,
  taskTitles,
}: {
  events: ToolEvent[];
  taskTitles: Map<string, string>;
}) {
  const entries: Array<{ key: string; title: string; status?: string; detail?: string }> = [];
  for (const event of events) {
    if (event.name === 'task_list') {
      for (const task of event.data?.tasks ?? []) {
        entries.push({ key: `list-${task.id}`, title: task.title, status: task.status, detail: task.detail });
      }
      continue;
    }
    const task = event.data?.task;
    const id = String(task?.id ?? event.args?.task_id ?? '');
    const title = String(
      task?.title ??
        event.args?.title ??
        taskTitles.get(id) ??
        (id ? `Task ${id}` : event.summary ?? 'Task'),
    );
    entries.push({
      key: event.id,
      title,
      status: String(task?.status ?? event.args?.status ?? (event.name === 'task_create' ? 'pending' : '')),
      detail: String(task?.detail ?? event.args?.detail ?? ''),
    });
  }
  if (!entries.length) return <div className="work-text muted">{events.map((e) => e.summary).join(' · ')}</div>;
  return (
    <ul className="work-tasks">
      {entries.map((entry) => (
        <li key={entry.key}>
          <StatusDot status={entry.status} />
          <span className="work-task-title">{entry.title}</span>
          {entry.detail && <span className="work-task-detail">{entry.detail}</span>}
        </li>
      ))}
    </ul>
  );
}

function SearchBody({ events }: { events: ToolEvent[] }) {
  const seen = new Set<string>();
  const results = events.flatMap((event) => event.data?.results ?? []).filter((result) => {
    if (!result.url || seen.has(result.url)) return false;
    seen.add(result.url);
    return true;
  });
  if (!results.length) {
    return (
      <div className="work-text muted">
        {events.map((event) => String(event.data?.query ?? event.args?.query ?? '')).filter(Boolean).join(' · ')}
      </div>
    );
  }
  return (
    <div className="search-results">
      {results.map((result) => (
        <a
          key={result.url}
          href={result.url}
          className="search-result"
          onClick={(event) => {
            event.preventDefault();
            void openExternal(result.url);
          }}
        >
          <span className="search-domain">{hostOf(result.url)}</span>
          <span className="search-title">{result.title}</span>
          {result.snippet && <span className="search-snippet">{result.snippet}</span>}
          <ExternalLink size={12} />
        </a>
      ))}
    </div>
  );
}

function FetchBody({ events }: { events: ToolEvent[] }) {
  return (
    <div className="work-links">
      {events.map((event) => {
        const url = String(event.data?.url ?? event.args?.url ?? '');
        if (!url) return null;
        return (
          <a
            key={event.id}
            className="tool-link"
            href={url}
            onClick={(event) => {
              event.preventDefault();
              void openExternal(url);
            }}
          >
            <Globe2 size={14} />
            <span>{String(event.data?.title || hostOf(url))}</span>
            <ExternalLink size={12} />
          </a>
        );
      })}
    </div>
  );
}

function WriteBody({
  events,
  onOpenFile,
}: {
  events: ToolEvent[];
  onOpenFile?: (file: FileTarget) => void;
}) {
  return (
    <div className="work-writes">
      {events.map((event) => {
        const content = String(event.data?.content ?? event.args?.content ?? '');
        return (
          <div key={event.id} className="work-write">
            <FileLinks files={event.data?.files} onOpenFile={onOpenFile} />
            {content && <pre className="tool-pre">{content}</pre>}
            {!event.data?.files?.length && !content && event.summary && (
              <div className="work-text muted">{event.summary}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CodeBody({
  events,
  onOpenFile,
}: {
  events: ToolEvent[];
  onOpenFile?: (file: FileTarget) => void;
}) {
  return (
    <div className="work-code">
      {events.map((event) => {
        const rawArgs = event.args as Record<string, unknown> | undefined;
        const rawData = event.data as Record<string, unknown> | undefined;
        const command =
          String(rawArgs?.command ?? rawArgs?.code ?? '').trim() ||
          (typeof rawData?.command === 'string' ? String(rawData.command).trim() : '');
        return (
          <div key={event.id} className="work-code-item">
            {event.status === 'running' ? (
              <div className="work-text muted">Running…</div>
            ) : (
              <>
                {command && (
                  <div className="tool-command">
                    <span className="tool-command-label">Command</span>
                    <pre className="tool-command-text">{command}</pre>
                  </div>
                )}
                <FileLinks files={event.data?.files} onOpenFile={onOpenFile} />
                {event.data?.stdout && (
                  <div className="tool-stream">
                    <span>stdout</span>
                    <pre>{event.data.stdout}</pre>
                  </div>
                )}
                {event.data?.stderr && (
                  <div className="tool-stream error">
                    <span>stderr</span>
                    <pre>{event.data.stderr}</pre>
                  </div>
                )}
                {typeof event.data?.exit_code === 'number' && event.data.exit_code !== 0 && (
                  <div className="work-text error">Exit code {event.data.exit_code}</div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

function GroupBody({
  group,
  onOpenFile,
  taskTitles,
}: {
  group: Group;
  onOpenFile?: (file: FileTarget) => void;
  taskTitles: Map<string, string>;
}) {
  switch (group.kind) {
    case 'goal':
      return <GoalBody event={group.events[0]} />;
    case 'tasks':
      return <TasksBody events={group.events} taskTitles={taskTitles} />;
    case 'search':
      return <SearchBody events={group.events} />;
    case 'fetch':
      return <FetchBody events={group.events} />;
    case 'write':
      return <WriteBody events={group.events} onOpenFile={onOpenFile} />;
    case 'read':
      return <FileLinks files={group.events.flatMap((event) => event.data?.files ?? [])} onOpenFile={onOpenFile} />;
    case 'list': {
      const files = group.events.flatMap((event) => event.data?.files ?? []);
      const listing = group.events
        .map((event) => event.data?.content ?? '')
        .filter(Boolean)
        .join('\n\n');
      return (
        <>
          <FileLinks files={files} onOpenFile={onOpenFile} />
          {!files.length && listing && <pre className="tool-pre">{listing}</pre>}
        </>
      );
    }
    case 'code':
      return <CodeBody events={group.events} onOpenFile={onOpenFile} />;
    default:
      return (
        <div className="work-text muted">
          {group.events.map((event) => event.summary).filter(Boolean).join(' · ')}
        </div>
      );
  }
}

function WorkGroup({
  group,
  onOpenFile,
  taskTitles,
}: {
  group: Group;
  onOpenFile?: (file: FileTarget) => void;
  taskTitles: Map<string, string>;
}) {
  const running = group.events.some((event) => event.status === 'running');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (running) setOpen(true);
  }, [running]);

  const preview = groupPreview(group);
  const duration = totalDuration(group.events);

  return (
    <details
      className={`work-group ${group.events.some((event) => event.ok === false) ? 'is-error' : ''}`}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span className="work-group-icon">{iconFor(group.kind)}</span>
        <span className="work-group-title">{groupTitle(group)}</span>
        {preview && <span className="work-group-preview">{preview}</span>}
        {duration > 0 && <span className="work-duration">{duration.toFixed(1)}s</span>}
        <GroupStatus events={group.events} />
        <ChevronDown size={13} className="work-chevron" />
      </summary>
      <div className="work-group-body">
        <GroupBody group={group} onOpenFile={onOpenFile} taskTitles={taskTitles} />
      </div>
    </details>
  );
}

export default function ToolTimeline({
  events,
  reasoning,
  durationMs,
  running = false,
  onOpenFile,
}: {
  events: ToolEvent[];
  reasoning?: string;
  durationMs?: number;
  running?: boolean;
  onOpenFile?: (file: FileTarget) => void;
}) {
  const groups = useMemo(() => groupEvents(events), [events]);
  // Keep the work log collapsed by default, both while the model is working and
  // after it finishes. The summary already shows live status and activity; the
  // user can expand it at any time and it stays open until they collapse it.
  const [open, setOpen] = useState(false);

  const taskTitles = useMemo(() => {
    const titles = new Map<string, string>();
    for (const event of events) {
      const task = event.data?.task;
      if (task?.id && task.title) titles.set(String(task.id), String(task.title));
    }
    return titles;
  }, [events]);

  const counts = useMemo(() => {
    const result = {
      goals: 0,
      tasks: 0,
      searches: 0,
      fetches: 0,
      writes: 0,
      reads: 0,
      lists: 0,
      runs: 0,
      sandboxRuns: 0,
      errors: 0,
    };
    const taskIds = new Set<string>();
    let unnamedTasks = 0;
    for (const event of events) {
      if (event.ok === false) result.errors += 1;
      switch (kindOf(event)) {
        case 'goal':
          result.goals += 1;
          break;
        case 'tasks': {
          if (event.name === 'task_create' || event.name === 'task_update') {
            const id = event.data?.task?.id ?? event.args?.task_id;
            if (id) taskIds.add(String(id));
            else unnamedTasks += 1;
          }
          break;
        }
        case 'search':
          result.searches += 1;
          break;
        case 'fetch':
          result.fetches += 1;
          break;
        case 'write':
          result.writes += 1;
          break;
        case 'read':
          result.reads += 1;
          break;
        case 'list':
          result.lists += 1;
          break;
        case 'code':
          result.runs += 1;
          if (event.name === 'sandbox') result.sandboxRuns += 1;
          break;
        default:
          break;
      }
    }
    result.tasks = taskIds.size + unnamedTasks;
    return result;
  }, [events]);

  const parts = useMemo(() => {
    const list: string[] = [];
    if (counts.goals) list.push(plural(counts.goals, 'Goal'));
    if (counts.tasks) list.push(plural(counts.tasks, 'Task'));
    if (counts.searches) {
      list.push(counts.searches === 1 ? 'Searched the Web' : `Searched the Web ×${counts.searches}`);
    }
    if (counts.fetches) list.push(`Read ${plural(counts.fetches, 'Web Page')}`);
    if (counts.writes) list.push(`Wrote ${plural(counts.writes, 'file')}`);
    if (counts.reads) list.push(`Read ${plural(counts.reads, 'file')}`);
    if (counts.lists) list.push(counts.lists === 1 ? 'Listed files' : `Listed files ×${counts.lists}`);
    if (counts.runs) {
      if (counts.sandboxRuns) {
        list.push(counts.runs === 1 ? 'Ran a command' : `Ran ${counts.runs} commands`);
      } else {
        list.push(counts.runs === 1 ? 'Ran Python' : `Ran Python ×${counts.runs}`);
      }
    }
    return list;
  }, [counts]);

  const errorCount = counts.errors;
  const hasReasoning = Boolean(reasoning?.trim());
  if (!groups.length && !hasReasoning && !running) return null;

  const duration = formatDuration(durationMs);
  const title = running ? 'Thinking…' : duration ? `Thought for ${duration}` : 'Thinking complete';

  return (
    <details
      className="worklog"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        {running ? (
          <Loader2 size={15} className="spin worklog-status" />
        ) : errorCount ? (
          <AlertCircle size={15} className="tool-error worklog-status" />
        ) : (
          <Check size={15} className="tool-ok worklog-status" />
        )}
        <span className="worklog-title">{title}</span>
        {parts.length > 0 && <span className="worklog-parts">{parts.join(', ')}</span>}
        {errorCount > 0 && (
          <span className="worklog-errors">{plural(errorCount, 'error')}</span>
        )}
        <ChevronDown size={14} className="worklog-chevron" />
      </summary>
      <div className="worklog-body">
        {hasReasoning && (
          <details className="work-group work-reasoning">
            <summary>
              <span className="work-group-icon reasoning-icon" />
              <span className="work-group-title">Reasoning</span>
              {duration && <span className="work-group-preview">{duration}</span>}
              <ChevronDown size={13} className="work-chevron" />
            </summary>
            <div className="work-group-body">
              <div className="reasoning-body">{reasoning}</div>
            </div>
          </details>
        )}
        {groups.map((group) => (
          <WorkGroup key={group.key} group={group} onOpenFile={onOpenFile} taskTitles={taskTitles} />
        ))}
        {running && !groups.length && !hasReasoning && (
          <div className="work-text muted">Waiting for the model…</div>
        )}
      </div>
    </details>
  );
}

export function sourceList(events: ToolEvent[]): Array<{ title: string; url: string }> {
  const seen = new Set<string>();
  const sources: Array<{ title: string; url: string }> = [];
  for (const event of events) {
    for (const result of event.data?.results ?? []) {
      if (!result.url || seen.has(result.url)) continue;
      seen.add(result.url);
      sources.push({ title: result.title, url: result.url });
    }
    if (event.data?.url && event.name === 'web_fetch' && !seen.has(event.data.url)) {
      seen.add(event.data.url);
      sources.push({ title: event.data.title || hostOf(event.data.url), url: event.data.url });
    }
  }
  return sources.slice(0, 6);
}

export function sumFileBytes(files: Array<{ name: string }>): string {
  return formatBytes(files.reduce((total, file) => total + (('size' in file ? Number(file.size) : 0) || 0), 0));
}
