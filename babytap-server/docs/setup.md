# 运行 BabyTap Server

## 本地开发

需要 Python 3.10+ 与 Node.js 24。Python 后端安装完成后，先构建上游前端静态资源；否则开发服务器能打开页面，但 CSS 和 JavaScript 会返回 404。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm ci
npx gulp build
export DJANGO_SETTINGS_MODULE=babybuddy.settings.development
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

首次迁移会沿用上游逻辑创建 `admin/admin`。登录后必须立即修改默认密码，并在用户设置中取得 API token。BabyTap 桌面端配置：

```dotenv
BABYTAP_BABYBUDDY_URL=http://127.0.0.1:8000
BABYTAP_BABYBUDDY_TOKEN=<token>
BABYTAP_BABYBUDDY_CHILD_ID=<child-id>
```

## Docker Compose

```bash
cp .env.example .env
# 修改 .env，至少替换 SECRET_KEY
docker compose up --build -d
```

这里构建的是本仓库 `Dockerfile` 中的定制源码，不依赖或拉取 Baby Buddy 官方成品镜像。SQLite 数据和媒体分别保存在命名卷 `babytap-data`、`babytap-media`。

## 验证

```bash
DJANGO_SETTINGS_MODULE=babybuddy.settings.test .venv/bin/python manage.py test
```

事件接口契约见 `docs/contracts/event-api.md`。
