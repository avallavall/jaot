import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '@/lib/api';

export interface ExecutionProgress {
  type: 'status' | 'progress' | 'solve_progress' | 'completed' | 'failed' | 'error';
  execution_id?: string;
  task_id?: string;
  status?: string;
  progress?: number;
  message?: string;
  iteration?: number;
  objective_value?: number;
  gap?: number;
  timestamp?: string;
  result?: Record<string, unknown>;
  error?: string;
  progress_data?: Record<string, unknown>;
  // Live Solve per-incumbent fields (type === 'solve_progress'); mirror the
  // backend ProgressPoint streamed on each new best solution.
  node?: number;
  objective?: number;
  primal_bound?: number;
  dual_bound?: number | null;
  elapsed_seconds?: number;
}

export interface UseWebSocketOptions {
  onProgress?: (data: ExecutionProgress) => void;
  /** Fired on `type === 'solve_progress'` — the per-incumbent Live Solve stream. */
  onSolveProgress?: (data: ExecutionProgress) => void;
  onComplete?: (data: ExecutionProgress) => void;
  onError?: (data: ExecutionProgress) => void;
  autoReconnect?: boolean;
  reconnectInterval?: number;
}

export interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: ExecutionProgress | null;
  connect: () => void;
  disconnect: () => void;
  sendMessage: (message: string) => void;
}

/**
 * Build the execution-progress WebSocket URL. Auth has two transports and the
 * server accepts either: the JWT **access cookie** (`jaot_access_token`,
 * auto-sent by the browser on a same-origin handshake — the email/password login
 * path) OR a Bearer **API key** passed via `?token=` (browsers can't set an
 * `Authorization` header on a WebSocket). The API key is appended only when
 * present; an email/cookie session has no API key in localStorage, so the URL is
 * built WITHOUT `?token=` and the server authenticates from the cookie. (Returning
 * null here when there was no API key was a bug: it meant cookie/email sessions —
 * the common case — never opened the Live Solve socket at all.)
 *
 * Returns `null` only when there is no `executionId`.
 */
export function buildExecutionWsUrl(
  executionId: string | null,
  token: string | null,
  opts?: { protocol?: string; host?: string }
): string | null {
  if (!executionId) return null;

  const protocol =
    opts?.protocol ??
    (typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:');
  const host =
    opts?.host ??
    (process.env.NEXT_PUBLIC_API_URL
      ? new URL(process.env.NEXT_PUBLIC_API_URL).host
      : typeof window !== 'undefined'
        ? window.location.host
        : '');

  const base = `${protocol}//${host}/api/v2/ws/executions/${executionId}`;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export function useExecutionWebSocket(
  executionId: string | null,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const {
    onProgress,
    onSolveProgress,
    onComplete,
    onError,
    autoReconnect = true,
    reconnectInterval = 3000,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<ExecutionProgress | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const connectRef = useRef<() => void>(() => {});

  const getWebSocketUrl = useCallback(
    // Token read fresh at connect time (localStorage), not reactive.
    () => buildExecutionWsUrl(executionId, api.getApiKey()),
    [executionId]
  );

  const connect = useCallback(() => {
    const url = getWebSocketUrl();
    if (!url) return;

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data: ExecutionProgress = JSON.parse(event.data);
          setLastMessage(data);

          // Call appropriate callback based on message type
          switch (data.type) {
            case 'progress':
              onProgress?.(data);
              break;
            case 'solve_progress':
              onSolveProgress?.(data);
              break;
            case 'completed':
              onComplete?.(data);
              break;
            case 'failed':
            case 'error':
              onError?.(data);
              break;
          }
        } catch (err) {
          console.warn('Failed to parse WebSocket message:', err);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        wsRef.current = null;

        // Auto-reconnect if not a clean close and enabled
        if (autoReconnect && event.code !== 1000 && event.code !== 1001) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connectRef.current();
          }, reconnectInterval);
        }
      };

      ws.onerror = () => {
        onError?.({ type: 'error', error: 'WebSocket connection error' });
      };
    } catch (err) {
      console.warn('Failed to create WebSocket:', err);
      onError?.({ type: 'error', error: 'Failed to create WebSocket connection' });
    }
  }, [getWebSocketUrl, onProgress, onSolveProgress, onComplete, onError, autoReconnect, reconnectInterval]);

  useEffect(() => { connectRef.current = connect; }, [connect]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const sendMessage = useCallback((message: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(message);
    }
  }, []);

  // Connect when executionId changes
  useEffect(() => {
    if (executionId) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [executionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Ping to keep connection alive
  useEffect(() => {
    if (!isConnected) return;

    const pingInterval = setInterval(() => {
      sendMessage('ping');
    }, 30000);

    return () => clearInterval(pingInterval);
  }, [isConnected, sendMessage]);

  return {
    isConnected,
    lastMessage,
    connect,
    disconnect,
    sendMessage,
  };
}
