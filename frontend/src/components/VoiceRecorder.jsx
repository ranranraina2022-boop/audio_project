import { useEffect, useRef, useState } from "react";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm; codecs=opus"];
const MIN_DURATION_MS = 1000;
const MAX_DURATION_MS = 60_000;
const MAX_FILE_BYTES = 5 * 1024 * 1024;

function findWebmOpusMimeType() {
  if (
    typeof MediaRecorder === "undefined" ||
    typeof MediaRecorder.isTypeSupported !== "function"
  ) {
    return "";
  }
  return MIME_CANDIDATES.find((mime) => MediaRecorder.isTypeSupported(mime)) ?? "";
}

function releaseStream(stream) {
  stream?.getTracks().forEach((track) => {
    track.stop();
  });
}

function clearSessionTimers(session) {
  if (!session) return;
  if (session.tick) clearInterval(session.tick);
  if (session.limitTimer) clearTimeout(session.limitTimer);
  session.tick = null;
  session.limitTimer = null;
}

function microphoneErrorMessage(error) {
  const name = error?.name;
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "没有获得麦克风权限，请允许后再按住录音。";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "没有检测到可用的麦克风。";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "麦克风被占用，请关闭其他正在使用麦克风的程序后再试。";
  }
  if (name === "SecurityError") {
    return "当前页面无法使用麦克风，请用 localhost 打开后再试。";
  }
  return "无法打开麦克风，请检查权限后重试。";
}

function formatBytes(size) {
  if (size < 1024) return `${size} 字节`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB（${size} 字节）`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB（${size} 字节）`;
}

function formatSeconds(ms) {
  return `${(ms / 1000).toFixed(1)} 秒`;
}

