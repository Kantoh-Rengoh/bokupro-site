#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_plan.py — オフの編成提案（枠整理）とドラフト候補のおすすめを作る。

build.py から呼ばれ、次の2つを書き出す。
  docs/data/roster_plan.json … オフの編成提案（6つの一覧・人数の見込み・1位指名の推奨）
  docs/draft.json            … ドラフト候補（高卒のみ）の一覧と、1位候補・狙い目・育成候補の3つの枠
しきい値はこのファイルの冒頭「設定値」にまとめてあるので、後から変えられる。

編成提案の考え方（プロ1〜2年目の選手は育成契約にできない、という仕様に合わせたもの）:
  ・支配下は、ドラフト前に目標人数（58〜60人。ページで切り替え）まで減らす
      - プロ1〜2年目の支配下選手は枠が固定（動かせない）
      - 残りの枠は「3年目以降の支配下選手」と「育成選手」を総合の高い順に並べて上から入れる
        （育成選手が入れ替わるには、総合が一定以上で、支配下の選手を2以上上回る必要がある）
      - ポジションごとの最低人数を割るときは、そのポジションの選手を残して別の選手を外す
      - 枠から外れた支配下選手は、24歳以下または伸びしろ5以上なら「育成へ」、それ以外は「自由契約」
  ・育成は、ドラフト後に 80人 になるように戦力外の人数を決める（育成の指名人数はページで入力）
      - プロ1〜2年目の育成選手は自由契約にできないので、候補に入れない
      - 候補は「予測最大80未満」の選手と「25歳以上で予測最大85以下」の選手
        ①25歳以上で総合80未満 ②25歳以上で予測最大85以下 ③24歳で75未満 ④23歳で70未満 ⑤それ以外 の順
  ・育成契約満了の一覧だけは、今の総合の高い順に並べる
  ・一覧: 育成→自由契約 ／ 支配下→自由契約 ／ 育成契約満了 ／ 育成→支配下 ／ 支配下→育成
