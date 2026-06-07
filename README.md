# 🎾 网球赛事管理系统

齐动力网球会员杯积分赛（端午站）专用赛事系统。报名 → 分组抽签 → 小组循环赛 → 淘汰赛 → 冠军。

## 功能

- **报名管理**：金数据表单收集 + CSV 批量导入
- **分组抽签**：16 人随机分 4 组（A/B/C/D），每组 4 人
- **小组循环赛**：打满 4 局无占先，2:2 抢七决胜，自动积分排名
- **淘汰赛**：固定对阵 A1vsC2 / B1vsD2 / C1vsA2 / D1vsB2，自动晋级
- **实时记分**：管理员+裁判员双角色，快速记分模式，手机友好
- **公开展示**：赛程和比分实时展示，30 秒自动刷新

## 技术栈

Python FastAPI + SQLite + Jinja2 模板，零构建步骤。

## 本地启动

```bash
pip install -r requirements.txt
set TOURNAMENT_ADMIN_PW=管理密码
set TOURNAMENT_REFEREE_PW=裁判密码
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

或双击 `start.bat`（先编辑密码）。

## 页面

| 地址 | 说明 |
|------|------|
| `/admin` | 管理后台（需登录） |
| `/public` | 公开展示页（无需登录） |

## 赛制规则

| 组别 | 计分 |
|------|------|
| U8 | 一局 11 分定胜负 |
| U10/U12/U14 | 打满 4 局无占先，2:2 抢七决胜 |

## 部署

### Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new)

或 Git 推送后 Railway 自动部署，环境变量：

```
TOURNAMENT_ADMIN_PW   = 管理员密码
TOURNAMENT_REFEREE_PW = 裁判员密码
DATABASE_PATH         = /data/tournament.db
```

### Docker

```bash
docker build -t tennis .
docker run -d -p 8000:8000 \
  -e TOURNAMENT_ADMIN_PW=xxx \
  -e TOURNAMENT_REFEREE_PW=xxx \
  -v ./data:/app \
  tennis
```
