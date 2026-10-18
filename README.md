# 语音约碰面地点

同一座城市里的两个人，用语音找一个中间附近的店。当前只有项目骨架：后端健康检查，以及一个能打开的前端页面。

本地环境：Python 3.11，Node.js 22.12 及以上的 22.x。后端端口 8003，前端端口 5175。

## 启动后端

在仓库根目录执行：

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8003 --reload
```

健康检查不读取密钥，也可以不创建 `.env`。需要填写密钥时，把 `backend/.env.example` 复制为 `backend/.env`。

## 启动前端

另开一个终端，在仓库根目录执行：

```bash
cd frontend
npm install
npm run dev
```

用浏览器打开 http://localhost:5175 。不要用 `127.0.0.1`，否则会和只放行 `http://localhost:5175` 的 CORS 对不上。

## 验证健康检查

- 浏览器打开 http://localhost:8003/health
- 浏览器打开 http://localhost:8003/docs ，找到 `GET /health`，点 Try it out，再点 Execute

成功时状态码是 **200**。响应体只有这两层：

```json
{"request_id": "本次请求的编号", "data": {"status": "ok"}}
```

`request_id` 每次请求都会变。`data` 里只有 `status`，值为 `ok`。

页面上应显示「正常」，以及同一形状的 JSON。

失败时，除获取音频文件的接口以外，响应使用这个外壳（本轮健康检查本身不会走到失败）：

```json
{"request_id": "本次请求编号", "error": {"code": "错误代号", "message": "给用户看的中文提示", "stage": "出错阶段"}}
```
