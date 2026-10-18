import { useEffect, useState } from "react";
import { getHealth } from "./api";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function loadHealth() {
    setLoading(true);
    try {
      const body = await getHealth();
      setHealth(body);
      setError("");
    } catch (err) {
      setHealth(null);
      setError(err.message || "暂时连不上后端，请确认服务已在 8003 端口启动。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadHealth();
  }, []);

  const statusOk = health?.data?.status === "ok";

  return (
    <main className="page">
      <p className="eyebrow">第一版骨架</p>
      <h1>语音约碰面地点</h1>
      <p className="lead">
        按住说话，帮同一座城市里的两个人找一个中间附近的店。这一页只确认服务是否在线。
      </p>

      <section className="card">
        <div className="card-head">
          <h2>服务状态</h2>
          <button type="button" onClick={loadHealth} disabled={loading}>
            {loading ? "检查中" : "重新检查"}
          </button>
        </div>
        {loading ? <p>正在检查…</p> : null}
        {!loading && error ? <p className="error">{error}</p> : null}
        {!loading && health ? (
          <>
            <p className={statusOk ? "ok" : "error"}>
              {statusOk ? "正常" : "异常"}
            </p>
            <pre>{JSON.stringify(health, null, 2)}</pre>
          </>
        ) : null}
      </section>
    </main>
  );
}
