#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — 「ぼくのプロ野球」のセーブデータ（.tfosave）から、サイト用の
docs/players.json と docs/meta.json（と docs/data/roster_plan.json）を作る。

使い方:  python scripts/build.py
  saves/ の中で「ゲーム内の日付」が一番新しい .tfosave を自動で選びます。
  古いセーブデータは saves/archive/ に移し、直近の数個だけ残します。
  docs/qa.json には触りません。

処理の流れ:
  1. セーブデータを展開（LZFSE）して 4 つの JSON を取り出す
  2. 能力6項目 → 総合 の変換を、役割ごとに学習して「セーブ時点の総合」を求める
  3. 引退選手の経歴から「生涯最高の総合」と「到達年齢」を予測するモデルを学習する
  4. 自チーム全員の予測・状態・前年比・三軍推奨・練習メニューを計算する
  5. docs/players.json / docs/meta.json を書き出す
  6. オフの編成提案（roster_plan.py）を docs/data/roster_plan.json に、ドラフト候補を docs/draft.json に書き出す
  ※ 二刀流の選手（twoWay 欄あり）は投手側・野手側を別々に計算し、予測最大が高い方を見出しに使う
"""
import sys, re, json, math, shutil, datetime, warnings
from pathlib import Path

try:
    import numpy as np
    import liblzfse  # noqa: F401
    import scipy  # noqa: F401
    import sklearn  # noqa: F401
except ImportError as _e:
    print(f"エラー: 必要な部品が入っていません（{_e}）。requirements.txt の内容をインストールしてください。")
    sys.exit(1)

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SAVES = ROOT / "saves"
ARCHIVE = SAVES / "archive"
DOCS = ROOT / "docs"
ARCHIVE_KEEP = 2          # archive に残す古いセーブデータの数
THIRD_SQUAD_RESERVE = 70  # 三軍推奨の人数 = 全選手数 − この値

AB6 = ["contact", "power", "speed", "fielding", "arm", "stamina"]
# 画面に出す5項目（表示名, 元の項目）
AB_BATTER = [("巧打", "contact"), ("長打", "power"), ("走力", "speed"), ("守備", "fielding"), ("精神", "arm")]
AB_PITCHER = [("制球", "contact"), ("変化", "power"), ("体力", "speed"), ("球威", "stamina"), ("精神", "arm")]
AB_KEYS = ["巧打・制球", "長打・変化", "走力・体力", "守備・球威", "精神"]
MENU_BATTER = {"contact": "ミート練習", "power": "長打力強化", "speed": "走塁強化", "fielding": "守備強化", "arm": "実戦判断練習"}
MENU_PITCHER = {"contact": "制球強化", "power": "変化球強化", "speed": "持久力強化", "stamina": "球威強化", "arm": "実戦判断練習"}
ROLE_CAT = {"投手": "投", "捕手": "捕", "内野手": "内", "外野手": "外"}
POS_CAT = {"投手": "投", "捕手": "捕", "一塁": "内", "二塁": "内", "三塁": "内", "遊撃": "内", "左翼": "外", "中堅": "外", "右翼": "外"}
ARCHETYPE = {"standard": "標準", "lateBloomer": "晩成", "earlyBloomer": "早熟", "durable": "持続", "slowStarter": "遅咲き",
             "meteor": "流星", "secondWind": "再成長", "refined": "熟成", "sustainedPrime": "長期ピーク", "earlyPlateau": "早期頭打ち"}
GRADE_NUM = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
ROOKIE_OFFSET_OK = 3.7     # 新人（キャンプ前）の総合に足す補正：ハズレなし
ROOKIE_OFFSET_MISS = -0.6  # 同、ハズレあり


def die(msg):
    print("エラー: " + msg)
    sys.exit(1)


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------
# 1. セーブデータの展開
# ----------------------------------------------------------------------
def split_streams(data: bytes):
    start = data.find(b"bvx2")
    if start < 0:
        return []
    ends = [m.start() + 4 for m in re.finditer(re.escape(b"bvx$"), data)]
    bounds = [start] + ends
    return [data[bounds[k]:bounds[k + 1]] for k in range(len(ends))]


def decode_save(path: Path, only_first=False):
    import liblzfse
    data = path.read_bytes()
    streams = split_streams(data)
    if len(streams) < 4 and not only_first:
        die(f"{path.name} はセーブデータの形式が違うようです（展開できる区切りが {len(streams)} 個しかありません）。")
    if not streams:
        die(f"{path.name} はセーブデータの形式が違うようです。")
    out = []
    for i, s in enumerate(streams[: (1 if only_first else 4)]):
        try:
            out.append(json.loads(liblzfse.decompress(s)))
        except Exception as e:
            die(f"{path.name} の {i + 1} 番目の区切りを展開できませんでした（{e}）。ファイルが壊れていないか確認してください。")
    return out


APPLE_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)
JST = datetime.timezone(datetime.timedelta(hours=9))


def game_datetime(seconds):
    """ゲーム内日付（2001年1月1日からの秒数）を日本時間の日時にする"""
    try:
        return (APPLE_EPOCH + datetime.timedelta(seconds=float(seconds))).astimezone(JST)
    except Exception:
        return None


def pick_newest_save():
    """saves/ 内の .tfosave をゲーム内日付で比べ、一番新しいものを返す。古いものは archive へ。"""
    SAVES.mkdir(exist_ok=True)
    ARCHIVE.mkdir(exist_ok=True)
    files = sorted([p for p in SAVES.glob("*.tfosave") if p.is_file()])
    if not files:
        files = sorted(ARCHIVE.glob("*.tfosave"))
        if not files:
            die("saves フォルダに .tfosave ファイルがありません。セーブデータをアップロードしてください。")
    dated = []
    for p in files:
        p0 = decode_save(p, only_first=True)[0]
        dt = game_datetime(p0.get("currentDate", 0))
        dated.append((dt or datetime.datetime.min.replace(tzinfo=JST), p))
        log(f"  {p.name}: ゲーム内日付 {dt.strftime('%Y-%m-%d') if dt else '不明'}")
    dated.sort(key=lambda t: t[0])
    newest_dt, newest = dated[-1]
    # 古いものは archive へ（名前の先頭にゲーム内日付を付けて並び順を保つ）
    for dt, p in dated[:-1]:
        if p.parent == ARCHIVE:
            continue
        target = ARCHIVE / f"{dt.strftime('%Y-%m-%d')}_{p.name}"
        shutil.move(str(p), str(target))
        log(f"  古いセーブデータを退避: {p.name} → archive/{target.name}")
    # archive は新しい方から ARCHIVE_KEEP 個だけ残す
    arch = sorted(ARCHIVE.glob("*.tfosave"), key=lambda p: p.name)
    for p in arch[:-ARCHIVE_KEEP] if len(arch) > ARCHIVE_KEEP else []:
        p.unlink()
        log(f"  古いセーブデータを削除: archive/{p.name}")
    return newest, newest_dt


# ----------------------------------------------------------------------
# 2. 能力 → 総合 の変換（役割ごと）
# ----------------------------------------------------------------------
def ability_vec(d):
    try:
        return [float(d[a]) for a in AB6]
    except Exception:
        return None


def overall_samples(players):
    """役割ごとに (能力6項目, 総合) の組を集める。戻り値: role -> (X, y, groups)"""
    out = {}
    for p in players:
        role = p.get("role")
        if role not in ROLE_CAT:
            continue
        X, y, g = out.setdefault(role, ([], [], []))
        pid = p.get("id")
        recs = list(p.get("abilityHistory") or [])
        for k in ("seasonStartAbility", "seasonEndAbility"):
            if isinstance(p.get(k), dict):
                recs.append(p[k])
        for h in recs:
            v = ability_vec(h)
            ov = h.get("overall100")
            if v is None or ov is None:
                continue
            X.append(v); y.append(float(ov)); g.append(pid)
    return out


class OverallModel:
    def __init__(self, w, iso):
        self.w = w
        self.iso = iso

    def predict(self, vec):
        s = float(np.dot(np.asarray(vec, float), self.w))
        return int(round(float(np.clip(self.iso.predict([s])[0], 1, 100))))


def fit_overall(X, y, label=""):
    from scipy.optimize import minimize
    from sklearn.isotonic import IsotonicRegression
    X = np.asarray(X, float); y = np.asarray(y, float)
    # 最適化は最大 12000 件に間引いて速くする（最終の変換は全件で作る）
    rng = np.random.default_rng(0)
    idx = rng.choice(len(X), size=min(len(X), 12000), replace=False)
    Xs, ys = X[idx], y[idx]

    def loss(w):
        w = np.abs(w)
        if w.sum() == 0:
            return 1e9
        s = Xs @ w
        iso = IsotonicRegression(out_of_bounds="clip").fit(s, ys)
        return float(np.mean(np.abs(iso.predict(s) - ys)))

    w0 = np.ones(len(AB6)) / len(AB6)
    res = minimize(loss, w0, method="Nelder-Mead", options={"maxiter": 800, "xatol": 1e-4, "fatol": 1e-4})
    w = np.abs(res.x); w = w / w.sum()
    iso = IsotonicRegression(out_of_bounds="clip").fit(X @ w, y)
    return OverallModel(w, iso)


def fit_overall_models(all_players):
    samples = overall_samples(all_players)
    models, report = {}, {}
    for role, (X, y, g) in samples.items():
        X = np.asarray(X, float); y = np.asarray(y, float); g = np.asarray(g)
        # 選手単位で 2 割を検証用に分け、未知の選手に対する誤差を測る
        uniq = np.unique(g)
        rng = np.random.default_rng(1)
        test_ids = set(rng.choice(uniq, size=max(1, len(uniq) // 5), replace=False).tolist())
        te = np.array([x in test_ids for x in g])
        m = fit_overall(X[~te], y[~te])
        pred = np.array([m.predict(v) for v in X[te]])
        mae = float(np.mean(np.abs(pred - y[te])))
        within1 = float(np.mean(np.abs(pred - y[te]) <= 1))
        # 本番用は全件で学習し直す
        models[role] = fit_overall(X, y)
        report[role] = {"件数": int(len(y)), "平均誤差": round(mae, 2), "誤差1以内の割合": round(within1, 3),
                        "重み": {a: round(float(wv), 3) for a, wv in zip(AB6, models[role].w)}}
        log(f"  {role}: 学習 {len(y)} 件、未知の選手での平均誤差 {mae:.2f}（誤差1以内 {within1 * 100:.0f}%）")
    for role in ROLE_CAT:
        if role not in models:
            die(f"{role} の総合を学習するデータがありません。")
    return models, report


# ----------------------------------------------------------------------
# 3. 生涯最高の総合・到達年齢の予測モデル
# ----------------------------------------------------------------------
ARCH_LIST = list(ARCHETYPE.keys())


def year_age_map(p):
    m = {}
    for sh in p.get("seasonHistory") or []:
        if isinstance(sh, dict) and "year" in sh and "age" in sh:
            m[int(sh["year"])] = int(sh["age"])
    return m


def hist_sorted(p):
    hs = [h for h in (p.get("abilityHistory") or []) if isinstance(h, dict) and h.get("overall100") is not None and h.get("year") is not None]
    return sorted(hs, key=lambda h: int(h["year"]))


def player_ages(p, hs):
    """abilityHistory の各年の年齢（seasonHistory から。無ければ現在の年齢から逆算）"""
    ya = year_age_map(p)
    ages = []
    last_year = int(hs[-1]["year"]) if hs else None
    for h in hs:
        y = int(h["year"])
        if y in ya:
            ages.append(ya[y])
        elif p.get("age") is not None and last_year is not None:
            ages.append(int(p["age"]) - (last_year - y))
        else:
            ages.append(None)
    return ages


def static_features(p):
    g = p.get("growth") or {}
    dr = p.get("draftRecord") or {}
    arch = g.get("archetype")
    f = [
        GRADE_NUM.get(dr.get("potentialGrade"), 3),
        float(p.get("developmentPotential") if p.get("developmentPotential") is not None else np.nan),
        float(g.get("peakAge") if g.get("peakAge") is not None else np.nan),
        float(g.get("riseRate") if g.get("riseRate") is not None else np.nan),
        float(g.get("declineRate") if g.get("declineRate") is not None else np.nan),
        float(g.get("plateauYears") if g.get("plateauYears") is not None else np.nan),
        float(p.get("growthVolatility") if p.get("growthVolatility") is not None else np.nan),
        1.0 if p.get("role") == "投手" else 0.0,
    ]
    f += [1.0 if arch == a else 0.0 for a in ARCH_LIST]
    return f


FEATURE_NAMES = ["age", "overall", "overall_first", "grade", "devPot", "peakAge", "riseRate", "declineRate", "plateauYears", "volatility", "isPitcher"] + ["arch_" + a for a in ARCH_LIST]


def build_training(players):
    """引退選手（経歴が揃っている）から学習データを作る。
    戻り値: (X, y_max, y_age, y_future, groups), 新人用 (X, y_max, y_age, y_future, groups), 年齢別の平均成長
    y_max は生涯の最高総合、y_future は「その年以降」の最高総合（編成提案の伸びしろに使う）"""
    X, ymax, yage, yfut, grp = [], [], [], [], []
    Xr, ymax_r, yage_r, grp_r = [], [], [], []
    growth_by_age = {}
    for p in players:
        hs = hist_sorted(p)
        if len(hs) < 2:
            continue
        ages = player_ages(p, hs)
        if any(a is None for a in ages):
            continue
        ovs = [float(h["overall100"]) for h in hs]
        mx = max(ovs)
        reach = ages[ovs.index(mx)]
        sf = static_features(p)
        pid = p.get("id")
        for i, (h, a, o) in enumerate(zip(hs, ages, ovs)):
            X.append([a, o, ovs[0]] + sf); ymax.append(mx); yage.append(reach); yfut.append(max(ovs[i:])); grp.append(pid)
            if i + 1 < len(hs) and ages[i + 1] == a + 1:
                growth_by_age.setdefault(a, []).append(ovs[i + 1] - o)
        Xr.append([ages[0], ovs[0]] + sf); ymax_r.append(mx); yage_r.append(reach); grp_r.append(pid)
    gba = {a: float(np.mean(v)) for a, v in growth_by_age.items() if len(v) >= 5}
    return (np.array(X, float), np.array(ymax, float), np.array(yage, float), np.array(yfut, float), np.array(grp)), \
           (np.array(Xr, float), np.array(ymax_r, float), np.array(yage_r, float), None, np.array(grp_r)), gba


def make_gbr():
    from sklearn.ensemble import GradientBoostingRegressor
    return GradientBoostingRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, random_state=0)


class Imputer:
    def __init__(self, X):
        self.med = np.nanmedian(X, axis=0)
        self.med = np.where(np.isnan(self.med), 0, self.med)

    def __call__(self, X):
        X = np.array(X, float)
        mask = np.isnan(X)
        if mask.any():
            X[mask] = np.take(self.med, np.where(mask)[1])
        return X


def fit_predictors(train, label):
    """戻り値: (imputer, 最高総合モデル, 到達年齢モデル, 誤差の報告, 今後の最高モデル or None)"""
    from sklearn.model_selection import GroupKFold
    X, ymax, yage, yfut, grp = train
    imp = Imputer(X)
    Xi = imp(X)
    rep = {}
    targets = [("最高総合", ymax), ("到達年齢", yage)] + ([("今後の最高", yfut)] if yfut is not None else [])
    for name, y in targets:
        errs = []
        for tr, te in GroupKFold(n_splits=5).split(Xi, y, grp):
            m = make_gbr().fit(Xi[tr], y[tr])
            errs.append(np.mean(np.abs(m.predict(Xi[te]) - y[te])))
        rep[name] = round(float(np.mean(errs)), 2)
        log(f"  {label}{name}: 選手単位の交差検証で平均誤差 {np.mean(errs):.2f}（{len(y)} 件）")
    m_max = make_gbr().fit(Xi, ymax)
    m_age = make_gbr().fit(Xi, yage)
    m_fut = make_gbr().fit(Xi, yfut) if yfut is not None else None
    return imp, m_max, m_age, rep, m_fut


# ----------------------------------------------------------------------
# 4. 自チーム選手の計算
# ----------------------------------------------------------------------
def is_external(p, team_name):
    dr = p.get("draftRecord")
    if not isinstance(dr, dict) or not dr:
        return True
    if p.get("foreign"):
        return True
    return dr.get("team") != team_name


def positions(p, role):
    pr = p.get("positionRatings") or []
    pairs = []
    for i in range(0, len(pr) - 1, 2):
        try:
            pairs.append((str(pr[i]), int(pr[i + 1])))
        except Exception:
            pass
    pairs.sort(key=lambda t: -t[1])
    main = ROLE_CAT.get(role, "")
    subs = []
    for nm, _ in pairs:
        c = POS_CAT.get(nm)
        if c and c != main and c not in subs:
            subs.append(c)
    order = {"投": 0, "捕": 1, "内": 2, "外": 3}
    subs.sort(key=lambda c: order.get(c, 9))
    return main, "・".join(subs), "／".join(f"{nm} {v}" for nm, v in pairs)


def error_margin(is_rookie, overall, age):
    if is_rookie:
        return 9 if overall <= 25 else 7 if overall <= 35 else 4 if overall <= 50 else 3
    return 4 if age <= 21 else 3


def status_of(is_rookie, age, reach_age, peak_age):
    if is_rookie:
        return "新人"
    if age > reach_age + 1 or (peak_age is not None and age > peak_age + 1):
        return "下降期"
    if age >= reach_age - 1:
        return "ピーク"
    if reach_age - age <= 3:
        return "成熟期"
    return "伸び盛り"


def predict_side(ab, role, age, hs, ages, sf, miss, ov_models, pred, pred_rookie, gba):
    """1つの役割分の計算（二刀流は投手側・野手側で2回呼ぶ）。
    ab: 能力6項目の dict、hs: その役割の abilityHistory（年順）、ages: hs 各年の年齢。
    戻り値: dict(current, pmax, reach, reach_status, is_rookie, hist_max, 誤差, 伸びしろ, 前年比, 状態, 能力5項目(+前年比), 推奨メニュー)"""
    imp, m_max, m_age, _, m_fut = pred
    imp_r, m_max_r, m_age_r, _, _ = pred_rookie
    vec = [float(ab[a]) for a in AB6]
    current = ov_models[role].predict(vec)
    is_rookie = len(hs) == 0
    peak_age = sf_peak(sf)
    if is_rookie:
        o_in = current + (ROOKIE_OFFSET_MISS if miss else ROOKIE_OFFSET_OK)
        x = imp_r([[age, o_in] + sf])
        pmax = max(int(round(float(m_max_r.predict(x)[0]))), current)
        page = float(m_age_r.predict(x)[0])
        reach = max(int(round(page)), age) if pmax > current else age
        reach_status = reach
        hist_max = current
    else:
        a_last = ages[-1] if ages[-1] is not None else age
        o_last = float(hs[-1]["overall100"])
        x = imp([[a_last, o_last, float(hs[0]["overall100"])] + sf])
        pmax = float(m_max.predict(x)[0])
        page = float(m_age.predict(x)[0])
        excess = (current - o_last) - gba.get(a_last, 0.0)
        pmax += 0.5 * excess
        hist_vals = [float(h["overall100"]) for h in hs]
        hist_max = max(hist_vals + [current])
        if peak_age is not None and age > int(peak_age):
            # 設定ピーク年齢を過ぎた選手：予測最大は「今後の最高」モデル（過去の最高値を含めない）。
            # 状態の判定だけは、実際に最高だった年齢（過去）を使う
            reach_status = ages[hist_vals.index(max(hist_vals))] if max(hist_vals) >= current else age
            pmax = max(int(round(float(m_fut.predict(x)[0]) + 0.5 * excess)), current)
            reach = max(int(round(page)), age) if pmax > current else age
        else:
            pmax = max(int(round(pmax)), current)
            reach = max(int(round(page)), age) if pmax > current else age
            reach_status = reach
    out = {
        "current": current, "pmax": int(pmax), "reach": reach, "reach_status": reach_status, "is_rookie": is_rookie,
        "hist_max": hist_max, "誤差": error_margin(is_rookie, current, age), "伸びしろ": max(0, int(pmax) - current),
        "前年比": None if is_rookie else int(current - int(hs[-1]["overall100"])),
        "状態": status_of(is_rookie, age, reach_status, peak_age),
    }
    ab_map = AB_PITCHER if role == "投手" else AB_BATTER
    for key, (lab, a) in zip(AB_KEYS, ab_map):
        val = int(ab[a])
        out[key] = val
        out[key + "_前年比"] = None if is_rookie or hs[-1].get(a) is None else int(val - int(hs[-1][a]))
    # 練習メニュー：役割の総合への重み × (100 − 能力値) が最大の能力
    w = ov_models[role].w
    menu_map = MENU_PITCHER if role == "投手" else MENU_BATTER
    best, best_lab, best_val, best_score = None, None, None, -1
    for lab, a in ab_map:
        score = float(w[AB6.index(a)]) * (100 - int(ab[a]))
        if score > best_score:
            best, best_lab, best_val, best_score = menu_map[a], lab, int(ab[a]), score
    out["推奨メニュー"] = f"{best}（{best_lab} {best_val}）" if best else ""
    return out


def sf_peak(sf):
    """static_features の並びから設定ピーク年齢を取り出す（NaN なら None）"""
    v = sf[2]
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else int(v)


def two_way_side(p):
    """二刀流の野手側の情報 (役割, 能力6項目, 疑似選手データ)。二刀流でなければ None。
    twoWay: fielderRole（野手としての位置）、contact/power/speed/fielding、battingGrowth、abilityHistory など"""
    tw = p.get("twoWay")
    if not isinstance(tw, dict):
        return None
    role = tw.get("fielderRole")
    if role not in ROLE_CAT or role == "投手":
        return None
    ab = {}
    for a in ("contact", "power", "speed", "fielding"):
        if tw.get(a) is None:
            return None
        ab[a] = float(tw[a])
    ab["arm"] = float(p.get("arm") or 0)          # 精神は投手・野手で共通
    ab["stamina"] = float(p.get("stamina") or 0)  # 野手の総合にはほぼ効かない
    pseudo = {"growth": tw.get("battingGrowth") or p.get("growth") or {}, "developmentPotential": p.get("developmentPotential"),
              "growthVolatility": p.get("growthVolatility"), "role": role, "draftRecord": p.get("draftRecord") or {},
              "abilityHistory": tw.get("abilityHistory") or [], "seasonHistory": p.get("seasonHistory") or [], "age": p.get("age")}
    return role, ab, pseudo


def side_public(side, role, g):
    """二刀流の詳細表示用に、1つの役割分の値をまとめる"""
    d = {"役割": role, "ポジ": ROLE_CAT.get(role, ""), "総合": side["current"], "予測最大": side["pmax"], "到達年齢": side["reach"],
         "伸びしろ": side["伸びしろ"], "誤差": side["誤差"], "前年比": side["前年比"], "状態": side["状態"],
         "タイプ": ARCHETYPE.get(g.get("archetype"), str(g.get("archetype") or "不明")), "設定ピーク年齢": g.get("peakAge"),
         "推奨メニュー": side["推奨メニュー"], "参考値": True}
    for key in AB_KEYS:
        d[key] = side[key]
        d[key + "_前年比"] = side[key + "_前年比"]
    return d


def compute_players(own, team_name, ov_models, pred, pred_rookie, gba):
    rows = []
    for p in own:
        role = p.get("role")
        if role not in ROLE_CAT:
            log(f"  注意: {p.get('surname')} の役割 '{role}' が不明なので飛ばします")
            continue
        vec = ability_vec(p)
        if vec is None:
            log(f"  注意: {p.get('surname')} の能力値が欠けているので飛ばします")
            continue
        age = int(p.get("age") or 0)
        g = p.get("growth") or {}
        dr = p.get("draftRecord") or {}
        miss = bool(dr.get("arrivalWasMiss"))
        hs = hist_sorted(p)
        ages = [a if a is not None else age for a in (player_ages(p, hs) if hs else [])]
        main_side = predict_side({a: float(p[a]) for a in AB6}, role, age, hs, ages, static_features(p), miss, ov_models, pred, pred_rookie, gba)

        # 二刀流：野手側も計算し、見出しの数字は予測最大が高い方を使う
        tw = two_way_side(p)
        tw_side, tw_role, tw_g = None, None, None
        if tw:
            tw_role, tw_ab, pseudo = tw
            hs2 = hist_sorted(pseudo)
            ages2 = [a if a is not None else age for a in (player_ages(pseudo, hs2) if hs2 else [])]
            tw_g = pseudo["growth"]
            tw_side = predict_side(tw_ab, tw_role, age, hs2, ages2, static_features(pseudo), miss, ov_models, pred, pred_rookie, gba)
        best, best_g = main_side, g
        if tw_side and (tw_side["pmax"], tw_side["current"]) > (main_side["pmax"], main_side["current"]):
            best, best_g = tw_side, tw_g

        is_rookie = main_side["is_rookie"]
        main, subs, posstr = positions(p, role)
        if tw_role:
            c = ROLE_CAT[tw_role]
            sub_list = [x for x in subs.split("・") if x]
            if c != main and c not in sub_list:
                subs = "・".join(sub_list + [c])
        ext = is_external(p, team_name)
        dev = bool(p.get("developmentContract"))
        kubun = "移籍・外国人" if ext else ("育成" if dev else "支配下")
        if ext:
            dyear, drank = "外部入団", "外部"
        else:
            dyear = str(dr.get("year")) if dr.get("year") is not None else "不明"
            rnd = dr.get("round")
            drank = ("育成" if dr.get("isDevelopment") else "") + (f"{rnd}位" if rnd is not None else "不明")
        row = {
            "id": p.get("id"),
            "背番号": p.get("uniformNumber"),
            "名前": p.get("surname") or p.get("familyName") or "",
            "役割": role,
            "所属": p.get("level") or "",
            "年齢": age,
            "将来性": dr.get("potentialGrade") or "-",
            "注目度": dr.get("attentionGrade") or "-",
            "区分": kubun,
            "新人": "新人" if is_rookie else "",
            "ドラフト年": dyear,
            "ドラフト順位": drank,
            "タイプ": ARCHETYPE.get(best_g.get("archetype"), str(best_g.get("archetype") or "不明")),
            "設定ピーク年齢": best_g.get("peakAge"),
            "現在": best["current"],
            "予測最大": best["pmax"],
            "到達年齢": best["reach"],
            "誤差": best["誤差"],
            "前年比": best["前年比"],
            "ポジ": main,
            "サブポジ": subs,
            "守備位置": posstr,
            "入団時ハズレ": "ハズレ" if miss else "",
            "伸びしろ": best["伸びしろ"],
            "二刀流": bool(tw_side),
        }
        for key in AB_KEYS:
            row[key] = main_side[key]
            row[key + "_前年比"] = main_side[key + "_前年比"]
        row["状態"] = best["状態"]
        row["三軍推奨"] = ""
        row["推奨メニュー"] = main_side["推奨メニュー"]
        if tw_side:
            pitcher_first = role == "投手"
            row["投手"] = side_public(main_side, role, g) if pitcher_first else side_public(tw_side, tw_role, tw_g)
            row["野手"] = side_public(tw_side, tw_role, tw_g) if pitcher_first else side_public(main_side, role, g)
        row["_hist_max"] = best["hist_max"]
        row["_fut"] = best["pmax"]   # 今後の最高総合の予測（編成提案用、書き出し前に消す）
        row["_p"] = p                # 元の選手データ（同上）
        rows.append(row)
    return rows


def assign_third_squad(rows):
    limit = max(0, len(rows) - THIRD_SQUAD_RESERVE)
    cands = [r for r in rows if r["所属"] != "一軍" and r["年齢"] <= 24 and r["伸びしろ"] >= 5]

    def prio(r):
        return 0 if r["新人"] else (1 if r["伸びしろ"] >= 10 else 2)

    cands.sort(key=lambda r: (prio(r), -r["予測最大"], -r["伸びしろ"]))
    for r in cands[:limit]:
        r["三軍推奨"] = "推奨"
    return limit, min(limit, len(cands))


# ----------------------------------------------------------------------
# 5. 本体
# ----------------------------------------------------------------------
def main():
    log("1/6 セーブデータを探しています…")
    save_path, game_dt = pick_newest_save()
    log(f"  使用するセーブデータ: {save_path.name}")

    log("2/6 セーブデータを展開しています…")
    parts = decode_save(save_path)
    p0, own, others, p3 = parts
    if not isinstance(own, list) or not own:
        die("自チームの選手データが見つかりません（2 番目の区切りが選手の一覧ではありません）。")
    retired = (p3.get("retiredPlayers") if isinstance(p3, dict) else None) or []
    team_name = p0.get("teamName") or ""
    phase = p0.get("phase") or ""
    log(f"  球団: {team_name}　ゲーム内日付: {game_dt.year}年{game_dt.month}月{game_dt.day}日（{phase}）")
    log(f"  自チーム {len(own)} 人、他球団 {len(others)} 人、引退選手 {len(retired)} 人")

    log("3/6 能力値から総合を求める変換を学習しています…")
    ov_models, ov_report = fit_overall_models(list(own) + list(others) + list(retired))

    log("4/6 生涯最高の総合と到達年齢の予測モデルを学習しています…")
    train, train_rookie, gba = build_training(list(retired) + [p for p in own if int(p.get("age") or 0) >= 34])
    if len(train[0]) < 200:
        die(f"学習に使える引退選手の経歴が少なすぎます（{len(train[0])} 件）。")
    pred = fit_predictors(train, "既存選手の")
    pred_rookie = fit_predictors(train_rookie, "新人の")

    log("5/6 自チームの選手を計算しています…")
    rows = compute_players(own, team_name, ov_models, pred, pred_rookie, gba)
    limit, assigned = assign_third_squad(rows)

    log("6/6 オフの編成提案を作っています…")
    import roster_plan
    roster_plan.build_plan(roster_plan_build_module(), p0, own, rows, retired, ov_models, game_dt,
                           DOCS / "data" / "roster_plan.json", DOCS / "draft.json")
    for r in rows:
        for k in ("_hist_max", "_fut", "_p"):
            r.pop(k, None)
    rows.sort(key=lambda r: (-r["予測最大"], -r["現在"]))

    season_year = max(int(h["year"]) for p in own for h in hist_sorted(p)) if any(hist_sorted(p) for p in own) else None
    rookies = [r for r in rows if r["新人"]]
    top_rookie = max(rookies, key=lambda r: r["予測最大"]) if rookies else None
    now = datetime.datetime.now(JST)
    meta = {
        "球団名": team_name,
        "ゲーム内日付": f"{game_dt.year}年{game_dt.month}月{game_dt.day}日",
        "フェーズ": phase,
        "開幕年": season_year,
        "更新日時": now.strftime("%Y-%m-%d %H:%M"),
        "セーブファイル": save_path.name,
        "選手数": len(rows),
        "新人数": len(rookies),
        "三軍推奨数": assigned,
        "三軍上限": limit,
        "総合の推定": ov_report,
        "予測モデルの誤差": {"既存選手": pred[3], "新人": pred_rookie[3]},
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "players.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ": ")), encoding="utf-8")
    (DOCS / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    log("")
    log("できあがり:")
    log(f"  選手 {len(rows)} 人（新人 {len(rookies)} 人、三軍推奨 {assigned} 人／上限 {limit} 人）")
    if top_rookie:
        log(f"  注目の新人: {top_rookie['名前']}（予測最大 {top_rookie['予測最大']}）")
    st = {}
    for r in rows:
        st[r["状態"]] = st.get(r["状態"], 0) + 1
    log("  状態の内訳: " + "、".join(f"{k} {v}人" for k, v in st.items()))
    log("  ゲーム画面と見比べる用（総合の計算値）:")
    for r in rows[:5]:
        log(f"    {r['名前']}（{r['役割']}・{r['所属']}）総合 {r['現在']}")
    tw_n = sum(1 for r in rows if r.get("二刀流"))
    if tw_n:
        log(f"  二刀流の選手: {tw_n} 人（予測は参考値）")
    log(f"  書き出し: {DOCS / 'players.json'}, {DOCS / 'meta.json'}, {DOCS / 'data' / 'roster_plan.json'}, {DOCS / 'draft.json'}")


def roster_plan_build_module():
    """roster_plan.py に渡す「このファイルの道具一式」"""
    return sys.modules[__name__]


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
