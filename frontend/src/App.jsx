import { useEffect, useRef, useState } from "react";
import {
  ApiFailure,
  extractPlaces,
  fetchReplyAudio,
  finalizeReply,
  getHealth,
  isAborted,
  recognizeAudio,
  searchPlaces,
  uploadRecording,
} from "./api";
import VoiceRecorder from "./components/VoiceRecorder";

const CITIES = ["杭州", "上海", "北京", "广州", "深圳", "成都", "南京", "武汉"];

const EMPTY_RESULT = {
  stage: "",
  requestId: "",
  transcript: "",
  places: null,
  searchId: "",
  pois: [],
  replyText: "",
  warning: "",
  error: null,
  audioError: "",
  manualPlay: false,
};

export default function App() {
  const [city, setCity] = useState("杭州");
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [healthLoading, setHealthLoading] = useState(true);
  const [result, setResult] = useState(EMPTY_RESULT);
  const [replySrc, setReplySrc] = useState("");

  const runRef = useRef(0);
  const requestRef = useRef(null);
  const replyAudioRef = useRef(null);
  const replyUrlRef = useRef("");
  const pendingAutoplayRef = useRef(0);

  function stopReplyAudio() {
    const player = replyAudioRef.current;
    if (player) {
      player.pause();
      player.removeAttribute("src");
      player.load();
    }
    if (replyUrlRef.current) {
      URL.revokeObjectURL(replyUrlRef.current);
      replyUrlRef.current = "";
    }
    pendingAutoplayRef.current = 0;
    setReplySrc("");
  }

  async function loadHealth() {
    setHealthLoading(true);
    try {
      const body = await getHealth();
      setHealth(body);
      setHealthError("");
    } catch (error) {
      setHealth(null);
      setHealthError(error instanceof ApiFailure ? error.message : "暂时连不上后端，请确认服务已在 8003 端口启动。");
    } finally {
      setHealthLoading(false);
    }
  }

  useEffect(() => {
    loadHealth();
    return () => {
      runRef.current += 1;
      requestRef.current?.abort();
      const player = replyAudioRef.current;
      if (player) {
        player.pause();
        player.removeAttribute("src");
      }
      if (replyUrlRef.current) {
        URL.revokeObjectURL(replyUrlRef.current);
        replyUrlRef.current = "";
      }
    };
  }, []);

  function playReply(blob, runId) {
    if (replyUrlRef.current) URL.revokeObjectURL(replyUrlRef.current);
    const url = URL.createObjectURL(blob);
    replyUrlRef.current = url;
    pendingAutoplayRef.current = runId;
    setReplySrc(url);
  }

  useEffect(() => {
    const runId = pendingAutoplayRef.current;
    const player = replyAudioRef.current;
    if (!replySrc || !player || !runId) return undefined;
    let cancelled = false;
    player.play().then(() => {
      if (cancelled || runRef.current !== runId) return;
      setResult((current) => ({ ...current, manualPlay: false, audioError: "" }));
    }).catch((error) => {
      if (cancelled || runRef.current !== runId) return;
      if (error?.name === "NotAllowedError") {
        setResult((current) => ({ ...current, manualPlay: true, audioError: "" }));
        return;
      }
      setResult((current) => ({
        ...current,
        manualPlay: true,
        audioError: "语音暂时无法自动播放，可以先看文字，或点按钮播放。",
      }));
    });
    return () => {
      cancelled = true;
    };
  }, [replySrc]);

  async function startPipeline(file) {
    const runId = runRef.current + 1;
    runRef.current = runId;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    stopReplyAudio();
    const selectedCity = city;
    setResult({ ...EMPTY_RESULT, stage: "上传中" });

    const current = () => runRef.current === runId;
    const signal = controller.signal;

    try {
      const uploaded = await uploadRecording(file, signal);
      if (!current()) return;
      setResult((item) => ({ ...item, requestId: uploaded.requestId, stage: "识别中" }));

      const recognized = await recognizeAudio(uploaded.data.audio_id, signal);
      if (!current()) return;
      setResult((item) => ({
        ...item,
        requestId: recognized.requestId,
        transcript: recognized.data.text,
        stage: "提取中",
      }));

      const extracted = await extractPlaces(recognized.data.text, selectedCity, signal);
      if (!current()) return;
      setResult((item) => ({
        ...item,
        requestId: extracted.requestId,
        places: extracted.data,
        stage: "找店中",
      }));

      const found = await searchPlaces(extracted.data, signal);
      if (!current()) return;
      setResult((item) => ({
        ...item,
        requestId: found.requestId,
        searchId: found.data.search_id,
        pois: Array.isArray(found.data.pois) ? found.data.pois.slice(0, 3) : [],
        stage: "生成推荐中",
      }));

      const reply = await finalizeReply(found.data.search_id, signal);
      if (!current()) return;
      setResult((item) => ({
        ...item,
        requestId: reply.requestId,
        replyText: reply.data.reply_text,
        warning: reply.data.warning || "",
        stage: reply.data.audio_url ? "正在加载语音" : "",
      }));

      if (!reply.data.audio_url) return;
      try {
        const audio = await fetchReplyAudio(reply.data.audio_url, signal);
        if (!current()) return;
        playReply(audio, runId);
      } catch (error) {
        if (!current() || isAborted(error)) return;
        const message = error instanceof ApiFailure ? error.message : "语音加载失败，可以先看文字。";
        setResult((item) => ({ ...item, audioError: message, stage: "" }));
        return;
      }
      if (current()) setResult((item) => ({ ...item, stage: "" }));
    } catch (error) {
      if (!current() || isAborted(error)) return;
      const failure =
        error instanceof ApiFailure
          ? error
          : new ApiFailure({ code: "request_failed", message: "请求失败，请稍后再试。", stage: "client" });
      setResult((item) => ({ ...item, stage: "", error: failure }));
    }
  }

  function playManually() {
    const player = replyAudioRef.current;
    if (!player) return;
    player.play().then(() => {
      setResult((item) => ({ ...item, manualPlay: false }));
    }).catch(() => {
      setResult((item) => ({
        ...item,
        audioError: "语音暂时无法播放，可以先看文字。",
      }));
    });
  }

  const statusOk = health?.data?.status === "ok";
  const places = result.places;

  return (
    <main className="page">
      <p className="eyebrow">语音约碰面地点</p>
      <h1>帮两个人找个中间的店</h1>
      <p className="lead">
        选择城市，按住说出两个人的位置和想找的店。松开后会上传这支录音，并依次识别、提取、找店和生成推荐。
      </p>

      <section className="card">
        <h2>城市</h2>
        <label className="city-field" htmlFor="city">
          页面上的城市，默认杭州
          <select id="city" value={city} onChange={(event) => setCity(event.target.value)}>
            {CITIES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
      </section>

      <VoiceRecorder onRecordingReady={startPipeline} />

      <section className="card">
        <h2>处理结果</h2>
        {result.stage ? <p className="status">{result.stage}</p> : null}
        {result.requestId ? <p className="meta">最近请求 {result.requestId}</p> : null}
        {result.error ? (
          <p className="error">
            {result.error.message}
            {`（${result.error.stage || "request"} / ${result.error.code || "request_failed"}）`}
          </p>
        ) : null}
        {result.transcript ? (
          <>
            <h3>识别文字</h3>
            <p>{result.transcript}</p>
          </>
        ) : null}
        {places ? (
          <>
            <h3>提取信息</h3>
            <dl className="clip-meta">
              <div>
                <dt>第一个人</dt>
                <dd>
                  {places.city_a} {places.address_a}
                </dd>
              </div>
              <div>
                <dt>第二个人</dt>
                <dd>
                  {places.city_b} {places.address_b}
                </dd>
              </div>
              <div>
                <dt>想找的店</dt>
                <dd>{places.category}</dd>
              </div>
            </dl>
          </>
        ) : null}
        {result.pois.length > 0 ? (
          <>
            <h3>候选</h3>
            <ol className="poi-list">
              {result.pois.map((poi, index) => (
                <li key={`${poi.name}-${poi.address}-${index}`}>
                  <strong>{poi.name}</strong>
                  <span>{poi.address}</span>
                  <span>距中点 {poi.distance_to_midpoint_m} 米</span>
                </li>
              ))}
            </ol>
          </>
        ) : null}
        {result.replyText ? (
          <>
            <h3>推荐语</h3>
            <p>{result.replyText}</p>
          </>
        ) : null}
        {result.warning ? <p className="warning">{result.warning}</p> : null}
        {result.audioError ? <p className="warning">{result.audioError}</p> : null}
        <audio
          ref={replyAudioRef}
          className={replySrc ? "reply-audio" : "reply-audio is-hidden"}
          controls
          preload="auto"
          src={replySrc || undefined}
          onError={() => {
            if (!replyUrlRef.current || runRef.current === 0) return;
            setResult((item) => ({
              ...item,
              audioError: "语音加载失败，可以先看文字。",
              stage: "",
            }));
          }}
        />
        {result.manualPlay ? (
          <button type="button" onClick={playManually}>
            播放推荐语音
          </button>
        ) : null}
        {!result.stage && !result.transcript && !result.error ? <p className="hint">完成一段有效录音后，这里会显示接口返回的内容。</p> : null}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>服务状态</h2>
          <button type="button" onClick={loadHealth} disabled={healthLoading}>
            {healthLoading ? "检查中" : "重新检查"}
          </button>
        </div>
        {healthLoading ? <p>正在检查…</p> : null}
        {!healthLoading && healthError ? <p className="error">{healthError}</p> : null}
        {!healthLoading && health ? (
          <p className={statusOk ? "ok" : "error"}>{statusOk ? "正常" : "异常"}</p>
        ) : null}
      </section>
    </main>
  );
}
