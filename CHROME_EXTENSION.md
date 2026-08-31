# Chrome 扩展

## 本地安装

1. 启动后端：`uv run uvicorn api:app --host 127.0.0.1 --port 8000`。
2. 打包：`cd frontend && npm run package:extension`。
3. 打开 `chrome://extensions`，启用“开发者模式”，选择“加载已解压的扩展程序”，目录为 `frontend/dist-extension`。

生成的商店上传包是 `frontend/clarityfinance-chrome-0.1.0.zip`。

## 发布前

当前扩展默认连接本机后端，只适合本地安装。公开发布前需要部署 HTTPS API，然后：

1. 将 `frontend/extension/manifest.json` 的 `host_permissions` 改为实际 API 域名。
2. 使用 `VITE_API_BASE=https://api.example.com npm run package:extension` 重新打包。
3. 准备 1280×800 或 640×400 的商店截图、440×280 宣传图、支持邮箱和公开隐私政策。
4. 在 Chrome Web Store Developer Dashboard 注册开发者、上传 ZIP、填写商店与隐私信息并提交审核。

扩展处理自选股、模拟持仓及投资偏好，隐私政策必须说明这些金融数据的收集、用途、保存位置和删除方式。
