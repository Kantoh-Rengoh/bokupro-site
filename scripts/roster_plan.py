#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_plan.py — オフの編成提案（枠整理）とドラフト候補のおすすめを作る。

build.py から呼ばれ、次の2つを書き出す。
  docs/data/roster_plan.json … オフの編成提案（6つの一覧・人数の見込み・1位指名の推奨）
  docs/draft.json            … ドラフト候補（高卒のみ）の一覧と、1位候補・狙い目・育成候補の3つの枠
しきい値はこのファイルの冒頭「設定値」にまとめてあるので、後から変えられる。

編成提案の考え方:
  ・ドラフト後に 支配下 68人・育成 80人 になるように、戦力外（自由契約）の人数を決める
    （ドラフトの指名人数はページで入力する。人数が変わると戦力外の人数も変わる）
  ・戦力外の候補は、予測最大が 80 未満の選手だけ。次の順に優先して選ぶ
      ① 25歳以上で総合80未満  ② 24歳で総合75未満  ③ 23歳で総合70未満  ④ それ以外（予測最大80未満）
  ・一覧: 1. 支配下 → 育成  2. 支配下 → 自由契約  3. 育成 → 支配下  4. 育成 → 自由契約
          5. 育成契約満了の選手（支配下／育成再契約／自由契約）  6. ドラフト候補（高卒で将来性A）
    2・4・5 の自由契約は、ページ側で指名人数に合わせて上位から選ぶ