export default function VoiceRecorder({ onRecordingReady }) {
  const mimeType = useRef(findWebmOpusMimeType()).current;
  const secureContext = useRef(
    typeof window !== "undefined" && window.isSecureContext
  ).current;
  const sessionRef = useRef(null);
  const buttonRef = useRef(null);
  const clipUrlRef = useRef("");
  const stopRef = useRef(() => {});
  const onRecordingReadyRef = useRef(onRecordingReady);
  onRecordingReadyRef.current = onRecordingReady;

  const [phase, setPhase] = useState("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [pointerOutside, setPointerOutside] = useState(false);
  const [notice, setNotice] = useState({ type: "", text: "" });
  const [clip, setClip] = useState(null);
  const [mediaDuration, setMediaDuration] = useState(null);

  function endSession(session) {
    clearSessionTimers(session);
    releaseStream(session.stream);
    session.stream = null;
    session.finalized = true;
    if (sessionRef.current === session) sessionRef.current = null;
    setPhase("idle");
    setElapsedMs(0);
    setPointerOutside(false);
  }

  function replaceClip(nextClip) {
    if (clipUrlRef.current) URL.revokeObjectURL(clipUrlRef.current);
    clipUrlRef.current = nextClip?.url ?? "";
    setMediaDuration(null);
    setClip(nextClip);
  }

  function finishWithoutFile(session, nextNotice) {
    if (session.finalized) return;
    endSession(session);
    if (nextNotice) setNotice(nextNotice);
  }

  function finishWithFile(session) {
    if (session.finalized) return;
    const durationMs = Date.now() - session.startedAt;
    const blob = new Blob(session.chunks, { type: session.mimeType });
    endSession(session);

    if (session.mode === "cancel") {
      setNotice({ type: "info", text: "已取消录音。" });
      return;
    }
    if (session.mode === "error" || blob.size === 0) {
      setNotice({ type: "error", text: "录音失败，请再试一次。" });
      return;
    }
    if (durationMs < MIN_DURATION_MS) {
      setNotice({ type: "error", text: "录音太短，请按住 1 到 60 秒。" });
      return;
    }
    if (blob.size > MAX_FILE_BYTES) {
      setNotice({
        type: "error",
        text: "录音文件超过 5MB，请缩短后再录。",
      });
      return;
    }

    const url = URL.createObjectURL(blob);
    const filename = "recording.webm";
    replaceClip({
      url,
      bytes: blob.size,
      durationMs,
      mimeType: blob.type || session.mimeType,
      filename,
    });
    const file = new File([blob], filename, { type: blob.type || session.mimeType });
    onRecordingReadyRef.current?.(file);
    if (session.mode === "max") {
      setNotice({ type: "info", text: "已录满 60 秒，录音已结束。可以试听或下载。" });
      return;
    }
    if (session.mode === "outside") {
      setNotice({
        type: "info",
        text: "已在按钮外松开，录音已结束。可以试听或下载。",
      });
      return;
    }
    setNotice({ type: "info", text: "录音已完成，可以试听或下载。" });
  }

  stopRef.current = (reason, event) => {
    const session = sessionRef.current;
    if (!session || session.stopRequested || session.finalized) return;

    if (
      (reason === "pointerup" || reason === "pointercancel") &&
      event &&
      event.pointerId !== session.pointerId
    ) {
      return;
    }

    let mode = reason;
    if (reason === "pointerup") {
      const releasedOnCancel = Boolean(event?.target?.closest?.("[data-cancel-recording]"));
      if (releasedOnCancel) mode = "cancel";
      else if (isOutsideButton(event)) mode = "outside";
      else mode = "release";
    }
    if (reason === "pointercancel") mode = "outside";

    session.stopRequested = true;
    session.mode = mode;
    clearSessionTimers(session);

    const recorder = session.recorder;
    if (!recorder || recorder.state === "inactive") {
      if (!session.startedAt) {
        if (mode === "cancel") {
          finishWithoutFile(session, { type: "info", text: "已取消录音。" });
        } else if (mode === "error") {
          finishWithoutFile(session, { type: "error", text: "录音失败，请再试一次。" });
        }
        return;
      }
      if (mode === "cancel") {
        finishWithoutFile(session, { type: "info", text: "已取消录音。" });
        return;
      }
      if (mode === "error") {
        finishWithoutFile(session, { type: "error", text: "录音失败，请再试一次。" });
        return;
      }
      finishWithoutFile(session, { type: "info", text: "录音已结束。" });
      return;
    }

    try {
      recorder.stop();
    } catch {
      session.mode = "error";
      finishWithoutFile(session, { type: "error", text: "录音失败，请再试一次。" });
    }
  };

  function isOutsideButton(event) {
    const button = buttonRef.current;
    if (!button || !event || !Number.isFinite(event.clientX)) return false;
    const rect = button.getBoundingClientRect();
    return (
      event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom
    );
  }

  useEffect(() => {
    function handlePointerUp(event) {
      stopRef.current("pointerup", event);
    }
    function handlePointerCancel(event) {
      stopRef.current("pointercancel", event);
    }
    function handleKeyDown(event) {
      if (event.key === "Escape") stopRef.current("cancel", event);
    }

    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerCancel);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerCancel);
      window.removeEventListener("keydown", handleKeyDown);
      const session = sessionRef.current;
      if (!session) return;
      session.stopRequested = true;
      session.finalized = true;
      clearSessionTimers(session);
      if (session.recorder) session.recorder.onstop = null;
      if (session.recorder && session.recorder.state !== "inactive") {
        try {
          session.recorder.stop();
        } catch {
          // 页面离开时只负责关掉麦克风。
        }
      }
      releaseStream(session.stream);
      sessionRef.current = null;
      if (clipUrlRef.current) {
        URL.revokeObjectURL(clipUrlRef.current);
        clipUrlRef.current = "";
      }
    };
  }, []);

  async function beginRecording(event) {
    if (!mimeType || !secureContext || sessionRef.current) return;
    const session = {
      pointerId: event.pointerId,
      mimeType,
      requestedAt: Date.now(),
      chunks: [],
      mode: "release",
      stopRequested: false,
      finalized: false,
      startedAt: 0,
      stream: null,
      recorder: null,
      tick: null,
      limitTimer: null,
    };
    sessionRef.current = session;
    setNotice({ type: "", text: "" });
    setPointerOutside(false);
    setPhase("opening");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (session.finalized || sessionRef.current !== session) {
        releaseStream(stream);
        return;
      }
      if (session.stopRequested) {
        releaseStream(stream);
        const waited = Date.now() - session.requestedAt;
        endSession(session);
        if (session.mode === "cancel") {
          setNotice({ type: "info", text: "已取消录音。" });
        } else if (waited >= 800) {
          setNotice({ type: "info", text: "麦克风已就绪，请再按住录音。" });
        } else {
          setNotice({ type: "error", text: "录音太短，请按住 1 到 60 秒。" });
        }
        return;
      }
      session.stream = stream;
      const recorder = new MediaRecorder(stream, { mimeType });
      session.recorder = recorder;
      recorder.ondataavailable = (dataEvent) => {
        if (dataEvent.data && dataEvent.data.size > 0) session.chunks.push(dataEvent.data);
      };
      recorder.onerror = () => {
        stopRef.current("error");
      };
      recorder.onstop = () => {
        finishWithFile(session);
      };
      recorder.start();
      session.startedAt = Date.now();
      session.tick = setInterval(() => {
        setElapsedMs(Math.min(Date.now() - session.startedAt, MAX_DURATION_MS));
      }, 200);
      session.limitTimer = setTimeout(() => {
        stopRef.current("max");
      }, MAX_DURATION_MS);
      setPhase("recording");
    } catch (error) {
      const failedAfterOpen = Boolean(session.stream);
      releaseStream(session.stream);
      if (!session.finalized) {
        endSession(session);
      } else if (sessionRef.current === session) {
        sessionRef.current = null;
        setPhase("idle");
      }
      setNotice({
        type: "error",
        text: failedAfterOpen ? "录音失败，请再试一次。" : microphoneErrorMessage(error),
      });
    }
  }

  function handlePointerDown(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    beginRecording(event);
  }

  const unsupported = !mimeType;
  const blocked = unsupported || !secureContext;
  const buttonLabel =
    phase === "recording" ? "松开结束" : phase === "opening" ? "正在打开麦克风…" : "按住说话";

  return (
    <section className="card">
      <h2>录音</h2>
      <p className="hint">按住 1 到 60 秒后松开。录音原文件需要在 5MB 以内。</p>
      {unsupported ? (
        <p className="error">当前浏览器不支持 WebM/Opus 录音，请换用 Chrome 或 Edge。</p>
      ) : null}
      {!unsupported && !secureContext ? (
        <p className="error">当前页面无法使用麦克风，请用 localhost 打开后再试。</p>
      ) : null}

      <div className="record-row">
        <button
          ref={buttonRef}
          type="button"
          className={`record-button${phase === "recording" ? " is-recording" : ""}`}
          disabled={blocked}
          aria-pressed={phase === "recording"}
          onPointerDown={handlePointerDown}
          onPointerEnter={() => setPointerOutside(false)}
          onPointerLeave={() => {
            if (sessionRef.current && !sessionRef.current.stopRequested) {
              setPointerOutside(true);
            }
          }}
          onContextMenu={(event) => event.preventDefault()}
        >
          {buttonLabel}
        </button>
        {phase === "opening" || phase === "recording" ? (
          <button
            type="button"
            className="ghost"
            data-cancel-recording
            onPointerDown={(event) => {
              event.preventDefault();
              stopRef.current("cancel", event);
            }}
          >
            取消
          </button>
        ) : null}
      </div>

      {phase === "recording" ? (
        <p className="timer">
          已录 {formatSeconds(elapsedMs)}
          {pointerOutside ? "，已移出按钮，松开后将结束录音" : ""}
        </p>
      ) : null}
      {notice.text ? <p className={notice.type === "error" ? "error" : "ok"}>{notice.text}</p> : null}

      {clip ? (
        <div className="clip">
          <audio
            controls
            preload="metadata"
            src={clip.url}
            onLoadedMetadata={(event) => {
              const duration = event.currentTarget.duration;
              setMediaDuration(Number.isFinite(duration) ? duration : null);
            }}
          />
          <dl className="clip-meta">
            <div>
              <dt>格式</dt>
              <dd>{clip.mimeType}</dd>
            </div>
            <div>
              <dt>大小</dt>
              <dd>{formatBytes(clip.bytes)}</dd>
            </div>
            <div>
              <dt>录制时长</dt>
              <dd>{formatSeconds(clip.durationMs)}</dd>
            </div>
            <div>
              <dt>播放器时长</dt>
              <dd>{mediaDuration == null ? "未读出" : `${mediaDuration.toFixed(1)} 秒`}</dd>
            </div>
          </dl>
          <a href={clip.url} download={clip.filename}>
            下载这份录音
          </a>
        </div>
      ) : null}
    </section>
  );
}
