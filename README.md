# pokerbot

Sequoia "No Limit" 扑克 bot 比赛的本地开发框架。规则依据官方 rules.html；消息格式、牌编码、结算规则参照官网 Exhibit B（8 人桌引擎）和 Exhibit D（消息追踪）。

## 目录

```
engine/              荷官和比赛环境
  cards.py           牌编码（0..51，rank = c % 13，suit = c // 13）+ 牌型评估（约 4 µs）
  variants.py        扑克变体：牌堆、底牌数、牌型排名、限注方式、高低分池；混合游戏轮换
  protocol.py        Action / Event / Observation：荷官和 bot 之间的消息
  table.py           荷官：一手牌（盲注、下注轮、边池、退回无人跟注的部分、1 ms 超时）
  tournament.py      8 人 SNG：2000 筹码、每 25 手升盲、200 手上限、ICM 分配剩余分数
  icm.py             Malmuth-Harville ICM（精确）：期望分数、名次概率、全下跟注所需胜率
agents/
  base.py            Agent 接口：reset / on_event / act
  baselines.py       对手池：random, station, maniac, nit, tag, pushfold, monte, codex（AI 默认款 TAG）
  registry.py        按名字列出所有 bot；没有 ours/ 时只用对手池
  adapter.py         占位：现场把官方接口转换成我们的格式
  ours/              我们的 agent（私有，不在公开仓库里）
precompute/
  build_preflop.py   线下生成 2 张底牌变体的翻前胜率表（hold'em、short deck）
  build_omaha.py     线下拟合奥马哈类翻前模型 omaha_preflop.json（需要 numpy，约 5 分钟）
  omaha_features.py  奥马哈翻前特征 + 运行时模型（纯 Python）
  build_hu_equity.py 线下生成 169×169 手牌对抗胜率表 hu_equity.json（GTO 推或弃求解用，约 1 分钟）
viz/
  server.py          本地可视化服务器（只用标准库），浏览器打开 http://127.0.0.1:8765
  static/index.html  电视转播风格牌桌：6 人桌和 8 人桌，观战或亲自对战；对战时显示翻前 GTO 建议
  static/gto.html    GTO 学习页（顶部 "GTO 学习" 按钮）：翻前范围表、按位置做题、推或弃 solver 实时求解演示
  static/gto.js      翻前范围表（100bb 近似值）、单挑推或弃纳什求解器、牌桌上的实时建议
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
python -m eval.run --variant omaha      # 换变体评估（见下方"变体"）
python -m eval.run --lineup field       # 预测的对手群体：多数是 codex 式 TAG
python -m eval.run --tables 5000 --workers 11 --no-time-limit   # 多进程；同一 --seed 结果和单进程完全一致
python -m eval.run --set use_phases=False          # 临时改 ours 的参数（需要 agents/ours/）
python -m eval.run --alt phase_open.late=1.6       # A/B：同一批牌桌各跑一次，报告逐桌配对的差值
python -m eval.run --json out.json                 # 结果另存为 JSON
python -m eval.trace --variant omaha8   # 看高低分池怎么结算
python -m precompute.build_preflop 6000 --variant shortdeck
python -m precompute.build_omaha        # omaha、omaha5、omaha8 的翻前模型
python -m engine.icm                    # ICM 耗时
python -m precompute.build_hu_equity --workers 11   # 重建 GTO 页用的手牌对抗胜率表
```

## 变体

具体变体开赛时才公布，所以引擎、对手池、我们的 agent 都按变体参数化（`engine/variants.py`）：

| 名字 | 规则 |
|---|---|
| `holdem` | 无限注德州 |
| `shortdeck` | 短牌（36 张，6 起）：A-6-7-8-9 是最小顺子，同花 > 葫芦，三条 > 顺子（Triton 规则） |
| `omaha` / `omaha-nl` | 底限注 / 无限注奥马哈：4 张底牌，必须正好用 2 张底牌 + 3 张公共牌 |
| `omaha5` | 5 张底牌的底限注奥马哈 |
| `omaha8` | 底限注奥马哈高低（8 or better）：低牌分半个底池，零头给高牌 |
| `pineapple` | 3 张底牌的德州（不弃牌，取 8 张里最好的 5 张） |
| `mixed:a,b,...` | 混合游戏：每 8 手（`TournamentConfig.variant_every`）轮换一次 |

- 底限注时 `max_raise_to` 已按"跟注后的底池"封顶；`ALL_IN` 表示加到允许的最大值。
- `Observation.variant` 和 `NEW_HAND` 事件告诉 bot 这一手是什么游戏。
- 奥马哈用 5 张牌查表评估（约 1 µs 一组），4 张底牌约 28 µs、5 张约 37 µs，留得出 1 ms 的余量。
- 如果公布的变体不在表里：在 `VARIANTS` 里加一行（牌堆、底牌数、排名顺序、最小顺子、限注、高低），
  再跑对应的 precompute 脚本。

## ICM

`engine/icm.py` 是精确的 Malmuth-Harville，结果已和逐个排列枚举对照过。

- `icm(stacks, prizes)`：每人的期望分数；0 筹码的人拿剩下最低的名次分。8 人约 0.4 ms。
- `icm_one(stacks, prizes, i)`：只算一个人，8 人约 0.13 ms。
- `allin_spot(...)`：面对全下时，弃牌、跟注赢、跟注输三种结果各值多少分，
  以及按分数算需要的胜率和只看底池赔率需要的胜率，还有泡沫系数。8 人约 0.3 ms。
- 荷官在 200 手上限时用它把未发的名次分分给存活者。

没有 `agents/ours/` 时，默认阵容里 ours 的座位换成 tag。

## 可视化牌桌

```
python -m viz.server        # 然后用浏览器打开 http://127.0.0.1:8765
```

- **WATCH AGENTS**：选 6 人桌或 8 人桌，自由安排每个座位放哪个 bot，看它们对打。
  可以调速（½× 到 16×）、暂停，"show hole cards" 控制是否显示所有底牌。
- **PLAY VS AGENTS**：自己选一个座位和 bot 对战。快捷键 F 弃牌，C 过牌或跟注，R 加注；
  也可以拖滑块，或点 MIN / ½ POT / ¾ POT / POT / ALL-IN。你出局后牌局以 4× 速度继续。
- 右侧 TRACE 按 Exhibit D 的格式实时显示荷官和 bot 之间的消息（对战模式下隐藏其他人的底牌）；
  STANDINGS 是实时筹码排名，比赛结束后弹出最终名次和得分。
- **STATS**：本桌的球员数据和电视转播式的奖项。数据有 VPIP、PFR、AF、摊牌率、摊牌胜率、运气、净输赢；
  奖项有 LUCK BOX、UNLUCKIEST、MOST NIT、ACTION PLAYER、AGGRESSOR、CALLING STATION、BLUFF KING、
  HERO CALL、SUCKOUT ARTIST、BAD BEAT、BIGGEST POT、SHOVE MACHINE。鼠标移到奖项上会高亮对应座位。
  运气 = 实际赢到的筹码 − 全下时（后面还有牌要发）按胜率应得的筹码，全桌加起来约等于 0（`viz/stats.py`）。
- 手机和平板也能用：窄屏时右侧面板收进 PANEL 按钮（平板从右侧滑出，手机从底部弹出），
  控制按钮收进 MENU；竖屏时牌桌变成竖向椭圆，大小按顶栏和操作栏之间剩下的空间计算。
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