"""
import json
import numpy as np

# ======================================================================
# 設定値（ここを変えると判定が変わる）
# ======================================================================
LIMIT_REGISTERED = 70          # 支配下の上限
LIMIT_DEVELOPMENT = 80         # 育成の上限
TARGET_REGISTERED_AFTER_DRAFT = 68    # ドラフト後の支配下の目標人数
TARGET_DEVELOPMENT_AFTER_DRAFT = 80   # ドラフト後の育成の目標人数
THIRD_SQUAD_BASE = 70          # 三軍の上限 = 合計 − この値

# 1. 支配下 → 育成
C2D_YEARS_PRO = 2              # プロ n 年目の支配下選手が対象
C2D_KEEP_ROUND = 1             # 例外：ドラフトこの順位で…
C2D_KEEP_OVERALL = 80          # …総合がこれ以上で…
C2D_KEEP_AGE = 20              # …この年齢以下なら「残留（例外）」

# 3. 育成 → 支配下
D2C_OVERALL = 82               # 総合がこれ以上 → 即昇格
D2C_EARLY_PMAX = 90            # 予測最大がこれ以上かつ…
D2C_EARLY_OVERALL = 75         # …総合がこれ以上 → 先行昇格

# 2・4・5. 戦力外（自由契約）の候補と優先順位
RELEASE_SAFE_PMAX = 80         # 予測最大がこれ以上（総合80以上の見込みあり）の選手は候補にしない
RELEASE_TIERS = (              # (段階, 年齢の下限, 年齢の上限, 総合がこれ未満)。上から順に優先して戦力外にする
    (1, 25, 99, 80),           # ① 25歳以上で総合80未満
    (2, 24, 24, 75),           # ② 24歳で総合75未満
    (3, 23, 23, 70),           # ③ 23歳で総合70未満
)                              # ④ 上のどれでもないが予測最大が RELEASE_SAFE_PMAX 未満
RELEASE_BORDER = 2             # 予測最大が「RELEASE_SAFE_PMAX − この値」以上の候補には「境界」の印（予測の誤差で入れ替わりうる）
RELEASE_NEXT_SHOW = 5          # 戦力外にならなかった候補のうち、次点として見せる人数
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
TIER_MARK = {1: "①", 2: "②", 3: "③", 4: "④"}


def release_tier(age, overall, pmax):
    """戦力外候補の段階（1〜4）。候補でなければ None"""
    if pmax >= RELEASE_SAFE_PMAX:
        return None, ""
    for tier, lo, hi, need in RELEASE_TIERS:
        if lo <= age <= hi and overall < need:
            who = f"{lo}歳以上" if hi >= 99 else f"{lo}歳"
            return tier, f"{TIER_MARK[tier]}{who}で総合{need}未満"
    return 4, f"④予測最大{RELEASE_SAFE_PMAX}未満"


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


def classify_players(rows, expiry_ids, B):
    """rows は build.compute_players の結果（_fut, _p 付き）。
    戻り値: dict(支配下→育成, 育成→支配下, 満了, 戦力外候補{支配下, 育成}, 例外, 移動後{支配下, 育成})"""
    c2d, d2c, exp, keep = [], [], [], []
    cand = {"支配下": [], "育成": []}
    moved = {"支配下": 0, "育成": 0}
    for r in rows:
        p = r["_p"]
        b = _row_base(r, p)
        ov, pmax, age = b["総合"], b["予測最大"], b["年齢"]
        dev = bool(p.get("developmentContract"))
        dr = p.get("draftRecord") or {}
        tier, tier_text = release_tier(age, ov, pmax)
        b["満了"] = r["id"] in expiry_ids
        b["元"] = ""

        def as_candidate(pool):
            """戦力外の候補として登録する（例外リストの選手は登録しない）"""
            if tier is None:
                return
            if r["id"] in D2F_KEEP_IDS:
                k = dict(b); k["判定"], k["理由"] = "残留（検証中）", "例外リスト"
                keep.append(k)
                return
            c = dict(b)
            c["段階"], c["理由"] = tier, tier_text
            c["境界"] = pmax >= RELEASE_SAFE_PMAX - RELEASE_BORDER
            cand[pool].append(c)

        if dev:
            promote = None
            if ov >= D2C_OVERALL:
                promote = "即昇格"
            elif pmax >= D2C_EARLY_PMAX and ov >= D2C_EARLY_OVERALL:
                promote = "先行昇格"
            if promote:
                moved["支配下"] += 1
                if b["満了"]:
                    b["判定"], b["理由"] = "支配下", promote + "の条件を満たす"
                    exp.append(b)
                else:
                    b["判定"] = promote
                    b["理由"] = f"総合{D2C_OVERALL}以上" if promote == "即昇格" else f"予測最大{D2C_EARLY_PMAX}以上・総合{D2C_EARLY_OVERALL}以上"
                    d2c.append(b)
                continue
            moved["育成"] += 1
            if b["満了"]:
                if r["id"] in D2F_KEEP_IDS:
                    why = "例外リスト（検証中のため残す）"
                else:
                    why = tier_text if tier else f"予測最大{RELEASE_SAFE_PMAX}以上の見込み"
                b["判定"], b["理由"] = "", why
                exp.append(b)
            as_candidate("育成")
            continue

        # 支配下
        if not b["外国人"] and p.get("yearsPro") == C2D_YEARS_PRO:
            if dr.get("round") == C2D_KEEP_ROUND and ov >= C2D_KEEP_OVERALL and age <= C2D_KEEP_AGE:
                b["判定"], b["理由"] = "残留（例外）", f"ドラフト{C2D_KEEP_ROUND}位・総合{C2D_KEEP_OVERALL}以上・{C2D_KEEP_AGE}歳以下"
                c2d.append(b)
                moved["支配下"] += 1
            else:
                # 育成へ移る。移った先（育成）で戦力外の候補にもなりうる
                b["判定"], b["理由"], b["元"] = "育成へ", f"{C2D_YEARS_PRO}年目", f"支配下{C2D_YEARS_PRO}年目"
                c2d.append(b)
                moved["育成"] += 1
                as_candidate("育成")
            continue
        moved["支配下"] += 1
        as_candidate("支配下")

    for pool in cand:
        # 段階（①→④）→ 予測最大の低い順 → 総合の低い順 → 年齢の高い順
        cand[pool].sort(key=lambda x: (x["段階"], x["予測最大"], x["総合"], -x["年齢"]))
        for i, c in enumerate(cand[pool]):
            c["順"] = i + 1
    return {"支配下→育成": _sort_rows(c2d), "育成→支配下": _sort_rows(d2c), "満了": _sort_rows(exp),
            "候補": cand, "例外": _sort_rows(keep), "移動後": moved}


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
def headcount(rows, cls):
    reg_now = sum(1 for r in rows if not r["_p"].get("developmentContract"))
    dev_now = len(rows) - reg_now
    mv = cls["移動後"]
    n_c2d = sum(1 for x in cls["支配下→育成"] if x["判定"] == "育成へ")
    n_d2c = len(cls["育成→支配下"]) + sum(1 for x in cls["満了"] if x["判定"] == "支配下")
    return {
        "現在": {"支配下": reg_now, "育成": dev_now, "合計": reg_now + dev_now, "三軍上限": reg_now + dev_now - THIRD_SQUAD_BASE},
        "移動後": {"支配下": mv["支配下"], "育成": mv["育成"]},   # 支配下↔育成の入れ替え後・戦力外の前
        "目標": {"支配下": TARGET_REGISTERED_AFTER_DRAFT, "育成": TARGET_DEVELOPMENT_AFTER_DRAFT},
        "上限": {"支配下": LIMIT_REGISTERED, "育成": LIMIT_DEVELOPMENT, "三軍の基準": THIRD_SQUAD_BASE},
        "内訳": {"支配下→育成": n_c2d, "育成→支配下": n_d2c, "満了": len(cls["満了"]),
                 "戦力外候補（支配下）": len(cls["候補"]["支配下"]), "戦力外候補（育成）": len(cls["候補"]["育成"])},
    }


# ======================================================================
# 本体
# ======================================================================
def build_plan(B, p0, own, rows, retired, ov_models, game_dt, out_path, draft_path):
    """B: build モジュール。rows: compute_players の結果（_fut と _p を含む）。
    docs/data/roster_plan.json と docs/draft.json を書き出す"""
    team = p0.get("teamName") or ""
    expiry_ids = set(p0.get("developmentExpiryPending") or [])
    cls = classify_players(rows, expiry_ids, B)
    train = list(retired) + [p for p in own if int(p.get("age") or 0) >= PROSPECT_TRAIN_MIN_AGE]
    pm = fit_prospect_model(train, B)
    draft_all = draft_candidates(p0, team, ov_models, pm, B)
    draft_all["予測誤差"] = pm[3]
    scheduled = draft_all["段階"] == "scheduled" and bool(draft_all["候補"])
    date_str = f"{game_dt.year}年{game_dt.month}月{game_dt.day}日"

    # --- 編成提案 ---
    plan_draft = plan_draft_section(draft_all) if scheduled else {k: v for k, v in draft_all.items() if k != "候補"} | {"候補": [], "推奨": {}}
    tier_text = "①25歳以上で総合80未満 → ②24歳で総合75未満 → ③23歳で総合70未満 → ④それ以外".replace("80未満", f"{RELEASE_TIERS[0][3]}未満", 1)
    hc = headcount(rows, cls)
    out = {
        "球団名": team,
        "ゲーム内日付": date_str,
        "フェーズ": p0.get("phase") or "",
        "シーズン年": p0.get("seasonYear"),
        "人数": hc,
        "入れ替え": {
            "支配下→育成": {"番号": 1, "題": "支配下 → 育成", "行": cls["支配下→育成"],
                           "説明": f"支配下・外国人以外でプロ{C2D_YEARS_PRO}年目の選手。ドラフト{C2D_KEEP_ROUND}位で総合{C2D_KEEP_OVERALL}以上・{C2D_KEEP_AGE}歳以下は残留（例外）。育成へ移した後に戦力外の対象になった選手は「支配下 → 自由契約」に出ます。"},
            "育成→支配下": {"番号": 3, "題": "育成 → 支配下", "行": cls["育成→支配下"],
                           "説明": f"総合{D2C_OVERALL}以上は「即昇格」。予測最大{D2C_EARLY_PMAX}以上かつ総合{D2C_EARLY_OVERALL}以上は「先行昇格」。"},
            "満了": {"番号": 5, "題": "育成契約満了の選手", "行": cls["満了"],
                     "説明": "今オフに育成契約が満了する選手。昇格の条件を満たせば「支配下」、戦力外の人数に入れば「自由契約」、それ以外は「育成再契約」。"},
        },
        "戦力外": {
            "支配下": cls["候補"]["支配下"], "育成": cls["候補"]["育成"], "例外": cls["例外"],
            "次点の人数": RELEASE_NEXT_SHOW, "見込みの総合": RELEASE_SAFE_PMAX,
            "説明": (f"ドラフト後に支配下{TARGET_REGISTERED_AFTER_DRAFT}人・育成{TARGET_DEVELOPMENT_AFTER_DRAFT}人になる人数だけ、候補の上から戦力外にします。"
                     f"候補は予測最大{RELEASE_SAFE_PMAX}未満の選手だけ（総合{RELEASE_SAFE_PMAX}以上の見込みがある選手は除外）。優先順は {tier_text}（予測最大{RELEASE_SAFE_PMAX}未満）。"
                     "同じ段階の中では予測最大の低い順です。"),
        },
        "ドラフト": plan_draft,
        "注意": ("予測最大は「今後の見込み」で、設定ピーク年齢を過ぎた選手は過去の最高値を含めません（成長予測タブと同じ値です）。"
                 f"在籍選手の予測は±3〜4程度、ドラフト候補は±{int(round(pm[3]))}程度の誤差があります。"
                 f"予測最大が{RELEASE_SAFE_PMAX - RELEASE_BORDER}〜{RELEASE_SAFE_PMAX - 1}の候補には「境界」の印を付けています（誤差で候補から外れることがあります）。"
                 "新人（特に能力の低い選手）は誤差が大きく、三軍に入れると予測より上に伸びやすい傾向があります。"),
    }
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
        "枠の説明": {"1位候補": "予測最大の高い順。興味を持つ球団が多いほど抽選になりやすい",
                     "狙い目": f"興味を持つ球団が{DRAFT_SLEEPER_INTEREST}以下で予測最大が高い順（2位以降で取れる見込み）",
                     "育成候補": f"スカウト順位{DRAFT_DEV_RANK}位以下だが予測最大{DRAFT_DEV_PMAX}以上"},
        "候補": draft_all["候補"] if scheduled else [],
        "注意": (f"予測最大は1年目開幕時の総合（今の総合＋{DRAFT_CAMP_BONUS}）から予測した参考値で、平均±{pm[3]}程度の誤差があります。"
                 "能力の低い候補ほど誤差が大きく、三軍に入れると予測より上に伸びやすい傾向があります。二刀流の候補は投手・野手の高い方を表示しています。"),
    }
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(json.dumps(dj, ensure_ascii=False, separators=(",", ": ")), encoding="utf-8")

    mv = hc["移動後"]
    log(f"  編成提案: 支→育 {hc['内訳']['支配下→育成']}人、育→支 {hc['内訳']['育成→支配下']}人、契約満了 {hc['内訳']['満了']}人、"
        f"戦力外候補 支配下{len(cls['候補']['支配下'])}人・育成{len(cls['候補']['育成'])}人、ドラフト候補(将来性A) {len(plan_draft['候補'])}人")
    log(f"  人数: 現在 支配下{hc['現在']['支配下']}・育成{hc['現在']['育成']} → 入れ替え後 支配下{mv['支配下']}・育成{mv['育成']}"
        f"（ドラフト後の目標 支配下{TARGET_REGISTERED_AFTER_DRAFT}・育成{TARGET_DEVELOPMENT_AFTER_DRAFT}。戦力外の人数は指名人数で決まる）")
    if plan_draft.get("推奨", {}).get("文"):
        log("  " + plan_draft["推奨"]["文"])
    if scheduled:
        log(f"  ドラフト候補({draft_all['ドラフト年']}年・高卒): {len(draft_all['候補'])}人、1位候補 {len(frames['1位候補'])}・狙い目 {len(frames['狙い目'])}・育成候補 {len(frames['育成候補'])}")
    else:
        log(f"  ドラフト候補: 今は表示しない時期です（段階 {draft_all['段階']}）")
    return out, dj
