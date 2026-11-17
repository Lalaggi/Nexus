import { Code2, FileSearch, ListTodo, Telescope } from 'lucide-react';

const SUGGESTIONS = [
  {
    icon: <Telescope size={16} />,
    label: 'Research something',
    prompt: 'Research the latest developments in local AI models and give me a concise brief with sources.',
  },
  {
    icon: <FileSearch size={16} />,
    label: 'Analyze a document',
    prompt: 'I want to analyze a document. I will attach it — summarize the key points and flag anything important.',
  },
  {
    icon: <Code2 size={16} />,
    label: 'Write & run code',
    prompt: 'Write and run a Python script that analyzes a dataset and saves a chart to my outputs folder.',
  },
  {
    icon: <ListTodo size={16} />,
    label: 'Plan a project',
    prompt: 'Help me plan a software project. Break it into tasks, risks, and a realistic first milestone.',
  },
];

export default function Welcome({
  userName,
  onPick,
}: {
  userName: string;
  onPick: (prompt: string) => void;
}) {
  return (
    <section className="hero">
      <div className="hero-glow" aria-hidden="true" />
      <h1>
        Welcome {userName}
        <br />
        <span>What shall we do today?</span>
      </h1>
      <div className="suggestions" role="group" aria-label="Suggested prompts">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion.label}
            type="button"
            className="suggestion"
            onClick={() => onPick(suggestion.prompt)}
          >
            {suggestion.icon}
            <span>{suggestion.label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
