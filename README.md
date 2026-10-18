# 语音约碰面地点

同一座城市里的两个人，用一句话找一个中间附近的店。页面展示识别文字、提取出的地点和店类、最多 3 家候选，以及推荐语。有语音时播放推荐，没有语音时保留文字。

本文档只说明怎样配置、启动和验收。它不表示功能已经验收通过。

## 环境

- Python 3.11
- Node.js 22.12 及以上、23 以下
- 后端端口 8003，前端端口 5175
- 浏览器打开 http://localhost:5175 。不要用 `127.0.0.1`，CORS 只允许 `http://localhost:5175`

后端依赖见 `backend/requirements.txt`：FastAPI、Uvicorn、Pydantic、python-multipart。不使用音频处理库或厂商 SDK，外部调用使用 Python 标准库。

前端依赖见 `frontend/package.json`：React 18、Vite 6、Axios。

## 配置

把 `backend/.env.example` 复制为 `backend/.env`，填写三把密钥：

```bash
BAILIAN_API_KEY=
DEEPSEEK_API_KEY=
AMAP_API_KEY=
```

`.env` 已被 Git 忽略。健康检查不读取密钥。识别、提取、找店、推荐和语音合成在密钥为空时不会调用对应的真实服务。

下面的变量只用于本地模拟故障，不要写进 `.env.example`，也不要和真实联调同时打开。修改后必须重启后端：

| 变量 | 取值 | 作用 |
| --- | --- | --- |
| `BAILIAN_ASR_MOCK` | `empty`、`error`、`timeout` | 不调用百炼识别 |
| `AMAP_SEARCH_MOCK` | `empty`、`ambiguous`、`error`、`timeout` | 不调用高德 |
| `DEEPSEEK_REPLY_MOCK` | `error`、`timeout` | 不调用 DeepSeek 生成推荐语 |
| `BAILIAN_TTS_MOCK` | `error`、`timeout`、`download` | 推荐语仍会调用 DeepSeek；不调用百炼语音，或模拟下载失败 |

地点提取没有单独的模拟开关。要看到提取失败，需要真实 DeepSeek，或使用空的 `DEEPSEEK_API_KEY` 看未配置。

模拟通过不能代替真实接口联调。真实识别、提取、找店和语音都会消耗对应服务的额度。

## 启动

后端：

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8003 --reload
```

前端另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

接口说明页：http://localhost:8003/docs

成功响应除音频文件外都是：

```json
{"request_id": "本次请求编号", "data": {}}
```

失败响应是：

```json
{"request_id": "本次请求编号", "error": {"code": "错误代号", "message": "中文提示", "stage": "出错阶段"}}
```

`GET /audio/{audio_id}` 成功时返回音频二进制和音频 `Content-Type`，不用上面的 JSON 外壳。失败时仍用 JSON 外壳。

## 数据文件

这些文件在 `backend/storage/` 下，目录已被 Git 忽略，接口响应里不返回路径。

- 上传录音：`storage/<audio_id>.webm` 和同名 `.json`。识别时检查是否超过 24 小时。
- 找店结果：`storage/searches/<search_id>.json`，含 `created_at`。当前读取时不按 24 小时拒绝。
- 推荐语音：`storage/replies/<audio_id>.<真实扩展名>` 和同名 `.json`。扩展名按文件头判断。当前没有过期删除。

没有单独的定时清理任务。密钥不要写入日志、页面或 Git。

## 测试说明

先做真实联调，再做模拟故障。一次只设置一个模拟变量，测完后去掉该变量并重启，再测真实接口。

页面路径：打开 http://localhost:5175 ，城市默认杭州，可改。按住录音 1 到 60 秒后松开。浏览器 Network 里应按顺序看到 `GET /health`、`POST /upload`、`POST /asr`、`POST /extract`、`POST /search`、`POST /finalize`，以及 `audio_url` 指向的 `GET /audio/...`。上传请求是 multipart，字段名为 `file`，`Content-Type` 由浏览器带上 boundary。其余 POST 是 JSON。

真实联调至少包括：

1. 说清同一城市的两个具体地点和一种店，页面出现识别文字、提取信息、最多 3 家候选和推荐语，并能播放 `audio_url`。候选顺序和「距中点多少米」来自接口。这个距离是到地理中点的直线距离，不是两个人相同的出行时间。
2. 拒绝麦克风、录音短于 1 秒、取消录音时，Network 里不应出现 `/upload`。
3. 口述里缺地点、不是两个人、跨城、地点含糊、地点在该城市对不上、附近没有这类店。页面停在对应中文错误，不再请求后续接口。
4. 关掉后端后再录音，页面提示网络不通。各模拟变量分别覆盖识别失败、找店失败、推荐语失败，以及语音合成或下载失败后的文字降级。
5. 某一步失败后，本轮已经得到的文字或店铺还留在页面上。立刻再录一条合格录音，旧请求被取消，旧文字、店铺和语音被清掉。
6. 用超过 24 小时的上传 `audio_id` 调用 `POST /asr`，应得到 410。`storage/` 不出现在 `git status` 里。

非法格式、超过 5MB、时长不合规要在 http://localhost:8003/docs 的 `POST /upload` 用文件测，页面录音本身不会生成这些文件。期望分别是 415、413、422。

模拟示例：

```bash
cd backend
source .venv/bin/activate
BAILIAN_TTS_MOCK=error uvicorn main:app --host 127.0.0.1 --port 8003 --reload
```

这个例子仍会调用 DeepSeek 生成推荐语，不会调用百炼语音。期望 `POST /finalize` 为 200，`reply_text` 有内容，`audio_url` 为 `null`，`warning` 有中文说明。
