# 上传 Git 前检查清单

本项目处理教师登录会话、模型 API 密钥和学生答题卡。上传仓库前请完成以下检查。

1. 不要提交 `config.json`、`.env`、其备份文件或任何包含 Cookie/API Key 的文件；仓库根目录的 `.gitignore` 已对此做默认保护。
2. 使用 `config.example.json` 作为公开配置样例；只保留占位值，不要填入真实 Cookie、模型密钥、学生信息或图片链接。
3. 执行 `git status --ignored`，确认 `config.json` 显示为已忽略；再执行 `git diff --cached`，逐行检查将要上传的内容。
4. 在项目中搜索 `sk-`、`Cookie`、`Authorization`、`Bearer`、`deviceId`、`tlsysSessionId` 等关键字。代码、文档和测试中可以出现字段名称或占位符，但不能出现真实值。
5. 若密钥或 Cookie 曾被加入 Git 暂存区、提交、聊天记录或截图，请先在对应服务端轮换密钥并使会话失效；仅从工作区删除不足以消除历史记录。

可在初始化仓库后运行：

```powershell
git init
git status --ignored
git add .
git diff --cached --check
git diff --cached
```

确认无误后再创建首次提交。
