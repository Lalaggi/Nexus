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
import { ArrowDown } from 'lucide-react';
import type { Message } from '../types';
import type { FileTarget } from '../api';
import MessageView from './MessageView';

export default function ChatView({
  messages,
  streaming,
  onRegenerate,
  onEdit,
  onOpenFile,
  onActivateVersion,
}: {
  messages: Message[];
  streaming: boolean;
  onRegenerate: () => void;
  onEdit: (message: Message) => void;
  onOpenFile: (file: FileTarget) => void;
  onActivateVersion: (messageId: string, versionId: string) => void;
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
  const lastMessage = messages[messages.length - 1];
  const lastUserMessage = [...messages].reverse().find((message) => message.role === 'user');

  // The user version that "controls" a given message. For a user message it's its
  // own active version; for a Nexus message it's the active version of the nearest
  // preceding user message. This scopes the Nexus switcher to only the responses
  // on the selected user timeline.
  const getControllingUserVersionId = (index: number): string | undefined => {
    const message = messages[index];
    if (message.role === 'user') {
      return message.active_version_id;
    }
    for (let j = index - 1; j >= 0; j -= 1) {
      if (messages[j].role === 'user') {
        return messages[j].active_version_id;
      }
    }
    return undefined;
  };

  return (
    <div className="chat-scroll" ref={scroller} onScroll={onScroll}>
      <div className="chat-thread">
        {messages.map((message, index) => (
          <MessageView
            key={message.id}
            message={message}
            streaming={streaming && message.id === lastAssistant?.id}
            isLast={message.id === lastMessage?.id}
            isLastUser={message.id === lastUserMessage?.id}
            controllingUserVersionId={getControllingUserVersionId(index)}
            onRegenerate={onRegenerate}
            onEdit={onEdit}
            onOpenFile={onOpenFile}
            onActivateVersion={onActivateVersion}
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
