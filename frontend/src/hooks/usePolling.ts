import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";

export interface PollingState<T> {
  data: T | null; // dữ liệu thành công gần nhất (giữ lại khi lần sau lỗi)
  error: ApiError | null; // lỗi của lần gọi gần nhất, null nếu thành công
  loading: boolean; // đang gọi API
  lastSuccessAt: Date | null; // lúc nhận dữ liệu thành công gần nhất
  refresh: () => void; // gọi lại ngay
}

/**
 * Gọi `fetcher` ngay khi `key` đổi và lặp lại mỗi `intervalMs`.
 * Tab bị ẩn thì tạm dừng; hiện lại thì gọi ngay. Request cũ bị hủy khi có request mới.
 */
export function usePolling<T>(fetcher: (signal: AbortSignal) => Promise<T>, key: string, intervalMs: number): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastSuccessAt, setLastSuccessAt] = useState<Date | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const controllerRef = useRef<AbortController | null>(null);

  // Một lần gọi API: hủy request đang chạy, lưu dữ liệu hoặc lỗi
  const run = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    try {
      const result = await fetcherRef.current(controller.signal);
      if (controller.signal.aborted) return;
      setData(result);
      setError(null);
      setLastSuccessAt(new Date());
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err : new ApiError(String(err), "UNKNOWN"));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void run();
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") void run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      controllerRef.current?.abort();
    };
  }, [key, intervalMs, run]);

  return { data, error, loading, lastSuccessAt, refresh: () => void run() };
}
