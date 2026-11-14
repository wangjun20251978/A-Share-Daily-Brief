# -*- coding: utf-8 -*-
"""每日抓一次数据，生成 data/daily.json 并注入 index.html 的内置快照。

数据源：
  1) wangjun20251978/ETF-ROTATION-PRO  docs/index.html   -> 48 只 ETF 三因子实测表
  2) wangjun20251978/ETF-ROTATION-PRO  docs/history.json -> 信号归档
  3) 东方财富公开行情接口（4 大 A 股指数），失败则沿用上次数据 / 显示「数据暂缺」

设计原则：不编造数值；抓不到就留空并标注；页面永远能打开（内置快照兜底）。
"""
import os, re, json, html as htmlmod
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
DATA_FILE = os.path.join(DATA_DIR, "daily.json")
INDEX_FILE = os.path.join(BASE, "index.html")
os.makedirs(DATA_DIR, exist_ok=True)

RAW = "https://raw.githubusercontent.com/wangjun20251978/ETF-ROTATION-PRO/main/docs/"
CDN = "https://cdn.jsdelivr.net/gh/wangjun20251978/ETF-ROTATION-PRO@main/docs/"
IDX_URL = ("https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2"
           "&secids=1.000001,0.399001,0.399006,1.000688&fields=f2,f3,f12,f14")
SOURCE = "wangjun20251978/ETF-ROTATION-PRO"
NOTICE = ("本简报为公开数据的整理与界面演示，所有评分、信号、状态均为历史快照记录，"
          "不构成任何投资建议，不可作为买卖依据。市场有风险，决策请自行判断。")


