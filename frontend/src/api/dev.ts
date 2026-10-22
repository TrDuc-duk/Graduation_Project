// API dev chỉ đọc (chỉ bật ở môi trường dev, ENABLE_DEV_ENDPOINTS=true): xem cả node đang chờ duyệt.
import { getJson } from "./client";
import type { NodeInfo, NodeReadings, RangeHours } from "./types";

/** Danh sách node kèm Gateway và độ mới dữ liệu. */
export function fetchNodes(signal?: AbortSignal): Promise<NodeInfo[]> {
  return getJson<NodeInfo[]>("/dev/nodes", signal);
}

/** Dữ liệu của một node: số đo thô (1/6/24 giờ) hoặc trung bình giờ (168/720 giờ), kèm số đo mới nhất, đơn vị. */
export function fetchReadings(nodeId: number, hours: RangeHours, signal?: AbortSignal): Promise<NodeReadings> {
  return getJson<NodeReadings>(`/dev/nodes/${nodeId}/readings?hours=${hours}`, signal);
}
