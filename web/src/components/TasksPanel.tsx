import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  FileCode2,
  FileText,
  Image as ImageIcon,
  ListTodo,
  Loader2,
  RefreshCw,
  X,
} from 'lucide-react';
import type { FileItem, TaskItem, TaskStatus } from '../types';
import { formatBytes, relativeTime } from '../api';

function statusIcon(status: TaskStatus) {
  switch (status) {
    case 'done':
      return <CheckCircle2 size={18} />;
    case 'in_progress':
      return <Loader2 size={18} className="spin" />;
    case 'blocked':
      return <AlertTriangle size={18} />;
    default:
      return <Circle size={18} />;
  }
}

function nextStatus(status: TaskStatus): TaskStatus {
  if (status === 'pending') return 'in_progress';
  if (status === 'in_progress') return 'done';
  if (status === 'blocked') return 'in_progress';
  return 'pending';
}

function fileIcon(file: FileItem) {
  if (file.mime.startsWith('image/')) return <ImageIcon size={16} />;
  if (
    file.mime.includes('javascript') ||
    file.mime.includes('json') ||
    file.mime.includes('xml') ||
    /\.(py|ts|tsx|js|jsx|css|html|sh|sql|yml|yaml|toml)$/i.test(file.name)
  ) {
    return <FileCode2 size={16} />;
  }
  return <FileText size={16} />;
}

export default function TasksPanel({
  open,
  tab,
  tasks,
  goal,
  files,
  fileKind,
  loadingFiles,
  onTab,
  onClose,
  onOpenFile,
  onRefreshFiles,
  onFileKind,
  onTaskUpdate,
}: {
  open: boolean;
  tab: 'tasks' | 'files';
  tasks: TaskItem[];
  goal: string;
  files: FileItem[];
  fileKind: 'outputs' | 'uploads';
  loadingFiles: boolean;
  onTab: (tab: 'tasks' | 'files') => void;
  onClose: () => void;
  onOpenFile: (file: FileItem) => void;
  onRefreshFiles: () => void;
  onFileKind: (kind: 'outputs' | 'uploads') => void;
  onTaskUpdate: (id: string, status: TaskStatus) => void;
}) {
  const done = tasks.filter((task) => task.status === 'done').length;
  const active = tasks.filter((task) => task.status === 'in_progress').length;
  const percent = tasks.length ? Math.round((done / tasks.length) * 100) : 0;

  if (!open) return null;

  return (
    <>
      <div className="sheet-backdrop" onClick={onClose} />
      <aside className="sheet tasks-sheet" aria-label="Tasks and files">
        <header className="sheet-head">
          <div>
            <span className="sheet-kicker">Workspace</span>
            <h2>{tab === 'tasks' ? 'Tasks' : 'Files'}</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close panel">
            <X size={18} />
          </button>
        </header>

        <div className="segmented">
          <button
            type="button"
            className={tab === 'tasks' ? 'is-active' : ''}
            onClick={() => onTab('tasks')}
          >
            <ListTodo size={15} />
            Tasks
            {active > 0 && <span className="badge">{active}</span>}
          </button>
          <button
            type="button"
            className={tab === 'files' ? 'is-active' : ''}
            onClick={() => onTab('files')}
          >
            <FileText size={15} />
            Files
          </button>
        </div>

        {tab === 'tasks' ? (
          <div className="sheet-body">
            {goal && (
              <div className="goal-card">
                <span className="card-kicker">Goal</span>
                <p>{goal}</p>
              </div>
            )}

            {tasks.length > 0 ? (
              <>
                <div className="progress-card">
                  <div className="progress-meta">
                    <span>
                      {done} of {tasks.length} done
                    </span>
                    <span>{percent}%</span>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${percent}%` }} />
                  </div>
                </div>
                <div className="task-list">
                  {tasks.map((task) => (
                    <div key={task.id} className={`task-row status-${task.status}`}>
                      <button
                        type="button"
                        className="task-status"
                        title="Cycle status"
                        onClick={() => onTaskUpdate(task.id, nextStatus(task.status))}
                      >
                        {statusIcon(task.status)}
                      </button>
                      <div className="task-content">
                        <span className="task-title">{task.title}</span>
                        {task.detail && <span className="task-detail">{task.detail}</span>}
                      </div>
                      <span className={`status-chip ${task.status}`}>
                        {task.status.replace('_', ' ')}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="panel-hint">
                  Tasks are the assistant's own plan for this conversation. Click a status icon to
                  change it.
                </p>
              </>
            ) : (
              <div className="sheet-empty">
                <ListTodo size={30} />
                <p>No tasks yet</p>
                <span>
                  For multi-step work the assistant creates a task list here so you can follow
                  along.
                </span>
              </div>
            )}
          </div>
        ) : (
          <div className="sheet-body">
            <div className="files-bar">
              <div className="segmented small">
                <button
                  type="button"
                  className={fileKind === 'outputs' ? 'is-active' : ''}
                  onClick={() => onFileKind('outputs')}
                >
                  Outputs
                </button>
                <button
                  type="button"
                  className={fileKind === 'uploads' ? 'is-active' : ''}
                  onClick={() => onFileKind('uploads')}
                >
                  Uploads
                </button>
              </div>
              <button
                type="button"
                className="icon-btn"
                onClick={onRefreshFiles}
                aria-label="Refresh files"
                title="Refresh files"
              >
                <RefreshCw size={15} className={loadingFiles ? 'spin' : ''} />
              </button>
            </div>

            {files.length > 0 ? (
              <div className="file-list">
                {files.map((file) => (
                  <button
                    key={`${file.kind}/${file.path}`}
                    type="button"
                    className="file-row"
                    onClick={() => onOpenFile(file)}
                  >
                    <span className="file-row-icon">{fileIcon(file)}</span>
                    <span className="file-row-main">
                      <span className="file-row-name">{file.name}</span>
                      <span className="file-row-meta">
                        {formatBytes(file.size)} · {relativeTime(new Date(file.mtime * 1000).toISOString())}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="sheet-empty">
                <FileText size={30} />
                <p>{fileKind === 'outputs' ? 'No outputs yet' : 'No uploads yet'}</p>
                <span>
                  {fileKind === 'outputs'
                    ? 'Files the assistant writes appear here and can be opened inline.'
                    : 'Attach documents or images in the composer to see them here.'}
                </span>
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