"""
import json
import numpy as np

# ======================================================================
# 設定値（ここを変えると判定が変わる）
# ======================================================================
LIMIT_REGISTERED = 70          # 支配下の上限
LIMIT_DEVELOPMENT = 80         # 育成の上限
TARGET_REGISTERED_PRE_DRAFT = (58, 59, 60)   # ドラフト前の支配下の目標人数（ページで切り替えられる候補）
TARGET_REGISTERED_DEFAULT = 60               # 最初に選ばれている目標
TARGET_DEVELOPMENT_AFTER_DRAFT = 80          # ドラフト後の育成の目標人数
THIRD_SQUAD_BASE = 70          # 三軍の上限 = 合計 − この値

# 支配下の枠の決め方
LOCK_YEARS_PRO = 2             # プロ n 年目までの支配下選手は育成契約にできない（枠は固定）
PROMOTE_FLOOR = 82             # 育成 → 支配下：総合がこれ以上の育成選手だけが昇格の対象
PROMOTE_MARGIN = 2             # さらに、入れ替わる支配下選手より総合がこれだけ高いこと（僅差の入れ替えを防ぐ）
ROLE_MIN = {"投手": 18, "捕手": 3, "内野手": 8, "外野手": 6}   # 支配下（3年目以降＋昇格）に最低これだけ残す
# 枠から外れた支配下選手の行き先
TO_DEV_MAX_AGE = 24            # この年齢以下、または
TO_DEV_MIN_UPSIDE = 5          # 伸びしろ（予測最大 − 総合）がこれ以上 → 育成へ。それ以外は自由契約
                               # （下降期・外国人・予測最大が RELEASE_SAFE_PMAX 未満の選手は、条件に関係なく自由契約）

# 育成の戦力外（自由契約）の候補と優先順位
RELEASE_LOCK_YEARS_PRO = 2     # プロ n 年目までの育成選手は自由契約にできない（候補に入れない）
RELEASE_SAFE_PMAX = 80         # 予測最大がこれ以上（総合80以上の見込みあり）の選手は候補にしない（下の ② は例外）
RELEASE_TIERS = (              # (段階, 年齢の下限, 年齢の上限, 総合がこれ未満)。段階の小さい順に優先して戦力外にする
    (1, 25, 99, 80),           # ① 25歳以上で総合80未満
    (3, 24, 24, 75),           # ③ 24歳で総合75未満
    (4, 23, 23, 70),           # ④ 23歳で総合70未満
)                              # ⑤ 上のどれでもないが予測最大が RELEASE_SAFE_PMAX 未満
RELEASE_OLD_AGE = 25           # ② この年齢以上で…
RELEASE_OLD_PMAX = 85          # …予測最大がこれ以下の選手は、総合80以上の見込みがあっても候補にする
RELEASE_OLD_TIER = 2           # ② の優先順位（① の次）
RELEASE_LAST_TIER = 5          # ⑤ の優先順位
RELEASE_BORDER = 2             # 予測最大が基準のすぐ下（基準 − この値 まで）の候補には「境界」の印（予測の誤差で入れ替わりうる）
RELEASE_NEXT_SHOW = 5          # 次点として見せる人数
# 戦力外にしない例外（ID で指定）
D2F_KEEP_IDS = {
    "21097BE8-2C7A-465D-9C22-B8C30C15D4A9": "戸池",   # 残留（検証中）
}

# 6. ドラフト候補（編成提案の一覧と docs/draft.json で共通）
DRAFT_BACKGROUNDS = ("高卒",)  # 対象の経歴（中卒・大卒・社卒・独立は対象外）
DRAFT_EXCLUDE_PMAX = 70        # 予測最大がこれ以下の候補は「対象外」として薄く表示
DRAFT_GRADES = ("A",)          # 編成提案の一覧に出す将来性
DRAFT_CAMP_BONUS = 2.3         # 候補の1年目開幕時の総合 = 今の総合 + これ（平均的なキャンプの伸び）
DRAFT_FEW_FIRST = 1            # 「1位候補にしている球団が少ない」= この数以下（編成提案の1位推奨）
PROSPECT_TRAIN_MIN_AGE = 31    # 候補の予測モデルに使う在籍選手の年齢（これ以上）
DRAFT_TOP_N = 8                # 各枠に出す人数
DRAFT_SLEEPER_INTEREST = 1     # 狙い目：興味を持つ球団がこの数以下
DRAFT_DEV_RANK = 100           # 育成候補：スカウト順位がこれ以上（低い）で…
DRAFT_DEV_PMAX = 75            # …予測最大がこれ以上
DRAFT_LOTTERY = ((3, "高"), (1, "中"), (0, "低"))  # 興味球団数 → 抽選の可能性

GRADE_NUM = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
ROLE_SHORT = {"投手": "投", "捕手": "捕", "内野手": "内", "外野手": "外"}
POS_ROLE = {"一塁": "内野手", "二塁": "内野手", "三塁": "内野手", "遊撃": "内野手", "左翼": "外野手", "中堅": "外野手", "右翼": "外野手", "捕手": "捕手", "投手": "投手"}


def log(msg):
    print(msg, flush=True)


# ======================================================================
# ドラフト候補の予測モデル（引退選手＋高齢の在籍選手で学習）
# ======================================================================
def _first_age(p, hs, player_ages):
    ages = player_ages(p, hs)
    return ages[0] if ages and ages[0] is not None else None


def prospect_features(first_overall, first_age, grade, attention, is_pitcher, dev_pot, rise, peak, vol):
    f = lambda v: float(v) if v is not None else np.nan
    return [f(first_overall), f(first_age), float(GRADE_NUM.get(grade, 3)), float(GRADE_NUM.get(attention, 3)),
            1.0 if is_pitcher else 0.0, f(dev_pot), f(rise), f(peak), f(vol)]


def fit_prospect_model(train_players, B):
    """B は build モジュール。戻り値: (imputer, 最高総合モデル, 到達年齢モデル, 平均誤差)"""
    from sklearn.model_selection import GroupKFold
    X, y, yage, grp = [], [], [], []
    for p in train_players:
        hs = B.hist_sorted(p)
        if len(hs) < 2:
            continue
        ages = B.player_ages(p, hs)
        if not ages or any(a is None for a in ages):
            continue
        g = p.get("growth") or {}
        dr = p.get("draftRecord") or {}
        ovs = [float(h["overall100"]) for h in hs]
        X.append(prospect_features(ovs[0], ages[0], dr.get("potentialGrade"), dr.get("attentionGrade"), p.get("role") == "投手",
                                   p.get("developmentPotential"), g.get("riseRate"), g.get("peakAge"), p.get("growthVolatility")))
        y.append(max(ovs)); yage.append(ages[ovs.index(max(ovs))]); grp.append(p.get("id"))
    X = np.array(X, float); y = np.array(y, float); yage = np.array(yage, float); grp = np.array(grp)
    imp = B.Imputer(X)
    Xi = imp(X)
    errs = []
    for tr, te in GroupKFold(n_splits=5).split(Xi, y, grp):
        m = B.make_gbr().fit(Xi[tr], y[tr])
        errs.append(float(np.mean(np.abs(m.predict(Xi[te]) - y[te]))))
    mae = float(np.mean(errs))
    log(f"  ドラフト候補の予測: 選手単位の交差検証で平均誤差 {mae:.2f}（{len(y)} 人）")
    return imp, B.make_gbr().fit(Xi, y), B.make_gbr().fit(Xi, yage), round(mae, 2)


def predict_prospect(pm, ov_models, role, ab6, age, grade, attention, dev_pot, growth, vol):
    """候補1人（1役割）の総合・予測最大・到達年齢。ab6 は能力6項目のリスト"""
    imp, m_max, m_age, _ = pm
    cur = ov_models[role].predict(ab6)
    g = growth or {}
    x = imp([prospect_features(cur + DRAFT_CAMP_BONUS, int(age or 18) + 1, grade, attention, role == "投手",
                               dev_pot, g.get("riseRate"), g.get("peakAge"), vol)])
    pmax = max(int(round(float(m_max.predict(x)[0]))), cur)
    reach = max(int(round(float(m_age.predict(x)[0]))), int(age or 18) + 1)
    return cur, pmax, reach


# ======================================================================
# 在籍選手の判定
# ======================================================================
TIER_MARK = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤"}


def release_tier(age, overall, pmax):
    """育成の戦力外候補の段階（1〜5）と説明。候補でなければ (None, "")"""
    if pmax < RELEASE_SAFE_PMAX:
        for tier, lo, hi, need in RELEASE_TIERS:
            if lo <= age <= hi and overall < need:
                who = f"{lo}歳以上" if hi >= 99 else f"{lo}歳"
                return tier, f"{TIER_MARK[tier]}{who}で総合{need}未満"
    if age >= RELEASE_OLD_AGE and pmax <= RELEASE_OLD_PMAX:
        return RELEASE_OLD_TIER, f"{TIER_MARK[RELEASE_OLD_TIER]}{RELEASE_OLD_AGE}歳以上で予測最大{RELEASE_OLD_PMAX}以下"
    if pmax < RELEASE_SAFE_PMAX:
        return RELEASE_LAST_TIER, f"{TIER_MARK[RELEASE_LAST_TIER]}予測最大{RELEASE_SAFE_PMAX}未満"
    return None, ""


def release_border(tier, pmax):
    """予測最大が基準のすぐ下（誤差で候補から外れうる）か"""
    if tier == RELEASE_OLD_TIER:
        return pmax > RELEASE_OLD_PMAX - RELEASE_BORDER
    return pmax >= RELEASE_SAFE_PMAX - RELEASE_BORDER


def _row_base(r, p):
    return {
        "id": r["id"], "名前": r["名前"], "背番号": r["背番号"], "年齢": r["年齢"],
        "ポジ": ROLE_SHORT.get(r["役割"], ""), "役割": r["役割"], "所属": r["所属"],
        "総合": r["現在"], "予測最大": r["_fut"], "伸びしろ": max(0, r["_fut"] - r["現在"]),
        "状態": r["状態"], "外国人": bool(p.get("foreign")), "年目": p.get("yearsPro"),
        "ドラフト順位": r["ドラフト順位"], "将来性": r["将来性"], "二刀流": bool(r.get("二刀流")),
    }


def _sort_rows(rows):
    rows.sort(key=lambda x: (x["年齢"], -x["予測最大"], -x["総合"]))
    return rows


def _mark(b, verdict, why):
    c = dict(b); c["判定"], c["理由"] = verdict, why
    return c


def destination(b):
    """支配下の枠から外れた選手の行き先（育成へ／自由契約）と理由"""
    if b["外国人"]:
        return "戦力外", "外国人（育成にできない）"
    if b["状態"] == "下降期":
        return "戦力外", "下降期"
    if b["予測最大"] < RELEASE_SAFE_PMAX:
        return "戦力外", f"予測最大{RELEASE_SAFE_PMAX}未満"
    if b["年齢"] <= TO_DEV_MAX_AGE:
        return "育成へ", f"{TO_DEV_MAX_AGE}歳以下"
    if b["伸びしろ"] >= TO_DEV_MIN_UPSIDE:
        return "育成へ", f"伸びしろ{TO_DEV_MIN_UPSIDE}以上"
    return "戦力外", f"{TO_DEV_MAX_AGE + 1}歳以上で伸びしろ{TO_DEV_MIN_UPSIDE - 1}以下"


def registered_plan(regs, devs, target):
    """支配下の枠を決める。regs: 支配下の行、devs: 育成の行、target: ドラフト前の支配下の目標人数。
    戻り値: dict(固定, 枠, 当落線, 昇格, 育成へ, 自由契約, 次点, 確保, 支配下, 育成)"""
    locked = [b for b in regs if (b["年目"] or 0) <= LOCK_YEARS_PRO]
    inc = [b for b in regs if (b["年目"] or 0) > LOCK_YEARS_PRO]
    slots = max(0, target - len(locked))
    # 順位付け：支配下はそのままの総合、育成は「総合 − PROMOTE_MARGIN」で比べる（同点は支配下を優先）
    pool = [(b["総合"], 1, b["予測最大"], b) for b in inc]
    pool += [(b["総合"] - PROMOTE_MARGIN, 0, b["予測最大"], b) for b in devs if b["総合"] >= PROMOTE_FLOOR]
    pool.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3]["年齢"]))
    sel = pool[:slots]
    rest = pool[slots:]
    # ポジションの最低人数を守る：足りないポジションの支配下選手を戻し、余っているポジションの最下位を外す
    guarded = []
    for _ in range(len(pool)):
        cnt = {}
        for t in sel:
            cnt[t[3]["役割"]] = cnt.get(t[3]["役割"], 0) + 1
        short = [r for r, m in ROLE_MIN.items() if cnt.get(r, 0) < m]
        if not short:
            break
        add = next((t for t in rest if t[1] == 1 and t[3]["役割"] in short), None)
        drop = next((t for t in reversed(sel) if cnt.get(t[3]["役割"], 0) > ROLE_MIN.get(t[3]["役割"], 0) and t[3]["id"] not in guarded), None)
        if add is None or drop is None:
            break
        sel.remove(drop); rest.remove(add)
        sel.append(add); rest.append(drop)
        guarded.append(add[3]["id"])
        sel.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3]["年齢"]))
        rest.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3]["年齢"]))
    sel_ids = {t[3]["id"] for t in sel}
    kept = [t[3] for t in sel if t[1] == 1]
    line = min((b["総合"] for b in kept if b["id"] not in guarded), default=None)
    promoted = [_mark(t[3], "昇格", f"総合{t[3]['総合']}（支配下の当落線{line}を{PROMOTE_MARGIN}以上上回る）" if line is not None else f"総合{PROMOTE_FLOOR}以上")
                for t in sel if t[1] == 0]
    to_dev, release = [], []
    for b in sorted([b for b in inc if b["id"] not in sel_ids], key=lambda x: (x["総合"], x["予測最大"], -x["年齢"])):
        verdict, why = destination(b)
        (to_dev if verdict == "育成へ" else release).append(_mark(b, verdict, f"総合{b['総合']}で枠外・{why}"))
    nxt = [_mark(b, "次点", f"総合{b['総合']}（当落線のすぐ上）")
           for b in sorted([b for b in kept if b["id"] not in guarded], key=lambda x: (x["総合"], x["予測最大"], -x["年齢"]))[:RELEASE_NEXT_SHOW]]
    keep = [_mark(b, "残留（ポジション確保）", f"{b['役割']}が最低{ROLE_MIN.get(b['役割'], 0)}人を割るため残す") for b in kept if b["id"] in guarded]
    return {
        "固定": len(locked), "枠": slots, "当落線": line,
        "昇格": _sort_rows(promoted), "育成へ": to_dev, "自由契約": release, "次点": nxt, "確保": keep,
        "支配下": len(locked) + len(sel), "育成": len(devs) - len(promoted) + len(to_dev),
    }


def classify_players(rows, expiry_ids, B):
    """rows は build.compute_players の結果（_fut, _p 付き）。
    戻り値: dict(案{目標: registered_plan の結果}, 満了, 候補（育成の戦力外・順位付き）, 例外, 現在{支配下, 育成})"""
    regs, devs, exp, keep, cand = [], [], [], [], []
    locked = 0
    for r in rows:
        p = r["_p"]
        b = _row_base(r, p)
        b["満了"] = r["id"] in expiry_ids
        if not p.get("developmentContract"):
            regs.append(b)
            continue
        devs.append(b)
        tier, tier_text = release_tier(b["年齢"], b["総合"], b["予測最大"])
        in_keep = r["id"] in D2F_KEEP_IDS
        # プロ1〜2年目の育成選手は自由契約にできない（年目が分からない選手は対象外にしない）
        is_locked = 1 <= (b["年目"] or 0) <= RELEASE_LOCK_YEARS_PRO
        if is_locked:
            locked += 1
            tier, tier_text = None, f"プロ{b['年目']}年目（{RELEASE_LOCK_YEARS_PRO}年目までは自由契約にできない）"
        if b["満了"]:
            why = "例外リスト（検証中のため残す）" if in_keep else (tier_text if tier or is_locked else "戦力外の基準に当てはまらない")
            exp.append(_mark(b, "", why))
        if tier is None:
            continue
        if in_keep:
            keep.append(_mark(b, "残留（検証中）", "例外リスト"))
            continue
        c = _mark(b, "", tier_text)
        c["段階"] = tier
        c["境界"] = release_border(tier, b["予測最大"])
        cand.append(c)
    # 段階（①→⑤）→ 予測最大の低い順 → 総合の低い順 → 年齢の高い順
    cand.sort(key=lambda x: (x["段階"], x["予測最大"], x["総合"], -x["年齢"]))
    for i, c in enumerate(cand):
        c["順"] = i + 1
    plans = {str(t): registered_plan(regs, devs, t) for t in TARGET_REGISTERED_PRE_DRAFT}
    # 育成契約満了だけは、今の総合の高い順に並べる
    exp.sort(key=lambda x: (-x["総合"], -x["予測最大"], x["年齢"]))
    return {"案": plans, "満了": exp, "候補": cand, "例外": _sort_rows(keep), "育成の固定": locked,
            "現在": {"支配下": len(regs), "育成": len(devs)}}


# ======================================================================
# ドラフト候補
# ======================================================================
def need_matches(slot, role):
    """補強方針の枠（例：救援投手、内野手）が候補の役割に合うか"""
    s = str(slot or "")
    if "投手" in s:
        return role == "投手"
    for pos, rl in POS_ROLE.items():
        if pos in s and rl == role:
            return True
    return role in s


def lottery_label(n):
    for th, lab in DRAFT_LOTTERY:
        if n >= th:
            return lab
    return "低"


def draft_candidates(p0, own_team, ov_models, pm, B):
    """ドラフト候補の全員分（対象の経歴のみ）の情報と、球団の関心・補強方針などをまとめる"""
    d = p0.get("draft") or {}
    prospects = d.get("prospects") or []
    stage = d.get("stage")
    board = d.get("interestBoard") or {}
    board = {t: list(v or []) for t, v in board.items() if t != own_team} if isinstance(board, dict) else {}
    dev_board = d.get("developmentInterestBoard") or {}
    dev_board = {t: list(v or []) for t, v in dev_board.items() if t != own_team} if isinstance(dev_board, dict) else {}
    declared_team = d.get("declaredFirstRoundPickTeam")
    declared_id = d.get("declaredFirstRoundProspectID")
    needs = [n for n in (d.get("needs") or []) if isinstance(n, dict)]
    interest, first, dev_interest = {}, {}, {}
    for t, ids in board.items():
        for i, pid in enumerate(ids):
            interest[pid] = interest.get(pid, 0) + 1
            if i == 0:
                first[pid] = first.get(pid, 0) + 1
    for t, ids in dev_board.items():
        for pid in ids:
            dev_interest[pid] = dev_interest.get(pid, 0) + 1
    name_count = {}
    for q in prospects:
        name_count[q.get("surname")] = name_count.get(q.get("surname"), 0) + 1

    def side(q, role, ab6, growth):
        cur, pmax, reach = predict_prospect(pm, ov_models, role, ab6, q.get("age"), q.get("assignedDevelopmentGrade"),
                                            q.get("assignedAttentionGrade"), q.get("developmentPotential"), growth, q.get("growthVolatility"))
        g = growth or {}
        out = {"役割": role, "ポジ": ROLE_SHORT.get(role, ""), "総合": cur, "予測最大": pmax, "到達年齢": reach,
               "誤差": B.error_margin(True, cur, int(q.get("age") or 18)),
               "タイプ": B.ARCHETYPE.get(g.get("archetype"), str(g.get("archetype") or "不明")), "設定ピーク年齢": g.get("peakAge")}
        ab_map = B.AB_PITCHER if role == "投手" else B.AB_BATTER
        for key, (lab, a) in zip(B.AB_KEYS, ab_map):
            out[key] = int(round(ab6[B.AB6.index(a)]))
        return out

    # 全候補の予測（同姓の注記や、将来性A以外の表示にも使う）
    pred = {}
    for q in prospects:
        role = q.get("role")
        vec = B.ability_vec(q)
        if role not in ov_models or vec is None:
            continue
        main = side(q, role, vec, q.get("growth"))
        tw = q.get("twoWay") if isinstance(q.get("twoWay"), dict) else None
        batter = None
        if tw and tw.get("fielderRole") in ov_models and tw.get("fielderRole") != "投手" and all(tw.get(a) is not None for a in ("contact", "power", "speed", "fielding")):
            ab6 = [float(tw["contact"]), float(tw["power"]), float(tw["speed"]), float(tw["fielding"]), float(q.get("arm") or 0), float(q.get("stamina") or 0)]
            batter = side(q, tw["fielderRole"], ab6, tw.get("battingGrowth") or q.get("growth"))
        pred[q["id"]] = (main, batter)

    rows = []
    for q in prospects:
        if q.get("background") not in DRAFT_BACKGROUNDS or q["id"] not in pred:
            continue
        main, batter = pred[q["id"]]
        best = main
        if batter and (batter["予測最大"], batter["総合"]) > (main["予測最大"], main["総合"]):
            best = batter
        same = []
        for o in prospects:
            if o.get("surname") == q.get("surname") and o["id"] != q["id"]:
                if o["id"] in pred:
                    same.append(f"{o.get('background')}・{ROLE_SHORT.get(o.get('role'), '')}・将来性{o.get('assignedDevelopmentGrade')}・予測{max(x['予測最大'] for x in pred[o['id']] if x)}")
                else:
                    same.append(f"{o.get('background')}・予測なし")
        pr = q.get("positionRatings") or []
        pos_pairs = []
        for i in range(0, len(pr) - 1, 2):
            try:
                pos_pairs.append((str(pr[i]), int(pr[i + 1])))
            except Exception:
                pass
        pos_pairs.sort(key=lambda t: -t[1])
        subs = []
        for nm, _ in pos_pairs:
            c = ROLE_SHORT.get(POS_ROLE.get(nm, ""), "")
            if c and c != main["ポジ"] and c not in subs:
                subs.append(c)
        if batter and batter["ポジ"] not in subs and batter["ポジ"] != main["ポジ"]:
            subs.append(batter["ポジ"])
        matched = [n.get("slot") for n in needs if need_matches(n.get("slot"), main["役割"]) or (batter and need_matches(n.get("slot"), batter["役割"]))]
        n_int = interest.get(q["id"], 0)
        row = {
            "id": q["id"], "名前": q.get("surname"), "年齢": q.get("age"), "役割": main["役割"], "ポジ": main["ポジ"], "サブポジ": "・".join(subs),
            "守備位置": "／".join(f"{nm} {v}" for nm, v in pos_pairs),
            "経歴": q.get("background"), "出身": q.get("origin") or "", "利き": q.get("handedness") or "",
            "将来性": q.get("assignedDevelopmentGrade") or "-", "注目度": q.get("assignedAttentionGrade") or "-",
            "スカウト順位": q.get("scoutRank"),
            "総合": best["総合"], "予測最大": best["予測最大"], "到達年齢": best["到達年齢"], "誤差": best["誤差"],
            "タイプ": best["タイプ"], "設定ピーク年齢": best["設定ピーク年齢"],
            "関心数": n_int, "1位候補数": first.get(q["id"], 0), "育成関心数": dev_interest.get(q["id"], 0),
            "抽選": lottery_label(n_int),
            "補強方針": "・".join(dict.fromkeys(str(s) for s in matched if s)),
            "同姓": "／".join(same), "公言": declared_team if q["id"] == declared_id else "",
            "対象外": best["予測最大"] <= DRAFT_EXCLUDE_PMAX, "推奨": "", "枠": [],
            "メモ": q.get("note") or "", "二刀流": bool(batter),
        }
        for key in B.AB_KEYS:
            row[key] = main[key]
        if batter:
            row["投手"] = main if main["役割"] == "投手" else batter
            row["野手"] = batter if main["役割"] == "投手" else main
        rows.append(row)
    rows.sort(key=lambda x: (-x["予測最大"], -x["総合"]))

    declared = None
    if declared_team and declared_id:
        name = next((q.get("surname") for q in prospects if q["id"] == declared_id), None)
        declared = {"球団": declared_team, "選手": name}
    upcoming = p0.get("upcomingDraftProspects") or d.get("upcomingDraftProspects") or []
    return {
        "候補": rows, "候補数": len(prospects), "段階": stage, "ドラフト年": d.get("year"), "公言": declared,
        "他球団数": len(board), "育成関心あり": bool(dev_board),
        "補強方針": [{"枠": n.get("slot"), "一言": n.get("comment")} for n in needs],
        "補強方針の見出し": d.get("needsHeadline") or "", "補強方針のまとめ": d.get("needsClosing") or "",
        "来年の候補数": len(upcoming) if isinstance(upcoming, list) else 0,
    }


def plan_draft_section(draft):
    """編成提案の一覧6（将来性Aのみ）と1位指名の推奨"""
    rows = [dict(r) for r in draft["候補"] if r["将来性"] in DRAFT_GRADES]
    rows.sort(key=lambda x: (x["年齢"], -x["予測最大"], -x["総合"]))
    # 1位指名の推奨：1位候補にしている球団が少ない候補の中で予測最大が最も高い選手と、その次点
    pool = [x for x in rows if not x["対象外"]]
    few = [x for x in pool if x["1位候補数"] <= DRAFT_FEW_FIRST]
    if len(few) < 2:
        few = pool
    # 予測最大が同じなら、今の総合が高い（確実性が高い）方を先にする
    few = sorted(few, key=lambda x: (-x["予測最大"], -x["総合"], x["1位候補数"]))
    rec = {}
    if few:
        few[0]["推奨"] = "1位"
        rec["1位"] = few[0]["名前"]
        text = f"1位は{few[0]['名前']}（{few[0]['ポジ']}・予測最大{few[0]['予測最大']}・1位候補にしている球団 {few[0]['1位候補数']}）"
        if len(few) > 1:
            few[1]["推奨"] = "外れ1位"
            rec["外れ"] = few[1]["名前"]
            text += f"。抽選に外れたら{few[1]['名前']}（{few[1]['ポジ']}・予測最大{few[1]['予測最大']}・1位候補にしている球団 {few[1]['1位候補数']}）"
            if few[1]["同姓"]:
                text += "※同姓の候補あり"
        rec["文"] = text + "。"
    out = {k: v for k, v in draft.items() if k != "候補"}
    out["候補"] = rows
    out["推奨"] = rec
    return out


def draft_frames(draft):
    """docs/draft.json 用の3つの枠。戻り値: {枠名: [id, ...]}（候補の行にも「枠」を書き込む）"""
    rows = draft["候補"]
    by_id = {r["id"]: r for r in rows}
    eligible = [r for r in rows if not r["対象外"]]
    top = sorted(eligible, key=lambda x: (-x["予測最大"], -x["総合"]))[:DRAFT_TOP_N]
    sleepers = sorted([r for r in eligible if r["関心数"] <= DRAFT_SLEEPER_INTEREST], key=lambda x: (-x["予測最大"], -x["総合"]))[:DRAFT_TOP_N]
    devs = sorted([r for r in rows if (r["スカウト順位"] or 0) >= DRAFT_DEV_RANK and r["予測最大"] >= DRAFT_DEV_PMAX],
                  key=lambda x: (-x["予測最大"], -x["総合"]))[:DRAFT_TOP_N]
    frames = {"1位候補": [r["id"] for r in top], "狙い目": [r["id"] for r in sleepers], "育成候補": [r["id"] for r in devs]}
    for name, ids in frames.items():
        for i in ids:
            by_id[i]["枠"].append(name)
    return frames


# ======================================================================
# 人数の見込み
# ======================================================================
def headcount(cls):
    reg_now, dev_now = cls["現在"]["支配下"], cls["現在"]["育成"]
    return {
        "現在": {"支配下": reg_now, "育成": dev_now, "合計": reg_now + dev_now, "三軍上限": reg_now + dev_now - THIRD_SQUAD_BASE},
        "育成の目標": TARGET_DEVELOPMENT_AFTER_DRAFT,
        "上限": {"支配下": LIMIT_REGISTERED, "育成": LIMIT_DEVELOPMENT, "三軍の基準": THIRD_SQUAD_BASE},
        "内訳": {"満了": len(cls["満了"]), "戦力外候補（育成）": len(cls["候補"])},
    }


def plan_core(rows, expiry_ids, B):
    """編成提案の本体（予測モデルを使わない部分）。roster_plan.json の中身のうち、選手の振り分けを返す"""
    cls = classify_players(rows, expiry_ids, B)
    parts = {t: (f"{lo}歳以上" if hi >= 99 else f"{lo}歳") + f"で総合{need}未満" for t, lo, hi, need in RELEASE_TIERS}
    parts[RELEASE_OLD_TIER] = f"{RELEASE_OLD_AGE}歳以上で予測最大{RELEASE_OLD_PMAX}以下"
    parts[RELEASE_LAST_TIER] = f"それ以外で予測最大{RELEASE_SAFE_PMAX}未満"
    tier_text = " → ".join(TIER_MARK[t] + parts[t] for t in sorted(parts))
    n_lock = cls["育成の固定"]
    mins = "・".join(f"{k}{v}人" for k, v in ROLE_MIN.items())
    return cls, {
        "人数": headcount(cls),
        "支配下の目標": list(TARGET_REGISTERED_PRE_DRAFT), "標準の目標": TARGET_REGISTERED_DEFAULT,
        "案": cls["案"],
        "満了": {"題": "育成契約満了", "行": cls["満了"],
                 "説明": "今オフに育成契約が満了する選手。昇格の対象なら「支配下」、戦力外の人数に入れば「自由契約」、それ以外は「育成再契約」。今の総合の高い順に並べています。"},
        "戦力外": {
            "育成": cls["候補"], "例外": cls["例外"], "次点の人数": RELEASE_NEXT_SHOW, "見込みの総合": RELEASE_SAFE_PMAX,
            "固定の年目": RELEASE_LOCK_YEARS_PRO, "固定の人数": n_lock,
            "年長の年齢": RELEASE_OLD_AGE, "年長の予測最大": RELEASE_OLD_PMAX,
            "説明": (f"ドラフト後に育成{TARGET_DEVELOPMENT_AFTER_DRAFT}人になる人数だけ、候補の上から戦力外にします。"
                     f"プロ{RELEASE_LOCK_YEARS_PRO}年目までの育成選手は自由契約にできないので、候補に入れません（今回 {n_lock}人）。"
                     f"候補は、予測最大{RELEASE_SAFE_PMAX}未満の選手と、{RELEASE_OLD_AGE}歳以上で予測最大{RELEASE_OLD_PMAX}以下の選手"
                     f"（{RELEASE_OLD_AGE - 1}歳以下で総合{RELEASE_SAFE_PMAX}以上の見込みがある選手は除外）。"
                     f"優先順は {tier_text}。①③④も予測最大{RELEASE_SAFE_PMAX}未満の選手だけです。同じ段階の中では予測最大の低い順です。"),
        },
        "説明": {
            "支配下": (f"プロ{LOCK_YEARS_PRO}年目までの支配下選手は育成にできないので枠は固定です。残りの枠には、{LOCK_YEARS_PRO + 1}年目以降の支配下選手と育成選手を総合の高い順に入れます。"
                       f"枠から外れた支配下選手は、{TO_DEV_MAX_AGE}歳以下または伸びしろ{TO_DEV_MIN_UPSIDE}以上なら「育成へ」、それ以外（下降期・外国人・予測最大{RELEASE_SAFE_PMAX}未満を含む）は「自由契約」です。"
                       f"ポジションの最低人数（{mins}）を割るときは、そのポジションの選手を残します。"),
            "昇格": f"総合{PROMOTE_FLOOR}以上の育成選手のうち、支配下の当落線を{PROMOTE_MARGIN}以上上回る選手を昇格させます（その分、支配下の下位が枠から外れます）。",
            "育成へ": f"支配下の枠から外れた{LOCK_YEARS_PRO + 1}年目以降の選手のうち、{TO_DEV_MAX_AGE}歳以下または伸びしろ{TO_DEV_MIN_UPSIDE}以上の選手。育成契約に切り替えて育てます。",
        },
    }


# ======================================================================
# 本体
# ======================================================================
def build_plan(B, p0, own, rows, retired, ov_models, game_dt, out_path, draft_path):
    """B: build モジュール。rows: compute_players の結果（_fut と _p を含む）。
    docs/data/roster_plan.json と docs/draft.json を書き出す"""
    team = p0.get("teamName") or ""
    expiry_ids = set(p0.get("developmentExpiryPending") or [])
    cls, core = plan_core(rows, expiry_ids, B)
    train = list(retired) + [p for p in own if int(p.get("age") or 0) >= PROSPECT_TRAIN_MIN_AGE]
    pm = fit_prospect_model(train, B)
    draft_all = draft_candidates(p0, team, ov_models, pm, B)
    draft_all["予測誤差"] = pm[3]
    scheduled = draft_all["段階"] == "scheduled" and bool(draft_all["候補"])
    date_str = f"{game_dt.year}年{game_dt.month}月{game_dt.day}日"

    # --- 編成提案 ---
    plan_draft = plan_draft_section(draft_all) if scheduled else {k: v for k, v in draft_all.items() if k != "候補"} | {"候補": [], "推奨": {}}
    out = {
        "球団名": team,
        "ゲーム内日付": date_str,
        "フェーズ": p0.get("phase") or "",
        "シーズン年": p0.get("seasonYear"),
    }
    out.update(core)
    out["ドラフト"] = plan_draft
    out["注意"] = ("予測最大は「今後の見込み」で、設定ピーク年齢を過ぎた選手は過去の最高値を含めません（成長予測タブと同じ値です）。"
                   f"在籍選手の予測は±3〜4程度の誤差があります。"
                   f"育成の戦力外で、予測最大が基準のすぐ下（{RELEASE_SAFE_PMAX - RELEASE_BORDER}〜{RELEASE_SAFE_PMAX - 1}、"
                   f"{RELEASE_OLD_AGE}歳以上は{RELEASE_OLD_PMAX - RELEASE_BORDER + 1}〜{RELEASE_OLD_PMAX}）の候補には「境界」の印を付けています（誤差で候補から外れることがあります）。"
                   "支配下の枠は総合の順位で決めているので、当落線の前後（次点）の選手は、ゲーム画面で起用状況を見てから決めてください。")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ": ")), encoding="utf-8")

    # --- ドラフト候補（docs/draft.json） ---
    frames = draft_frames(draft_all) if scheduled else {"1位候補": [], "狙い目": [], "育成候補": []}
    dj = {
        "球団名": team, "ゲーム内日付": date_str, "フェーズ": p0.get("phase") or "",
        "表示": scheduled, "段階": draft_all["段階"], "ドラフト年": draft_all["ドラフト年"],
        "対象の経歴": list(DRAFT_BACKGROUNDS), "他球団数": draft_all["他球団数"], "育成関心あり": draft_all["育成関心あり"],
        "公言": draft_all["公言"], "補強方針": draft_all["補強方針"], "補強方針の見出し": draft_all["補強方針の見出し"],
        "補強方針のまとめ": draft_all["補強方針のまとめ"], "来年の候補数": draft_all["来年の候補数"],
        "予測誤差": pm[3], "候補数": draft_all["候補数"],
        "枠": frames,
        "枠の条件": {"人数": DRAFT_TOP_N, "狙い目の関心数": DRAFT_SLEEPER_INTEREST, "育成の順位": DRAFT_DEV_RANK, "育成の予測最大": DRAFT_DEV_PMAX,
                     "1位推奨の将来性": list(DRAFT_GRADES), "1位推奨の1位候補数": DRAFT_FEW_FIRST},
        "枠の説明": {"1位候補": "予測最大の高い順。興味を持つ球団が多いほど抽選になりやすい",
                     "狙い目": f"興味を持つ球団が{DRAFT_SLEEPER_INTEREST}以下で予測最大が高い順（2位以降で取れる見込み）",
                     "育成候補": f"スカウト順位{DRAFT_DEV_RANK}位以下だが予測最大{DRAFT_DEV_PMAX}以上"},
        "候補": draft_all["候補"] if scheduled else [],
        "注意": (f"予測最大は1年目開幕時の総合（今の総合＋{DRAFT_CAMP_BONUS}）から予測した参考値で、平均±{pm[3]}程度の誤差があります。"
                 "能力の低い候補ほど誤差が大きく、三軍に入れると予測より上に伸びやすい傾向があります。二刀流の候補は投手・野手の高い方を表示しています。"),
    }
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(json.dumps(dj, ensure_ascii=False, separators=(",", ": ")), encoding="utf-8")

    d = cls["案"][str(TARGET_REGISTERED_DEFAULT)]
    log(f"  編成提案（目標{TARGET_REGISTERED_DEFAULT}人）: 支配下 {cls['現在']['支配下']}人のうち固定 {d['固定']}人・当落線 総合{d['当落線']}、"
        f"昇格 {len(d['昇格'])}人、育成へ {len(d['育成へ'])}人、自由契約 {len(d['自由契約'])}人、ポジション確保 {len(d['確保'])}人")
    log(f"  人数: 現在 支配下{cls['現在']['支配下']}・育成{cls['現在']['育成']} → ドラフト前 支配下{d['支配下']}・育成{d['育成']}（育成の戦力外の前）、"
        f"契約満了 {len(cls['満了'])}人、育成の戦力外候補 {len(cls['候補'])}人（{RELEASE_LOCK_YEARS_PRO}年目までで対象外 {cls['育成の固定']}人）")
    if plan_draft.get("推奨", {}).get("文"):
        log("  " + plan_draft["推奨"]["文"])
    if scheduled:
        log(f"  ドラフト候補({draft_all['ドラフト年']}年・高卒): {len(draft_all['候補'])}人、1位候補 {len(frames['1位候補'])}・狙い目 {len(frames['狙い目'])}・育成候補 {len(frames['育成候補'])}")
    else:
        log(f"  ドラフト候補: 今は表示しない時期です（段階 {draft_all['段階']}）")
    return out, dj
