import axios from "axios";

export const API_BASE = "http://localhost:8003";

// 略长于后端各自的完整调用预算，避免前端先断开。失败后不自动重试。
export const REQUEST_TIMEOUTS = {
  health: 5_000,
  upload: 30_000,
  asr: 70_000,
  extract: 40_000,
  search: 30_000,
  finalize: 55_000,
  audio: 20_000,
};

const client = axios.create({
  baseURL: API_BASE,
  headers: { Accept: "application/json" },
});

export class ApiFailure extends Error {
  constructor({ code, message, stage }) {
    super(message);
    this.name = "ApiFailure";
    this.code = code;
    this.stage = stage;
  }
}

export function isAborted(error) {
  return axios.isCancel(error) || error?.code === "ERR_CANCELED" || error?.name === "CanceledError";
}

function failureFromBody(body, fallback) {
  const info = body?.error;
  if (info && typeof info.message === "string" && info.message) {
    return new ApiFailure({
      code: typeof info.code === "string" ? info.code : "request_failed",
      message: info.message,
      stage: typeof info.stage === "string" ? info.stage : "request",
    });
  }
  return new ApiFailure(fallback);
}

export function describeRequestError(error) {
  if (error instanceof ApiFailure) return error;
  if (isAborted(error)) return error;
  if (error?.code === "ECONNABORTED") {
    return new ApiFailure({
      code: "timeout",
      message: "请求超时，请稍后再试。",
      stage: "client",
    });
  }
  if (!error?.response) {
    return new ApiFailure({
      code: "network",
      message: "网络不通，请确认后端已在 8003 端口启动。",
      stage: "client",
    });
  }
  return failureFromBody(error.response.data, {
    code: "request_failed",
    message: "请求失败，请稍后再试。",
    stage: "request",
  });
}

async function readSuccess(promise) {
  try {
    const response = await promise;
    const body = response.data;
    if (!body || typeof body !== "object" || !body.data || typeof body.data !== "object") {
      throw new ApiFailure({
        code: "invalid_response",
        message: "服务返回了无法识别的结果。",
        stage: "client",
      });
    }
    return {
      requestId: typeof body.request_id === "string" ? body.request_id : "",
      data: body.data,
    };
  } catch (error) {
    if (error instanceof ApiFailure || isAborted(error)) throw error;
    throw describeRequestError(error);
  }
}

export function getHealth(signal) {
  return readSuccess(client.get("/health", { timeout: REQUEST_TIMEOUTS.health, signal }));
}

export function uploadRecording(file, signal) {
  const form = new FormData();
  form.append("file", file, file.name || "recording.webm");
  return readSuccess(
    client.post("/upload", form, {
      timeout: REQUEST_TIMEOUTS.upload,
      signal,
      transformRequest: [
        (data, headers) => {
          if (typeof headers?.delete === "function") headers.delete("Content-Type");
          return data;
        },
      ],
    }),
  );
}

export function recognizeAudio(audioId, signal) {
  return readSuccess(
    client.post("/asr", { audio_id: audioId }, { timeout: REQUEST_TIMEOUTS.asr, signal }),
  );
}

export function extractPlaces(text, city, signal) {
  return readSuccess(
    client.post("/extract", { text, city }, { timeout: REQUEST_TIMEOUTS.extract, signal }),
  );
}

export function searchPlaces(places, signal) {
  return readSuccess(
    client.post(
      "/search",
      {
        city_a: places.city_a,
        address_a: places.address_a,
        city_b: places.city_b,
        address_b: places.address_b,
        category: places.category,
      },
      { timeout: REQUEST_TIMEOUTS.search, signal },
    ),
  );
}

export function finalizeReply(searchId, signal) {
  return readSuccess(
    client.post("/finalize", { search_id: searchId }, { timeout: REQUEST_TIMEOUTS.finalize, signal }),
  );
}

export async function fetchReplyAudio(audioUrl, signal) {
  try {
    const response = await axios.get(audioUrl, {
      responseType: "blob",
      timeout: REQUEST_TIMEOUTS.audio,
      signal,
    });
    const blob = response.data;
    const contentType = String(response.headers?.["content-type"] || blob?.type || "");
    if (contentType.includes("json") || contentType.startsWith("text/")) {
      const raw = typeof blob?.text === "function" ? await blob.text() : "";
      let body = null;
      try {
        body = JSON.parse(raw);
      } catch {
        body = null;
      }
      throw failureFromBody(body, {
        code: "audio_invalid",
        message: "语音加载失败，可以先看文字。",
        stage: "audio",
      });
    }
    if (!contentType.startsWith("audio/")) {
      throw new ApiFailure({
        code: "audio_invalid",
        message: "语音加载失败，可以先看文字。",
        stage: "audio",
      });
    }
    return blob;
  } catch (error) {
    if (error instanceof ApiFailure || isAborted(error)) throw error;
    if (error?.response?.data instanceof Blob) {
      const raw = await error.response.data.text();
      let body = null;
      try {
        body = JSON.parse(raw);
      } catch {
        body = null;
      }
      throw failureFromBody(body, describeRequestError({ ...error, response: undefined }));
    }
    const described = describeRequestError(error);
    if (described instanceof ApiFailure && described.code === "network") {
      throw new ApiFailure({
        code: "audio_invalid",
        message: "语音加载失败，可以先看文字。",
        stage: "audio",
      });
    }
    throw described;
  }
}