def fetch(url, timeout=20):
    """urllib 为主，SSL 握手失败时回退到 curl（Windows / Actions 均自带）"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        print("urllib 失败(%s)，改用 curl" % type(e).__name__)
        import subprocess
        p = subprocess.run(["curl", "-sL", "-m", str(timeout), "-A", "Mozilla/5.0", url],
                           capture_output=True, timeout=timeout + 8)
        if p.returncode == 0 and p.stdout:
            return p.stdout.decode("utf-8")
        raise


def fetch_repo(path):
    """raw 实时优先，jsDelivr CDN 兜底；都不通再由 main() 用仓库内离线快照"""
    for base, t in ((RAW, 8), (CDN, 15)):
        try:
            return fetch(base + path, timeout=t)
        except Exception as e:
            print("源不可用 %s (%s)" % (base.split("/")[2], type(e).__name__))
    raise RuntimeError("两个在线数据源均不可用")


def clean(s):
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def num(s, default=0.0):
    t = str(s).replace("%", "").replace("+", "").replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return default


def parse_table(src):
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", src, re.S):
        c = [clean(x) for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(c) < 17 or not c[0].isdigit():
            continue
        out.append({
            "code": c[1], "name": c[2], "price": c[3],
            "chg": c[4], "r5": c[5], "r10": c[6],
            "m": c[7], "vpos": c[8], "v": c[9], "fr": c[10], "f": c[11],
            "score": c[12], "risk": c[13], "days": c[14], "best": c[15], "act": c[16],
            "nChg": num(c[4]), "nR5": num(c[5]), "nR10": num(c[6]),
            "nScore": num(c[12]), "nM": num(c[7]), "nV": num(c[9]), "nF": num(c[11]),
        })
    return out


def old_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_indices(prev):
    try:
        j = json.loads(fetch(IDX_URL, timeout=10))
        diff = (j.get("data") or {}).get("diff") or []
        out = []
        for x in diff:
            out.append({"name": x.get("f14", "—"), "val": str(x.get("f2", "—")),
                        "chg": num(x.get("f3"), 0)})
        if len(out) >= 4:
            print("指数：实时抓取成功")
            return out
    except Exception as e:
        print("指数：抓取失败，沿用上次数据 /", type(e).__name__)
    p = (prev.get("market") or {}).get("indices") or []
    if p:
        return p
    return [{"name": n, "val": "—", "chg": None} for n in
            ["上证指数", "深证成指", "创业板指", "科创50"]]


def main():
    prev = old_data()
    try:
        table = parse_table(fetch_repo("index.html"))
        hist = json.loads(fetch_repo("history.json"))
    except Exception as e:
        print("联网抓取失败(%s)，改用仓库内离线快照" % type(e).__name__)
        snap_file = os.path.join(DATA_DIR, "etf_snapshot.json")
        with open(snap_file, encoding="utf-8") as f:
            snap = json.load(f)
        table, hist = snap["table"], snap["history"]
    if not table:
        raise RuntimeError("ETF 表格解析为空，保留原有数据不变")
    last = hist[-1] if hist else {}
    print("ETF 行数:", len(table), "| 历史记录:", len(hist), "| 最新:", last)

    up = sum(1 for x in table if x["nChg"] > 0)
    down = sum(1 for x in table if x["nChg"] < 0)
    flat = len(table) - up - down
    avg = sum(x["nChg"] for x in table) / len(table)
    by_chg = sorted(table, key=lambda x: x["nChg"], reverse=True)
    passed = [x for x in table if "未通过" not in x["risk"]]
    total_pass = last.get("pass", len(passed))
    total_pool = last.get("total", len(table))

    # 池内温度：上涨占比 60% + 风控通过率 40%，自定义口径
    temp = int(round((up / len(table)) * 60 + (total_pass / max(1, total_pool)) * 40))
    state = last.get("market", "—")
    position = str(last.get("weight", "—")) + "%"

    # 信号卡：优先风控通过，按综合分取 5 只，不足则用综合分补齐
    pool = sorted(passed, key=lambda x: x["nScore"], reverse=True)
    pool += [x for x in sorted(table, key=lambda x: x["nScore"], reverse=True) if x not in pool]
    signals = []
    for x in pool[:5]:
        ok = "未通过" not in x["risk"]
        status = "信号" if ok else ("风险" if x["nChg"] <= -3 else "观察")
        conclusion = ("综合分 %s，M %s / V %s / F %s；5日 %s、10日 %s。风控%s。"
                      % (x["score"], x["m"], x["v"], x["f"], x["r5"], x["r10"],
                         "通过" if ok else "未通过"))
        checks = ("检查项：%s · 信号天数 %s · 最优持股 %s · 原表操作 %s"
                  % (x["risk"], x["days"] or "—", x["best"] or "—", x["act"]))
        signals.append({
            "name": x["name"], "code": x["code"], "score": x["score"], "status": status,
            "conclusion": conclusion, "m": x["m"], "v": x["v"], "f": x["f"],
            "checks": checks,
            "discipline": "仅作跟踪记录；仓位与止损按个人纪律执行，不据本页下单。",
        })

    f_top = sorted(table, key=lambda x: x["nF"], reverse=True)[:3]
    r5_top = sorted(table, key=lambda x: x["nR5"], reverse=True)[:3]
    r5_bot = sorted(table, key=lambda x: x["nR5"])[:2]
    headline = ("池内 %d 只标的，上涨 %d / 下跌 %d，平均 %s；风控通过 %d 只，"
                "大盘状态「%s」，信号归档参考仓位 %s。今日以跟踪与风控为主。"
                % (len(table), up, down, ("%+.2f%%" % avg), total_pass, state, position))
    review = {
        "market": "池内 %d 只标的平均日涨幅 %s，上涨 %d 只、下跌 %d 只、平盘 %d 只；"
                  "信号归档显示大盘「%s」，总仓 %s。" % (len(table), "%+.2f%%" % avg, up, down, flat, state, position),
        "fund": "F 资金流得分靠前：%s。该项来自三因子快照的 F 列，仅反映池内相对强弱。"
                % "、".join("%s(%s)" % (x["name"], x["f"]) for x in f_top),
        "hot": "5 日收益居前：%s；靠后：%s。均为历史区间统计，不代表后续表现。"
               % ("、".join("%s %s" % (x["name"], x["r5"]) for x in r5_top),
                  "、".join("%s %s" % (x["name"], x["r5"]) for x in r5_bot)),
        "risk": "风控未通过 %d 只；检查项含乖离率、量能配合、重大利空等。"
                "本页不提供买卖指令，请独立判断并严格执行个人交易纪律。"
                % (len(table) - len(passed)),
    }

    src_time = str(last.get("time", ""))
    date = src_time[:10] or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    time_hm = src_time[11:16] or "--:--"
    data = {
        "date": date, "time": time_hm,
        "generated": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
        "source": SOURCE, "notice": NOTICE, "headline": headline,
        "market": {
            "temp": temp, "state": state, "position": position,
            "pass": total_pass, "total": total_pool,
            "indices": get_indices(prev),
            "up": up, "down": down, "flat": flat, "avg_chg": round(avg, 2),
            "top": [{"name": x["name"], "chg": x["nChg"]} for x in by_chg[:3]],
            "bottom": [{"name": x["name"], "chg": x["nChg"]} for x in by_chg[-3:]],
        },
        "signals": signals,
        "review": review,
        "history": [{"time": h.get("time", ""), "holds": h.get("holds", "—"),
                     "pass": h.get("pass", "—"), "market": h.get("market", "—"),
                     "weight": h.get("weight", "—")} for h in hist[-8:][::-1]],
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    # 注入 index.html 内置快照（本地双击 / Pages 都可用）
    with open(INDEX_FILE, encoding="utf-8") as f:
        page = f.read()
    snap = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    pat = re.compile(r'(<script id="snapshot"[^>]*>)(.*?)(</script>)', re.S)
    if not pat.search(page):
        raise RuntimeError("index.html 缺少 snapshot 占位")
    page = pat.sub(lambda m: m.group(1) + snap + m.group(3), page, count=1)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(page)
    print("已更新 data/daily.json 并注入 index.html 内置快照 | 北京", data["generated"])


if __name__ == "__main__":
    main()
