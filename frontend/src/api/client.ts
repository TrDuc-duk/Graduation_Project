// Gọi API backend qua /api (cùng origin, Vite proxy ở dev). Lỗi được chuẩn hóa thành ApiError.

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

/** Lỗi khi gọi API: `offline` = không tới được máy chủ; còn lại có mã lỗi của backend. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly offline = false,
  ) {
    super(message);
  }
}

/** GET một endpoint, trả JSON; lỗi mạng → ApiError(offline), lỗi HTTP → ApiError(code của backend). */
export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: { "Accept-Language": "vi" }, signal });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Không kết nối được tới máy chủ", "NETWORK", true);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const error = body?.error;
    // 502/503/504 từ proxy nghĩa là backend không phản hồi
    const offline = res.status >= 502 && res.status <= 504;
    throw new ApiError(error?.message ?? `Lỗi máy chủ (${res.status})`, error?.code ?? `HTTP_${res.status}`, offline);
  }
  return (await res.json()) as T;
}
