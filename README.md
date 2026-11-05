# pokerbot

Sequoia "No Limit" 扑克 bot 比赛的本地开发框架。规则依据官方 rules.html；消息格式、牌编码、结算规则参照官网 Exhibit B（8 人桌引擎）和 Exhibit D（消息追踪）。

## 目录

```
engine/              荷官和比赛环境
  cards.py           牌编码（0..51，rank = c % 13，suit = c // 13）+ 牌型评估（约 4 µs）
  protocol.py        Action / Event / Observation：荷官和 bot 之间的消息
  table.py           荷官：一手牌（盲注、下注轮、边池、退回无人跟注的部分、1 ms 超时）
  tournament.py      8 人 SNG：2000 筹码、每 25 手升盲、200 手上限、ICM 分配剩余分数
  icm.py             Malmuth-Harville ICM
agents/
  base.py            Agent 接口：reset / on_event / act
  baselines.py       对手池：random, station, maniac, nit, tag, pushfold, monte
  registry.py        按名字列出所有 bot；没有 ours/ 时只用对手池
  adapter.py         占位：现场把官方接口转换成我们的格式
  ours/              我们的 agent（私有，不在公开仓库里）
precompute/
  build_preflop.py   线下生成 preflop_equity.json（约 3 分钟）
viz/
  server.py          本地可视化服务器（只用标准库），浏览器打开 http://127.0.0.1:8765
  static/index.html  电视转播风格牌桌：6 人桌和 8 人桌，观战或亲自对战
  browser.py         网页版后端：在浏览器里用 Pyodide 运行同一套引擎
  web/               网页版前端：替代 server.py 回应页面请求（web.js）并运行 Python（worker.js）
  build_site.py      生成 GitHub Pages 用的静态网站 site/（不含 ours/）
eval/
  run.py             跑大量 SNG，统计平均得分、名次、耗时、超时
  trace.py           按 Exhibit D 的格式打印荷官和 bot 之间的消息
```

## 使用

需要 Python 3.10+，没有第三方依赖。在 `pokerbot` 目录下运行：

```
python -m eval.trace --hands 3          # 看一手牌里的消息往来
python -m eval.run --tables 500         # 评估：平均得分、胜率、耗时
python -m eval.run --lineup tag,tag,nit,nit,station,maniac,pushfold,monte
python -m precompute.build_preflop      # 重新生成翻前表（换变体后）
```

没有 `agents/ours/` 时，默认阵容里 ours 的座位换成 tag。

## 可视化牌桌

```
python -m viz.server        # 然后用浏览器打开 http://127.0.0.1:8765
```

- **WATCH AGENTS**：选 6 人桌或 8 人桌，自由安排每个座位放哪个 bot，看它们对打。
  可以调速（½× 到 16×）、暂停，"show hole cards" 控制是否显示所有底牌。
- **PLAY VS AGENTS**：自己选一个座位和 bot 对战。快捷键 F 弃牌，C 过牌或跟注，R 加注；
  也可以拖滑块，或点 MIN / ½ POT / ¾ POT / POT / ALL-IN。你出局后牌局以 4× 速度继续。
- 右侧 MESSAGE TRACE 按 Exhibit D 的格式实时显示荷官和 bot 之间的消息（对战模式下隐藏其他人的底牌）；
  STANDINGS 是实时筹码排名，比赛结束后弹出最终名次和得分。
- 牌局用的是和 eval/ 完全相同的荷官与 agent 代码；你的座位不受 1 ms 限制。

## 在线版

不用安装，直接打开 https://zixunhuangupenn.github.io/Hold-emGame/ 。网站只有对手池里的 bot，没有 ours。

引擎通过 Pyodide 在访问者的浏览器里运行，首次打开要从 CDN 下载约 10 MB。网页版关闭了 1 ms 限制，
因为 WebAssembly 下的耗时和比赛环境不同，页面显示的决策耗时只能作参考；要测超时请用 `eval/run.py`。

每次推送到 `main`，GitHub Actions（`.github/workflows/pages.yml`）会重新生成网站并覆盖 `gh-pages` 分支，
一两分钟后生效。也可以在仓库的 Actions 页面手动运行。本地预览：

```
python -m viz.build_site
python -m http.server 8766 --directory site
```

## 规则要点（官方 rules.html）

- 每次决策 **1 ms**，超时或报错：能过牌就过牌，否则弃牌
- 8 人 SNG，每人 2000 筹码，盲注 10/20 起，每 25 手升级，最多 200 手
- 按名次给分（分数表现场公布）；200 手打满时，剩余分数按 ICM 分给存活者
- 每桌开始 bot 会被重置，对手匿名
- 代码用 Python，实现官方 Agent 接口；文件不超过 100 MB；运行时没有网络
- 具体扑克变体在开赛时公布

**待确认（发邮件给 pokerbot@sequoiacap.com）：能否带提前写好的代码或预计算表进场。**
`TournamentConfig` 里的升盲表和分数表是猜的，现场要按公布的数据修改。
