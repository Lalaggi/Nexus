import { useId } from 'react';

/**
 * The Nexus "N" mark. Shared by the sidebar and the collapsed-sidebar topbar
 * so the brand only has to be defined once.
 */
export function NexusLogo({ size = 28 }: { size?: number }) {
  const gradientId = `nexus-logo-${useId().replace(/[:]/g, '')}`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 512 512"
      width={size}
      height={size}
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id={gradientId}
          gradientUnits="userSpaceOnUse"
          x1="106"
          y1="96"
          x2="406"
          y2="416"
        >
          <stop offset="0" stopColor="#8B5CF6" />
          <stop offset="1" stopColor="#FF7F50" />
        </linearGradient>
      </defs>
      <g fill={`url(#${gradientId})`}>
        <path d="M106 96 H174 L356 356 H406 V416 H338 L156 156 H106 Z" />
        <path d="M106 164 H151 C154 190 156 212 156 240 V416 H106 Z" />
        <path d="M406 348 H361 C358 322 356 300 356 272 V96 H406 Z" />
      </g>
    </svg>
  );
}

/**
 * Sidebar toggle. The small left pane represents the sidebar: it is solid when
 * the sidebar is open and outlined when it is closed.
 */
export function SidebarToggleIcon({
  filled = false,
  size = 18,
}: {
  filled?: boolean;
  size?: number;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="18" height="18" rx="3.5" />
      <rect
        x="4"
        y="4"
        width="5.4"
        height="16"
        rx="2.4"
        fill={filled ? 'currentColor' : 'none'}
        stroke={filled ? 'none' : 'currentColor'}
      />
    </svg>
  );
}
