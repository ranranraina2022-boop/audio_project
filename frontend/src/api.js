export const API_BASE = "http://localhost:8003";

export async function getHealth() {
  const response = await fetch(`${API_BASE}/health`);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = body?.error?.message || "健康检查失败";
    throw new Error(message);
  }
  return body;
}
