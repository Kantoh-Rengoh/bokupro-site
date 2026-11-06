#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roster_plan.py — オフの編成提案（枠整理・ドラフト候補）を作る。

build.py から呼ばれ、docs/data/roster_plan.json を書き出す。
しきい値はこのファイルの冒頭「設定値」にまとめてあるので、後から変えられる。

一覧（上にあるものが優先。1人の選手は1つの一覧にしか出ない）:
  1. 支配下 → 育成
  2. 支配下 → 自由契約
  3. 育成 → 支配下
  4. 育成 → 自由契約
  5. 育成契約満了の選手（支配下／育成再契約／自由契約）※満了の選手はここだけに出す
  6. ドラフト候補（中卒・高卒で将来性Aのみ）
"""
import json
import numpy as np

# ======================================================================
# 設定値（ここを変えると判定が変わる）
# ======================================================================
LIMIT_REGISTERED = 70          # 支配下の上限
LIMIT_DEVELOPMENT = 80         # 育成の上限
TARGET_DEVELOPMENT_PRE_DRAFT = 70  # ドラフト前の育成の目標（この人数以下）
THIRD_SQUAD_BASE = 70          # 三軍の上限 = 合計 − この値

# 1. 支配下 → 育成
C2D_YEARS_PRO = 2              # プロ n 年目の支配下選手が対象
C2D_KEEP_ROUND = 1             # 例外：ドラフトこの順位で…
C2D_KEEP_OVERALL = 80          # …総合がこれ以上で…
C2D_KEEP_AGE = 20              # …この年齢以下なら「残留（例外）」
RELEASE_PMAX = 70              # 予測最大がこれ以下なら育成にせず自由契約へ（2,4,5番でも使う）

# 2. 支配下 → 自由契約
C2F_AGE = 25                   # この年齢以上で
C2F_UPSIDE = 2                 # 伸びしろがこれ以下の選手のうち
C2F_OVERALL_RELEASE = 82       # 総合がこれ未満 → 推奨
C2F_DECLINE_OVERALL = 85       # 下降期で総合がこれ以下 → 推奨
C2F_DECLINE2_OVERALL = 85      # 開幕時の総合が2年連続で低下し、総合がこれ以下 → 推奨（主力級を誤って出さないための上限）
C2F_OVERALL_REVIEW_MAX = 84    # それ以外で総合が 82〜この値 → 検討

# 3. 育成 → 支配下
D2C_OVERALL = 82               # 総合がこれ以上 → 即昇格
D2C_EARLY_PMAX = 90            # 予測最大がこれ以上かつ…
D2C_EARLY_OVERALL = 75         # …総合がこれ以上 → 先行昇格

# 4. 育成 → 自由契約（予測最大 RELEASE_PMAX 以下）。例外は ID で指定する
D2F_KEEP_IDS = {
    "21097BE8-2C7A-465D-9C22-B8C30C15D4A9": "戸池",   # 残留（検証中）
}

# 5. 育成契約満了
EXP_AGE = 24                   # この年齢以上で
EXP_UPSIDE = 2                 # 伸びしろがこれ以下かつ
EXP_PMAX = 80                  # 予測最大がこれ未満 → 自由契約（予測最大 RELEASE_PMAX 以下も自由契約）

# 6. ドラフト候補
DRAFT_BACKGROUNDS = ("中卒", "高卒")
DRAFT_GRADES = ("A",)
DRAFT_CAMP_BONUS = 2           # 候補の1年目開幕時の総合 = 今の総合 + これ（三軍キャンプ分）
DRAFT_FEW_FIRST = 1            # 「1位候補にしている球団が少ない」= この数以下
PROSPECT_TRAIN_MIN_AGE = 31    # 候補の予測モデルに使う在籍選手の年齢（これ以上）

GRADE_NUM = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
ROLE_SHORT = {"投手": "投", "捕手": "捕", "内野手": "内", "外野手": "外"}


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
    """B は build モジュール。戻り値: (imputer, model, 平均誤差)"""
    from sklearn.model_selection import GroupKFold
    X, y, grp = [], [], []
    for p in train_players:
        hs = B.hist_sorted(p)
        if len(hs) < 2:
            continue
        a0 = _first_age(p, hs, B.player_ages)
        if a0 is None:
            continue
        g = p.get("growth") or {}
        dr = p.get("draftRecord") or {}
        ovs = [float(h["overall100"]) for h in hs]
        X.append(prospect_features(ovs[0], a0, dr.get("potentialGrade"), dr.get("attentionGrade"), p.get("role") == "投手",
                                   p.get("developmentPotential"), g.get("riseRate"), g.get("peakAge"), p.get("growthVolatility")))
        y.append(max(ovs)); grp.append(p.get("id"))
    X = np.array(X, float); y = np.array(y, float); grp = np.array(grp)
    imp = B.Imputer(X)
    Xi = imp(X)
    errs = []
    for tr, te in GroupKFold(n_splits=5).split(Xi, y, grp):
        m = B.make_gbr().fit(Xi[tr], y[tr])
        errs.append(float(np.mean(np.abs(m.predict(Xi[te]) - y[te]))))
    mae = float(np.mean(errs))
    log(f"  ドラフト候補の予測: 選手単位の交差検証で平均誤差 {mae:.2f}（{len(y)} 人）")
    return imp, B.make_gbr().fit(Xi, y), round(mae, 2)


# ======================================================================
# 在籍選手の判定
# ======================================================================
def _two_year_decline(hs):
    """開幕時の総合が2年連続で下がった（直近3回の開幕時の値が 右肩下がり）"""
    vals = [float(h["overall100"]) for h in hs]
    return len(vals) >= 3 and vals[-1] < vals[-2] < vals[-3]


def _row_base(r, p):
    return {
        "id": r["id"], "名前": r["名前"], "背番号": r["背番号"], "年齢": r["年齢"],
        "ポジ": ROLE_SHORT.get(r["役割"], ""), "役割": r["役割"], "所属": r["所属"],
        "総合": r["現在"], "予測最大": r["_fut"], "伸びしろ": max(0, r["_fut"] - r["現在"]),
        "状態": r["状態"], "外国人": bool(p.get("foreign")), "年目": p.get("yearsPro"),
        "ドラフト順位": r["ドラフト順位"], "将来性": r["将来性"],
    }


def _sort_rows(rows):
    rows.sort(key=lambda x: (x["年齢"], -x["予測最大"], -x["総合"]))
    return rows


def classify_players(rows, expiry_ids, B):
    """rows は build.compute_players の結果（_fut, _p 付き）。戻り値: 一覧5つ（dict の list）"""
    c2d, c2f, d2c, d2f, exp = [], [], [], [], []
    for r in rows:
        p = r["_p"]
        b = _row_base(r, p)
        ov, pmax, up, age = b["総合"], b["予測最大"], b["伸びしろ"], b["年齢"]
        dev = bool(p.get("developmentContract"))
        dr = p.get("draftRecord") or {}
        promote = None
        if ov >= D2C_OVERALL:
            promote = "即昇格"
        elif pmax >= D2C_EARLY_PMAX and ov >= D2C_EARLY_OVERALL:
            promote = "先行昇格"

        # 5. 契約満了の選手はこの一覧だけ
        if r["id"] in expiry_ids:
            if promote:
                b["判定"], b["理由"] = "支配下", promote + "の条件を満たす"
            elif pmax <= RELEASE_PMAX:
                b["判定"], b["理由"] = "自由契約", f"予測最大{RELEASE_PMAX}以下"
            elif age >= EXP_AGE and up <= EXP_UPSIDE and pmax < EXP_PMAX:
                b["判定"], b["理由"] = "自由契約", f"{EXP_AGE}歳以上・伸びしろ{EXP_UPSIDE}以下・予測最大{EXP_PMAX}未満"
            else:
                b["判定"], b["理由"] = "育成再契約", "まだ伸びしろあり"
            exp.append(b)
            continue

        if not dev:
            # 1. 支配下 → 育成
            if not b["外国人"] and p.get("yearsPro") == C2D_YEARS_PRO:
                if dr.get("round") == C2D_KEEP_ROUND and ov >= C2D_KEEP_OVERALL and age <= C2D_KEEP_AGE:
                    b["判定"], b["理由"] = "残留（例外）", f"ドラフト{C2D_KEEP_ROUND}位・総合{C2D_KEEP_OVERALL}以上・{C2D_KEEP_AGE}歳以下"
                    c2d.append(b)
                elif pmax <= RELEASE_PMAX:
                    b["判定"], b["理由"] = "推奨", f"{C2D_YEARS_PRO}年目・予測最大{RELEASE_PMAX}以下"
                    c2f.append(b)
                else:
                    b["判定"], b["理由"] = "育成へ", f"{C2D_YEARS_PRO}年目"
                    c2d.append(b)
                continue
            # 2. 支配下 → 自由契約
            if age >= C2F_AGE and up <= C2F_UPSIDE:
                hs = B.hist_sorted(p)
                reasons = []
                if ov < C2F_OVERALL_RELEASE:
                    reasons.append(f"総合{C2F_OVERALL_RELEASE}未満")
                if _two_year_decline(hs) and ov <= C2F_DECLINE2_OVERALL:
                    reasons.append("2年連続で総合が低下")
                if b["状態"] == "下降期" and ov <= C2F_DECLINE_OVERALL:
                    reasons.append(f"下降期で総合{C2F_DECLINE_OVERALL}以下")
                if reasons:
                    b["判定"], b["理由"] = "推奨", "・".join(reasons)
                    c2f.append(b)
                elif C2F_OVERALL_RELEASE <= ov <= C2F_OVERALL_REVIEW_MAX:
                    b["判定"], b["理由"] = "検討", f"総合{C2F_OVERALL_RELEASE}〜{C2F_OVERALL_REVIEW_MAX}・伸びしろ{C2F_UPSIDE}以下"
                    c2f.append(b)
            continue

        # 3. 育成 → 支配下
        if promote:
            b["判定"] = promote
            b["理由"] = f"総合{D2C_OVERALL}以上" if promote == "即昇格" else f"予測最大{D2C_EARLY_PMAX}以上・総合{D2C_EARLY_OVERALL}以上"
            d2c.append(b)
            continue
        # 4. 育成 → 自由契約（例外リストの選手は、しきい値に関係なく「残留（検証中）」として見せる）
        if r["id"] in D2F_KEEP_IDS:
            b["判定"], b["理由"] = "残留（検証中）", "例外リスト" + ("" if pmax <= RELEASE_PMAX else f"（予測最大は{RELEASE_PMAX}より上）")
            d2f.append(b)
        elif pmax <= RELEASE_PMAX:
            b["判定"], b["理由"] = "自由契約", f"予測最大{RELEASE_PMAX}以下"
            d2f.append(b)
    for lst in (c2f, d2f, exp):
        for b in lst:
            # 予測最大のしきい値ぎりぎり（±1）で判定が決まった選手には印を付ける（予測の誤差で入れ替わりうる）
            b["境界"] = f"予測最大{RELEASE_PMAX}以下" in b["理由"] and abs(b["予測最大"] - RELEASE_PMAX) <= 1
    return [_sort_rows(x) for x in (c2d, c2f, d2c, d2f, exp)]


# ======================================================================
# ドラフト候補
# ======================================================================
def draft_candidates(p0, own_team, ov_models, prospect_model, B):
    d = p0.get("draft") or {}
    prospects = d.get("prospects") or []
    board = d.get("interestBoard") or {}
    if isinstance(board, dict):
        board = {t: list(v or []) for t, v in board.items() if t != own_team}
    else:
        board = {}
    declared_team = d.get("declaredFirstRoundPickTeam")
    declared_id = d.get("declaredFirstRoundProspectID")
    interest, first = {}, {}
    for t, ids in board.items():
        for i, pid in enumerate(ids):
            interest[pid] = interest.get(pid, 0) + 1
            if i == 0:
                first[pid] = first.get(pid, 0) + 1
    imp, model, _ = prospect_model
    name_count = {}
    for q in prospects:
        name_count[q.get("surname")] = name_count.get(q.get("surname"), 0) + 1

    # 全候補の予測（同姓の注記に使う）
    pred = {}
    for q in prospects:
        role = q.get("role")
        vec = B.ability_vec(q)
        if role not in ov_models or vec is None:
            continue
        cur = ov_models[role].predict(vec)
        g = q.get("growth") or {}
        x = imp([prospect_features(cur + DRAFT_CAMP_BONUS, int(q.get("age") or 18) + 1, q.get("assignedDevelopmentGrade"),
                                    q.get("assignedAttentionGrade"), role == "投手", q.get("developmentPotential"),
                                    g.get("riseRate"), g.get("peakAge"), q.get("growthVolatility"))])
        pred[q["id"]] = (cur, max(int(round(float(model.predict(x)[0]))), cur))

    rows = []
    for q in prospects:
        if q.get("background") not in DRAFT_BACKGROUNDS or q.get("assignedDevelopmentGrade") not in DRAFT_GRADES:
            continue
        if q["id"] not in pred:
            continue
        cur, pmax = pred[q["id"]]
        same = [f"{o.get('background')}・将来性{o.get('assignedDevelopmentGrade')}・予測{pred[o['id']][1]}" if o["id"] in pred else "予測なし"
                for o in prospects if o.get("surname") == q.get("surname") and o["id"] != q["id"]]
        rows.append({
            "id": q["id"], "名前": q.get("surname"), "年齢": q.get("age"), "ポジ": ROLE_SHORT.get(q.get("role"), ""), "役割": q.get("role"),
            "経歴": q.get("background"), "出身": q.get("origin"), "総合": cur, "予測最大": pmax,
            "将来性": q.get("assignedDevelopmentGrade"), "注目度": q.get("assignedAttentionGrade"),
            "関心数": interest.get(q["id"], 0), "1位候補数": first.get(q["id"], 0),
            "同姓": "／".join(same), "公言": declared_team if q["id"] == declared_id else "",
            "対象外": pmax <= RELEASE_PMAX, "推奨": "",
            "タイプ": B.ARCHETYPE.get((q.get("growth") or {}).get("archetype"), ""),
            "メモ": q.get("note") or "",
        })
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
    declared = None
    if declared_team and declared_id:
        name = next((q.get("surname") for q in prospects if q["id"] == declared_id), None)
        declared = {"球団": declared_team, "選手": name}
    return {
        "候補": rows, "候補数": len(prospects), "推奨": rec, "公言": declared,
        "他球団数": len(board), "ドラフト年": d.get("year"), "段階": d.get("stage"),
    }


# ======================================================================
# 人数の見込み
# ======================================================================
def headcount(rows, lists):
    c2d, c2f, d2c, d2f, exp = lists
    reg_now = sum(1 for r in rows if not r["_p"].get("developmentContract"))
    dev_now = len(rows) - reg_now
    n_c2d = sum(1 for x in c2d if x["判定"] == "育成へ")
    n_c2f = sum(1 for x in c2f if x["判定"] == "推奨")
    n_c2f_rev = sum(1 for x in c2f if x["判定"] == "検討")
    n_d2c = sum(1 for x in d2c if x["判定"] in ("即昇格", "先行昇格"))
    n_d2f = sum(1 for x in d2f if x["判定"] == "自由契約")
    e_reg = sum(1 for x in exp if x["判定"] == "支配下")
    e_rel = sum(1 for x in exp if x["判定"] == "自由契約")
    e_re = sum(1 for x in exp if x["判定"] == "育成再契約")
    reg_after = reg_now - n_c2d - n_c2f + n_d2c + e_reg
    dev_after = dev_now + n_c2d - n_d2c - n_d2f - e_reg - e_rel
    return {
        "現在": {"支配下": reg_now, "育成": dev_now, "合計": reg_now + dev_now, "三軍上限": reg_now + dev_now - THIRD_SQUAD_BASE},
        "提案後": {"支配下": reg_after, "育成": dev_after, "合計": reg_after + dev_after, "三軍上限": reg_after + dev_after - THIRD_SQUAD_BASE},
        "上限": {"支配下": LIMIT_REGISTERED, "育成": LIMIT_DEVELOPMENT, "育成目標": TARGET_DEVELOPMENT_PRE_DRAFT, "三軍の基準": THIRD_SQUAD_BASE},
        "内訳": {"支配下→育成": n_c2d, "支配下→自由契約": n_c2f, "支配下→自由契約（検討）": n_c2f_rev, "育成→支配下": n_d2c,
                 "育成→自由契約": n_d2f, "満了→支配下": e_reg, "満了→育成再契約": e_re, "満了→自由契約": e_rel},
    }


# ======================================================================
# 本体
# ======================================================================
def build_plan(B, p0, own, rows, retired, ov_models, game_dt, out_path):
    """B: build モジュール。rows: compute_players の結果（_fut と _p を含む）"""
    team = p0.get("teamName") or ""
    expiry_ids = set(p0.get("developmentExpiryPending") or [])
    lists = classify_players(rows, expiry_ids, B)
    train = list(retired) + [p for p in own if int(p.get("age") or 0) >= PROSPECT_TRAIN_MIN_AGE]
    pm = fit_prospect_model(train, B)
    draft = draft_candidates(p0, team, ov_models, pm, B)
    draft["予測誤差"] = pm[2]
    titles = [
        ("支配下 → 育成", f"支配下・外国人以外でプロ{C2D_YEARS_PRO}年目の選手。ドラフト{C2D_KEEP_ROUND}位で総合{C2D_KEEP_OVERALL}以上・{C2D_KEEP_AGE}歳以下は残留（例外）。予測最大{RELEASE_PMAX}以下は自由契約の一覧へ。"),
        ("支配下 → 自由契約", f"{C2F_AGE}歳以上で伸びしろ{C2F_UPSIDE}以下のうち、総合{C2F_OVERALL_RELEASE}未満／開幕時の総合が2年連続で低下（総合{C2F_DECLINE2_OVERALL}以下）／下降期で総合{C2F_DECLINE_OVERALL}以下なら「推奨」、それ以外で総合{C2F_OVERALL_RELEASE}〜{C2F_OVERALL_REVIEW_MAX}なら「検討」。外国人は印を付けています。"),
        ("育成 → 支配下", f"総合{D2C_OVERALL}以上は「即昇格」。予測最大{D2C_EARLY_PMAX}以上かつ総合{D2C_EARLY_OVERALL}以上は「先行昇格」。"),
        ("育成 → 自由契約", f"予測最大{RELEASE_PMAX}以下の育成選手。例外リストの選手は「残留（検証中）」。"),
        ("育成契約満了の選手", f"今オフに育成契約が満了する選手。昇格の条件を満たせば「支配下」、予測最大{RELEASE_PMAX}以下または{EXP_AGE}歳以上で伸びしろ{EXP_UPSIDE}以下かつ予測最大{EXP_PMAX}未満なら「自由契約」、それ以外は「育成再契約」。"),
    ]
    out = {
        "球団名": team,
        "ゲーム内日付": f"{game_dt.year}年{game_dt.month}月{game_dt.day}日",
        "フェーズ": p0.get("phase") or "",
        "シーズン年": p0.get("seasonYear"),
        "人数": headcount(rows, lists),
        "一覧": [{"番号": i + 1, "題": t, "説明": s, "行": rows_} for i, ((t, s), rows_) in enumerate(zip(titles, lists))],
        "ドラフト": draft,
        "注意": ("予測最大は「今後の見込み」で、設定ピーク年齢を過ぎた選手は過去の最高値を含めません（成長予測タブと同じ値です）。"
                 f"在籍選手の予測は±3〜4程度、ドラフト候補は±{int(round(pm[2]))}程度の誤差があります。"
                 "新人（特に能力の低い選手）は誤差が大きく、三軍に入れると予測より上に伸びやすい傾向があります。"),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ": ")), encoding="utf-8")
    c2d, c2f, d2c, d2f, exp = lists
    hc = out["人数"]
    log(f"  編成提案: 支→育 {len(c2d)}人、支→自 {len(c2f)}人、育→支 {len(d2c)}人、育→自 {len(d2f)}人、契約満了 {len(exp)}人、ドラフト候補 {len(draft['候補'])}人")
    log(f"  人数: 現在 支配下{hc['現在']['支配下']}・育成{hc['現在']['育成']} → 提案後 支配下{hc['提案後']['支配下']}・育成{hc['提案後']['育成']}")
    if draft["推奨"].get("文"):
        log("  " + draft["推奨"]["文"])
    return out
