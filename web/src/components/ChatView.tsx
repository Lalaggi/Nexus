import { useEffect, useRef, useState } from 'react';
import { ArrowDown } from 'lucide-react';
import type { Message } from '../types';
import type { FileTarget } from '../api';
import MessageView from './MessageView';

export default function ChatView({
  messages,
  streaming,
  onRegenerate,
  onOpenFile,
}: {
  messages: Message[];
  streaming: boolean;
  onRegenerate: () => void;
  onOpenFile: (file: FileTarget) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    if (atBottom) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages, streaming, atBottom]);

  const onScroll = () => {
    const node = scroller.current;
    if (!node) return;
    setAtBottom(node.scrollTop + node.clientHeight >= node.scrollHeight - 120);
  };

  const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant');

  return (
    <div className="chat-scroll" ref={scroller} onScroll={onScroll}>
      <div className="chat-thread">
        {messages.map((message) => (
          <MessageView
            key={message.id}
            message={message}
            streaming={streaming && message.id === lastAssistant?.id}
            isLast={message.id === lastAssistant?.id}
            onRegenerate={onRegenerate}
            onOpenFile={onOpenFile}
          />
        ))}
        <div className="thread-end" />
      </div>
      {!atBottom && (
        <button
          type="button"
          className="scroll-down"
          onClick={() => {
            const node = scroller.current;
            if (node) node.scrollTop = node.scrollHeight;
            setAtBottom(true);
          }}
          aria-label="Scroll to latest"
        >
          <ArrowDown size={17} />
        </button>
      )}
    </div>
  );
}
