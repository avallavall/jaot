import { useEffect, useRef, useState, useCallback } from 'react';

export interface ExecutionProgress {
  type: 'status' | 'progress' | 'completed' | 'failed' | 'error';
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
}

export interface UseWebSocketOptions {
  onProgress?: (data: ExecutionProgress) => void;
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

export function useExecutionWebSocket(
  executionId: string | null,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const {
    onProgress,
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

  const getWebSocketUrl = useCallback(() => {
    if (!executionId) return null;
    
    // Determine WebSocket URL based on current location
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = process.env.NEXT_PUBLIC_API_URL 
      ? new URL(process.env.NEXT_PUBLIC_API_URL).host 
      : window.location.host;
    
    return `${protocol}//${host}/api/v2/ws/executions/${executionId}`;
  }, [executionId]);

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
  }, [getWebSocketUrl, onProgress, onComplete, onError, autoReconnect, reconnectInterval]);

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
