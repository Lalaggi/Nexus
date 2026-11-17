export function Brandmark({ size = 30 }: { size?: number }) {
  return (
    <span className="brandmark" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 24 24" width={size * 0.62} height={size * 0.62} fill="currentColor">
        <path d="M12 2.6 14 8.2 19.6 10.2 14 12.2 12 17.8 10 12.2 4.4 10.2 10 8.2Z" />
        <path d="M18.6 14.6 19.4 16.6 21.4 17.4 19.4 18.2 18.6 20.2 17.8 18.2 15.8 17.4 17.8 16.6Z" />
      </svg>
    </span>
  );
}
