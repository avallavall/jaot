'use client';

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { useExecutionWebSocket } from '@/hooks/useWebSocket';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import { Info } from 'lucide-react';
import Link from 'next/link';

interface ProgressPoint {
  iteration: number;
  objective: number;
  gap: number;
  timestamp: number;
}

interface ExecutionProgressProps {
  executionId: string | null;
  onComplete?: (result: Record<string, unknown>) => void;
  onError?: (error: string) => void;
  onCancel?: () => void;
  showConvergenceGraph?: boolean;
}

export function ExecutionProgress({
  executionId,
  onComplete,
  onError,
  onCancel,
  showConvergenceGraph = true,
}: ExecutionProgressProps) {
  const t = useTranslations('solve.progress');
  const [status, setStatus] = useState<string>('pending');
  const [cancelling, setCancelling] = useState(false);
  const [progress, setProgress] = useState<number>(0);
  const [message, setMessage] = useState<string>(t('waitingToStart'));
  const [iteration, setIteration] = useState<number>(0);
  const [objectiveValue, setObjectiveValue] = useState<number | null>(null);
  const [gap, setGap] = useState<number | null>(null);
  const [progressHistory, setProgressHistory] = useState<ProgressPoint[]>([]);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, setCreditsUsed] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const prevStatusRef = useRef<string>('pending');
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const hasCompletedRef = useRef(false);

  // Handle completion from any source (WebSocket or polling)
  const handleCompletion = useCallback((resultData: Record<string, unknown>) => {
    if (hasCompletedRef.current) return;
    hasCompletedRef.current = true;
    setStatus('completed');
    setProgress(1);
    setMessage(t('modelFound'));
    setResult(resultData);
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    onComplete?.(resultData);
  }, [onComplete, t]);

  const handleFailure = useCallback((errorMsg: string) => {
    if (hasCompletedRef.current) return;
    hasCompletedRef.current = true;
    setStatus('failed');
    setError(errorMsg);
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    onError?.(errorMsg);
  }, [onError]);

  const handleCancel = useCallback(async () => {
    if (!executionId || cancelling) return;
    setCancelling(true);
    try {
      await api.request(`/api/v2/models/async/${executionId}/cancel`, { method: 'POST' });
      setStatus('cancelled');
      setMessage(t('cancelledByUser'));
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
      onCancel?.();
    } catch (err) {
      console.warn('Failed to cancel execution:', err);
      toast.error(t('cancelFailed'));
    } finally {
      setCancelling(false);
    }
  }, [executionId, cancelling, onCancel, t]);

  const { isConnected, disconnect: disconnectWs } = useExecutionWebSocket(executionId, {
    autoReconnect: false, // Disable auto-reconnect, we use polling as fallback
    onProgress: (data) => {
      if (hasCompletedRef.current) return;
      setStatus('running');
      setProgress(data.progress || 0);
      setMessage(data.message || t('solvingMsg'));
      if (data.iteration !== undefined) setIteration(data.iteration);
      if (data.objective_value !== undefined) setObjectiveValue(data.objective_value);
      if (data.gap !== undefined) setGap(data.gap);

      // Add to history for convergence graph
      if (data.iteration !== undefined && data.objective_value !== undefined) {
        setProgressHistory((prev) => [
          ...prev,
          {
            iteration: data.iteration!,
            objective: data.objective_value!,
            gap: data.gap || 0,
            timestamp: Date.now(),
          },
        ]);
      }
    },
    onComplete: (data) => {
      if (data.result) {
        handleCompletion(data.result);
      }
      disconnectWs();
    },
    onError: (data) => {
      // Don't treat WebSocket connection errors as execution failures
      if (data.error === 'WebSocket connection error') {
        return;
      }
      handleFailure(data.error || t('unknownError'));
    },
  });

  // Polling fallback
  useEffect(() => {
    if (!executionId) return;

    hasCompletedRef.current = false;
    setStatus('pending');
    setProgress(0);
    setMessage(t('connecting'));
    setIteration(0);
    setObjectiveValue(null);
    setGap(null);
    setProgressHistory([]);
    setResult(null);
    setError(null);
    setCreditsUsed(null);

    const poll = async () => {
      if (hasCompletedRef.current) return;
      
      try {
        const statusData = await api.getAsyncTaskStatus(executionId);
        
        if (statusData.status === 'completed') {
          // statusData now has flattened structure:
          // { status, execution_id, task_id, result: {model data}, execution_time_ms, credits_used }
          handleCompletion(statusData as unknown as Record<string, unknown>);
          disconnectWs();
        } else if (statusData.status === 'failed') {
          handleFailure(statusData.error || t('executionFailed'));
          disconnectWs();
        } else if (statusData.status === 'running' && !hasCompletedRef.current) {
          setStatus('running');
          const ext = statusData as unknown as Record<string, unknown>;
          setMessage((ext.message as string) || t('solvingMsg'));
          if (statusData.progress) setProgress(statusData.progress);
        }
      } catch (err) {
        console.warn('Execution polling error:', err);
      }
    };

    // Poll immediately and then every second
    poll();
    pollingRef.current = setInterval(poll, 1000);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [executionId, handleCompletion, handleFailure, disconnectWs, t]);

  // Announce status changes for screen readers
  useEffect(() => {
    if (status === prevStatusRef.current) return;
    if (status === 'running' && prevStatusRef.current !== 'running') {
      setAnnouncement(t('announceSolvingStarted'));
    } else if (status === 'completed') {
      setAnnouncement(t('announceCompleted', { message }));
    } else if (status === 'failed') {
      setAnnouncement(t('announceFailed', { error: error || t('unknownError') }));
    } else if (status === 'cancelled') {
      setAnnouncement(t('announceCancelled'));
    }
    prevStatusRef.current = status;
  }, [status, message, error, t]);

  const progressPercent = Math.round(progress * 100);

  const statusColor = useMemo(() => {
    switch (status) {
      case 'completed':
        return 'bg-green-500';
      case 'failed':
        return 'bg-red-500';
      case 'running':
        return 'bg-blue-500';
      default:
        return 'bg-gray-400';
    }
  }, [status]);

  const statusIcon = useMemo(() => {
    switch (status) {
      case 'completed':
        return '✓';
      case 'failed':
        return '✗';
      case 'running':
        return '⟳';
      default:
        return '○';
    }
  }, [status]);

  if (!executionId) {
    return null;
  }

  return (
    <>
    <div aria-live="polite" className="sr-only">{announcement}</div>
    <div className="bg-card rounded-lg shadow-md p-6 space-y-4" aria-busy={status === 'running' || status === 'pending'}>
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-foreground">
          {t('title')}
        </h3>
        <div className="flex items-center gap-2">
          <span
            className={`w-3 h-3 rounded-full ${
              isConnected ? 'bg-green-500' : 'bg-muted-foreground/40'
            }`}
          />
          <span className="text-sm text-muted-foreground">
            {isConnected ? t('connected') : t('disconnected')}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <span
          className={`inline-flex items-center justify-center w-8 h-8 rounded-full text-white ${statusColor}`}
        >
          {statusIcon}
        </span>
        <div>
          <p className="font-medium text-foreground capitalize">
            {status}
          </p>
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">{t('progress')}</span>
          <span className="font-medium text-foreground">
            {progressPercent}%
          </span>
        </div>
        <div className="w-full bg-muted rounded-full h-3">
          <div
            className={`h-3 rounded-full transition-all duration-300 ${statusColor}`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {status === 'running' && (
        <div className="grid grid-cols-3 gap-4 pt-2">
          <div className="text-center">
            <p className="text-2xl font-bold text-foreground">
              {iteration}
            </p>
            <p className="text-xs text-muted-foreground">{t('iteration')}</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-foreground">
              {objectiveValue !== null ? objectiveValue.toFixed(2) : '-'}
            </p>
            <p className="text-xs text-muted-foreground">{t('objective')}</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold text-foreground">
              {gap !== null ? `${(gap * 100).toFixed(2)}%` : '-'}
            </p>
            <p className="text-xs text-muted-foreground">{t('gap')}</p>
          </div>
        </div>
      )}

      {(status === 'running' || status === 'pending') && (
        <div className="pt-2">
          <button
            onClick={handleCancel}
            disabled={cancelling}
            className="w-full px-4 py-2 text-sm font-medium text-destructive bg-destructive/10 hover:bg-destructive/20 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {cancelling ? t('cancelling') : t('cancelExecution')}
          </button>
        </div>
      )}

      {(status === 'running' || status === 'pending') && (
        <div className="flex items-start gap-3 p-3 bg-blue-50 border border-blue-200 rounded-lg dark:bg-blue-900/20 dark:border-blue-800">
          <Info className="w-4 h-4 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
          <div className="space-y-1 text-sm">
            <p className="font-medium text-blue-800 dark:text-blue-300">
              {t('asyncInfoTitle')}
            </p>
            <p className="text-blue-700 dark:text-blue-400">
              {t('asyncInfoRunning')}
            </p>
            <p className="text-blue-700 dark:text-blue-400">
              {t('asyncInfoSafeToLeave')}
            </p>
            <p className="text-blue-600/80 dark:text-blue-400/80 text-xs">
              {t('asyncInfoEstimatedTime')}
            </p>
            <Link
              href="/solve/executions"
              className="inline-block text-xs font-medium text-blue-700 dark:text-blue-300 underline underline-offset-2 hover:text-blue-900 dark:hover:text-blue-100 mt-1"
            >
              {t('asyncInfoViewHistory')}
            </Link>
          </div>
        </div>
      )}

      {showConvergenceGraph && progressHistory.length > 1 && (
        <div className="pt-4 border-t border-border">
          <h4 className="text-sm font-medium text-foreground mb-3">
            {t('convergenceGraph')}
          </h4>
          <ConvergenceGraph data={progressHistory} />
        </div>
      )}

      {status === 'completed' && result && (
        <div className="pt-4 border-t border-border">
          <h4 className="text-sm font-medium text-foreground mb-2">
            {t('resultLabel')}
          </h4>
          <pre className="bg-muted p-3 rounded text-xs overflow-auto max-h-48">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}

      {status === 'failed' && error && (
        <div className="pt-4 border-t border-destructive/20">
          <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-4">
            <p className="text-destructive text-sm">{error}</p>
          </div>
        </div>
      )}
    </div>
    </>
  );
}

// Simple SVG-based convergence graph
function ConvergenceGraph({ data }: { data: ProgressPoint[] }) {
  const width = 400;
  const height = 150;
  const padding = { top: 10, right: 10, bottom: 30, left: 50 };

  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  // Calculate scales
  const xMin = Math.min(...data.map((d) => d.iteration));
  const xMax = Math.max(...data.map((d) => d.iteration));
  const yMin = Math.min(...data.map((d) => d.objective));
  const yMax = Math.max(...data.map((d) => d.objective));

  const xScale = (x: number) =>
    padding.left + ((x - xMin) / (xMax - xMin || 1)) * chartWidth;
  const yScale = (y: number) =>
    padding.top + chartHeight - ((y - yMin) / (yMax - yMin || 1)) * chartHeight;

  // Generate path
  const pathD = data
    .map((point, i) => {
      const x = xScale(point.iteration);
      const y = yScale(point.objective);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    })
    .join(' ');

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto"
      style={{ maxHeight: '150px' }}
    >
      <line
        x1={padding.left}
        y1={padding.top + chartHeight}
        x2={padding.left + chartWidth}
        y2={padding.top + chartHeight}
        stroke="currentColor"
        strokeWidth="1"
        className="text-border"
      />
      <line
        x1={padding.left}
        y1={padding.top}
        x2={padding.left}
        y2={padding.top + chartHeight}
        stroke="currentColor"
        className="text-border"
        strokeWidth="1"
      />

      <path
        d={pathD}
        fill="none"
        stroke="#3b82f6"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {data.slice(-10).map((point, i) => (
        <circle
          key={i}
          cx={xScale(point.iteration)}
          cy={yScale(point.objective)}
          r="3"
          fill="#3b82f6"
        />
      ))}

      <text
        x={padding.left + chartWidth / 2}
        y={height - 5}
        textAnchor="middle"
        className="text-xs fill-gray-500"
      >
        Iteration
      </text>
      <text
        x={15}
        y={padding.top + chartHeight / 2}
        textAnchor="middle"
        transform={`rotate(-90, 15, ${padding.top + chartHeight / 2})`}
        className="text-xs fill-gray-500"
      >
        Objective
      </text>
    </svg>
  );
}

export default ExecutionProgress;
