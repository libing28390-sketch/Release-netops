import React, { useEffect, useRef, useState } from 'react';

interface CountdownTextProps {
  deadline: number;
  onExpire: () => void;
  children: (secondsRemaining: number) => React.ReactNode;
}

const secondsUntil = (deadline: number): number =>
  deadline > 0 ? Math.max(0, Math.ceil((deadline - Date.now()) / 1000)) : 0;

/** Keeps one-second timer updates local to the countdown instead of rerendering the full page. */
const CountdownText: React.FC<CountdownTextProps> = ({ deadline, onExpire, children }) => {
  const [secondsRemaining, setSecondsRemaining] = useState(() => secondsUntil(deadline));
  const hasExpired = useRef(false);

  useEffect(() => {
    hasExpired.current = false;
    if (!deadline) {
      setSecondsRemaining(0);
      return;
    }

    const updateRemaining = () => {
      const next = secondsUntil(deadline);
      setSecondsRemaining(previous => previous === next ? previous : next);
      if (next === 0 && !hasExpired.current) {
        hasExpired.current = true;
        onExpire();
      }
    };

    updateRemaining();
    const timer = window.setInterval(updateRemaining, 1000);
    return () => window.clearInterval(timer);
  }, [deadline, onExpire]);

  return <>{children(secondsRemaining)}</>;
};

export default CountdownText;
