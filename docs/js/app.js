/* ============================================================
   ESY 選手成長予測  アプリ本体
   - players.json / qa.json / meta.json / data/roster_plan.json を読み込んで表示する
   - これらは build.py が自動生成する（qa.json だけ手で書く）
   ============================================================ */
(function () {
  'use strict';

  // ---------- 設定（ここを変えると表示が変わる） ----------
  const STAR = 90;                 // 「予測最大が◯以上」のしきい値
  const PLAYERS_URL = 'players.json';
  const QA_URL = 'qa.json';
  const META_URL = 'meta.json';   // build.py が出力する更新情報（ゲーム内日付など）
  const PLAN_URL = 'data/roster_plan.json';  // roster_plan.py が出力するオフの編成提案
  const DRAFT_URL = 'draft.json';            // roster_plan.py が出力するドラフト候補
  // meta.json が無いときの文言。{Y} は開幕年に置き換わる。
  const NOTE_SAVE = '{Y}年シーズン';
  const NOTE_BASE = '{Y}年開幕時';

  // ---------- 定数 ----------
  const POS_C = { '投': 'var(--p-p)', '捕': 'var(--p-c)', '内': 'var(--p-i)', '外': 'var(--p-o)' };
  const POS_CAT = { '投手': '投', '捕手': '捕', '一塁': '内', '二塁': '内', '三塁': '内', '遊撃': '内', '左翼': '外', '中堅': '外', '右翼': '外' };
  const AB_FIELDS = ['巧打・制球', '長打・変化', '走力・体力', '守備・球威', '精神'];
  const TIERS = [[90, 'var(--c3)'], [80, 'var(--c1)'], [70, 'var(--c5)'], [60, 'var(--c2)'], [50, 'var(--c0)'], [0, 'var(--c7)']];
  const ST_VAR = { '新人': 'var(--s-new)', '伸び盛り': 'var(--s-grow)', '成熟期': 'var(--s-mid)', 'ピーク': 'var(--s-peak)', '下降期': 'var(--s-down)' };
  const GR_VAR = { 'A': 'var(--c5)', 'B': 'var(--c0)', 'C': 'var(--c2)', 'D': 'var(--c7)', 'E': 'var(--c7)' };
  const CAT_C = { 'ウィンターリーグ': 'var(--s-new)', '将来性・成長': 'var(--s-grow)', '成長タイプ': 'var(--s-mid)', '予測': 'var(--s-peak)', '育成方針': 'var(--p-o)', 'ドラフト': 'var(--p-p)', '隠し数値': 'var(--c1)', '分析の仕組み': 'var(--c7)' };
  const LB = { P: ['制球', '変化', '体力', '球威', '精神'], B: ['巧打', '長打', '走力', '守備', '精神'] };
  const ST_ORDER = { '新人': 0, '伸び盛り': 1, '成熟期': 2, 'ピーク': 3, '下降期': 4 };

  // ---------- 画面の状態 ----------
  const BP = { status: '', role: '', kubun: '', dy: '', tri: '', q: '', sort: '予測最大', dir: -1, open: new Set(), qopen: new Set() };
  let PLAYERS = null;   // 選手データ（配列）
  let QA = null;        // 質問データ（配列）
  let META = null;      // 更新情報（meta.json、無くても動く）
  let PLAN = null;      // オフの編成提案（data/roster_plan.json、無くても動く）
  let DRAFT = null;     // ドラフト候補（draft.json、無くても動く）
  const DF = { role: '', grade: '', attn: '', sort: '予測最大', dir: -1, q: '', open: new Set() };
  const LOT_VAR = { '高': 'var(--color-bad)', '中': 'var(--color-warn)', '低': 'var(--color-ok)' };
  const FRAME_VAR = { '1位候補': 'var(--gold)', '狙い目': 'var(--s-grow)', '育成候補': 'var(--s-new)' };
  // 判定の色（推奨＝赤系、検討＝黄系、昇格＝緑系、例外＝灰色、育成へ＝青系）
  const JD_VAR = { '推奨': 'var(--color-bad)', '自由契約': 'var(--color-bad)', '検討': 'var(--color-warn)', '育成再契約': 'var(--color-warn)',
    '即昇格': 'var(--color-ok)', '先行昇格': 'var(--color-ok)', '支配下': 'var(--color-ok)', '育成へ': 'var(--s-new)',
    '残留（例外）': 'var(--c7)', '残留（検証中）': 'var(--c7)', '1位': 'var(--gold)', '外れ1位': 'var(--c5)',
    '戦力外': 'var(--color-bad)', '次点': 'var(--color-warn)' };

  // ---------- 小さな道具 ----------
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };
  const isNil = (v) => v === null || v === undefined || v === '';
  const num = (v) => Number(v);
  const setText = (id, v) => { const e = $(id); if (e) e.textContent = isNil(v) ? '—' : String(v); };

  // ---------- 更新情報（meta.json） ----------
  // build.py が書き出す { "ゲーム内日付": "2157年2月3日", "シーズン年": 2157, "更新日時": "…", "セーブファイル": "…" }
  function drawAsof() {
    const p = $('asof');
    if (!p) return;
    p.replaceChildren();
    if (!META) return;
    const add = (lab, val) => { if (isNil(val)) return; const s = el('span'); s.append(document.createTextNode(lab + ' '), el('b', null, String(val))); p.append(s); };
    add('ゲーム内の日付', META['ゲーム内日付']);
    add('サイト更新', META['更新日時']);
  }

  // ---------- 集計（元の dash.calc('summary') 相当） ----------
  function summary(players) {
    const rookies = players.filter(r => r['新人'] === '新人');
    const top = rookies.slice().sort((a, b) => num(b['予測最大']) - num(a['予測最大']))[0];
    return {
      '新人数': rookies.length,
      '伸び盛り人数': players.filter(r => r['状態'] === '伸び盛り').length,
      '主力候補人数': players.filter(r => num(r['予測最大']) >= STAR).length,
      'ピーク以降人数': players.filter(r => r['状態'] === 'ピーク' || r['状態'] === '下降期').length,
      '注目新人': top ? top['名前'] : '',
      '注目新人予測': top ? num(top['予測最大']) : null
    };
  }
  function drawSummary() {
    const s = summary(PLAYERS);
    setText('s_new', s['新人数']); setText('t_new', s['新人数']);
    setText('s_topnew', s['注目新人']); setText('s_topnewv', s['注目新人予測']);
    const lede = document.querySelector('.lede');
    if (lede && !s['新人数']) {
      // 新人がいない時期（ドラフト前など）は、注目選手を伸び盛りの最有力に切り替える
      const grow = PLAYERS.filter(r => r['状態'] === '伸び盛り').sort((a, b) => num(b['予測最大']) - num(a['予測最大']))[0];
      lede.replaceChildren();
      lede.append(document.createTextNode('今回の新人はまだいません（ドラフト前）。'));
      if (grow) {
        lede.append(document.createTextNode('伸び盛りで最も期待できるのは'), el('b', null, String(grow['名前'])), document.createTextNode('（予測最大総合力'), el('b', null, String(grow['予測最大'])), document.createTextNode('）です。'));
      }
    }
    const eyebrow = document.querySelector('.eyebrow');
    if (eyebrow && META && META['球団名']) eyebrow.textContent = `${META['球団名']} ／ 育成レポート`;
    setText('t_grow', s['伸び盛り人数']);
    setText('t_star', s['主力候補人数']);
    setText('t_peak', s['ピーク以降人数']);
    setText('th_star', STAR);
  }

  // シーズン年 ＝ データ内の最大ドラフト年＋1（例：2156年ドラフトの新人がいれば 2157年）
  // 開幕年 ＝ 前年比の基準になる年（meta.json があればそれを使い、無ければドラフト年から推定）
  function seasonYear() {
    if (META && Number.isFinite(Number(META['開幕年']))) return Number(META['開幕年']);
    const ys = PLAYERS.map(r => Number(r['ドラフト年'])).filter(y => Number.isFinite(y) && y > 0);
    return ys.length ? Math.max(...ys) + 1 : null;
  }
  // 三軍推奨の基準の説明（基準の数字は meta.json にあればそれを使う）
  function triNote(tri) {
    const c = (META && META['三軍推奨の基準']) || { '年齢ごとの総合': { '20': 55, '21': 60, '22': 65, '23': 70, '24': 75, '25': 80 }, '見込みの総合': 80, '空き枠の年齢': 20 };
    const ages = Object.keys(c['年齢ごとの総合']).sort((a, b) => Number(a) - Number(b)).map(a => `${a}歳で${c['年齢ごとの総合'][a]}`).join('・');
    const b = META && META['三軍推奨の内訳'];
    const br = b ? `（内訳：年齢基準 ${b['年齢基準']}人、${c['見込みの総合']}到達の見込み ${b['80到達の見込み']}人、空き枠 ${b['空き枠']}人${b['枠から漏れた基準該当者'] ? `。枠が足りず ${b['枠から漏れた基準該当者']}人は入れていません` : ''}）` : '';
    return `「三軍推奨」は、一軍以外の選手から、①年齢ごとの総合の基準（${ages} 以上）を満たす選手、②基準は満たさないが総合${c['見込みの総合']}に届く見込み（予測最大${c['見込みの総合']}以上）の選手、③それでも空きがあれば${c['空き枠の年齢']}歳以下を総合の高い順、の順に${tri}人（全選手数−70）まで選んだものです${br}。`;
  }
  function drawNote() {
    const y = seasonYear();
    const save = META && META['ゲーム内日付'] ? `ゲーム内 ${META['ゲーム内日付']}${META['フェーズ'] ? '・' + META['フェーズ'] : ''}` : (y ? NOTE_SAVE.replace('{Y}', y) : 'セーブ時点');
    const base = y ? NOTE_BASE.replace('{Y}', y) : '今季開幕時';
    const tri = PLAYERS.filter(r => r['三軍推奨'] === '推奨').length;
    $('note').textContent =
      `能力・総合はセーブ時点（${save}）の値です。選手名をタップすると詳細が開きます。` +
      '名前の右は、ポジション（塗りつぶし＝本職、枠だけ＝守れる別ポジション）・ドラフト順位・総合・年齢です。' +
      `前年比（各能力も同じ）は${base}からの伸びです。誤差は予測最大のずれの目安です。将来性の丸の色は等級（A〜E）ごとに分けています。` +
      triNote(tri) +
      '練習メニューは、その役割の総合への影響が大きく、まだ低い能力を伸ばすものです。「入団時ハズレ」は、入団時の実際の能力がスカウト評価を大きく下回った選手です。' +
      '二刀流の選手の総合は、ゲームの表示に合わせた合成値（高い側×0.75＋低い側×0.25）で、予測最大・伸びしろは投手・野手の高い側の値です。詳細の「投手として」「野手として」はそれぞれの能力だけで計算しています（参考値）。';
    const info = $('datainfo');
    if (info) info.textContent = `選手 ${PLAYERS.length} 人${y ? `・${y}年シーズン時点のデータ` : ''}${META && META['セーブファイル'] ? `・${META['セーブファイル']}` : ''}`;
  }

  // ---------- 絞り込み・並び替え ----------
  function filtered() {
    if (!PLAYERS) return null;
    const q = BP.q.trim();
    const rows = PLAYERS.filter(r =>
      (!BP.status || r['状態'] === BP.status) &&
      (!BP.role || (BP.role === '二刀流' ? !!r['二刀流'] : r['役割'] === BP.role)) &&
      (!BP.kubun || r['区分'] === BP.kubun) &&
      (!BP.dy || String(r['ドラフト年']) === BP.dy) &&
      (!BP.tri ||
        (BP.tri === 'rec' && r['三軍推奨'] === '推奨') ||
        (BP.tri === 'in' && r['三軍推奨'] === '推奨' && r['所属'] !== '三軍') ||
        (BP.tri === 'out' && r['三軍推奨'] !== '推奨' && r['所属'] === '三軍')) &&
      (!q || String(r['名前']).includes(q) || String(r['背番号']) === q));
    const k = BP.sort, numeric = !['名前', '将来性', '状態', 'タイプ'].includes(k);
    rows.sort((a, b) => {
      let x = a[k], y = b[k];
      if (k === '状態') { x = ST_ORDER[x]; y = ST_ORDER[y]; }
      else if (k === 'ドラフト年') { x = Number(x) || 0; y = Number(y) || 0; }
      else if (k === '前年比') { x = isNil(x) ? 999 * BP.dir : Number(x); y = isNil(y) ? 999 * BP.dir : Number(y); }
      else if (numeric) { x = Number(x); y = Number(y); }
      else { x = String(x); y = String(y); }
      if (k === '将来性') return (x < y ? -1 : x > y ? 1 : 0) * -BP.dir;
      const c = (x < y ? -1 : x > y ? 1 : 0) * BP.dir;
      if (c) return c;
      if (k === '年齢') return (num(b['現在']) - num(a['現在'])) || (num(b['予測最大']) - num(a['予測最大']));   // 同じ年齢の中は総合の高い順
      return num(b['予測最大']) - num(a['予測最大']);
    });
    return rows;
  }

  // ---------- 選手リスト描画 ----------
  function drawRows() {
    const box = $('rows');
    const rows = filtered();
    box.replaceChildren();
    setText('shown', rows ? rows.length : null);
    if (!rows) return;
    if (!rows.length) { box.append(el('div', 'wait', '条件に合う選手がいません。')); return; }
    for (const r of rows) box.append(playerItem(r));
  }

  function playerItem(r) {
    const id = r['id'], open = BP.open.has(id);
    const item = el('div', 'pl' + (open ? ' open' : ''));
    item.style.setProperty('--k', ST_VAR[r['状態']] || 'var(--c7)');

    // 見出し行
    const head = el('button', 'plh'); head.type = 'button';
    head.setAttribute('aria-expanded', String(open));
    const tv = num(r['現在']); const tt = TIERS.find(z => tv >= z[0]) || TIERS[TIERS.length - 1];
    const ov = el('span', 'ov', String(r['現在'])); ov.style.setProperty('--t', tt[1]);
    const rk = el('span', 'rk' + (String(r['ドラフト順位']).startsWith('育成') ? ' dev' : ''), String(r['ドラフト順位']));
    const pw = el('span', 'pos');
    const pm0 = el('span', 'pm0', String(r['ポジ'])); pm0.style.setProperty('--pc', POS_C[r['ポジ']] || 'var(--c7)'); pw.append(pm0);
    String(r['サブポジ'] || '').split('・').filter(Boolean).forEach(s => { const e = el('span', 'ps', s); e.style.setProperty('--pc', POS_C[s] || 'var(--c7)'); pw.append(e); });
    const nm = el('span', 'nm', String(r['名前']));
    if (r['二刀流']) nm.append(document.createTextNode(' '), el('span', 'tw', '二刀流'));
    head.append(nm, pw, rk, ov, el('span', 'ag', String(r['年齢']) + '歳'), el('span', 'chev', open ? '▴' : '▾'));
    head.addEventListener('click', () => { if (BP.open.has(id)) BP.open.delete(id); else BP.open.add(id); drawRows(); });
    item.append(head);
    if (!open) return item;

    // 詳細
    const d = el('div', 'pld');
    const tags = el('div', 'tags');
    tags.append(el('span', 'pill', String(r['状態'])));
    if (r['入団時ハズレ'] === 'ハズレ') tags.append(el('span', 'miss', '入団時ハズレ'));
    if (r['三軍推奨'] === '推奨') { tags.append(el('span', 'trirec', '三軍推奨')); if (r['三軍理由']) tags.append(el('span', 'tag', String(r['三軍理由']))); }
    tags.append(gradeTag('将来性', r['将来性']));
    tags.append(gradeTag('注目度', r['注目度']));
    tags.append(el('span', 'tag', '背番号 ' + String(r['背番号'])));
    tags.append(el('span', 'tag', `${r['役割']}・${r['所属']}・${r['区分']}`));
    tags.append(el('span', 'tag', /^\d+$/.test(String(r['ドラフト年'])) ? String(r['ドラフト年']) + '年ドラフト' : String(r['ドラフト年'])));
    tags.append(el('span', 'tag', 'タイプ ' + String(r['タイプ'])));
    d.append(tags);

    const pl = el('div', 'posl');
    String(r['守備位置'] || '').split('／').filter(Boolean).forEach(s => {
      const [nm, v] = s.trim().split(' ');
      const e = el('span', 'pp'); e.style.setProperty('--pc', POS_C[POS_CAT[nm]] || 'var(--c7)');
      e.append(el('span', null, nm), el('b', null, v || '')); pl.append(e);
    });
    d.append(pl);

    const st = el('div', 'stats');
    const stat = (lab, val, cls) => { const s = el('div', 'st' + (cls ? ' ' + cls : '')); s.append(el('div', 'sl', lab), el('div', 'sv', val)); st.append(s); return s; };
    stat('総合', String(r['現在']));
    const dv = r['前年比'];
    const ys = stat('前年比', isNil(dv) ? '—' : (Number(dv) > 0 ? '+' : '') + String(dv), 'yoy');
    if (!isNil(dv)) ys.style.setProperty('--k', Number(dv) > 0 ? 'var(--s-grow)' : Number(dv) < 0 ? 'var(--s-down)' : 'var(--c7)');
    stat('予測最大', String(r['予測最大']), 'pm');
    stat('到達年齢', String(r['到達年齢']) + '歳');
    stat('伸びしろ', '+' + String(r['伸びしろ']));
    stat('誤差', '±' + String(r['誤差']));
    d.append(st);

    const bar = el('div', 'bar');
    const cur = Math.max(0, Math.min(100, num(r['現在']))), pm = Math.max(0, Math.min(100, num(r['予測最大'])));
    const c1 = el('div', 'cur'); c1.style.width = cur + '%';
    const c2 = el('div', 'up'); c2.style.left = cur + '%'; c2.style.width = Math.max(0, pm - cur) + '%';
    bar.append(c1, c2); d.append(bar);

    if (r['二刀流'] && r['投手'] && r['野手']) {
      // 二刀流：投手として／野手として の2段
      const sides = el('div', 'sides');
      sides.append(sideBlock(r['投手'], '投手として', true), sideBlock(r['野手'], '野手として', true));
      d.append(sides);
    } else {
      d.append(abGrid(r, r['役割'], true));
      if (r['推奨メニュー']) d.append(menuBox(r['推奨メニュー']));
      d.append(el('div', 'foot', `設定ピーク ${r['設定ピーク年齢']}歳`));
    }
    item.append(d);
    return item;
  }

  // 将来性・注目度の札（色付き丸）
  function gradeTag(label, v) {
    const g = el('span', 'grd', String(isNil(v) || v === '-' ? '—' : v)); g.style.setProperty('--k', GR_VAR[v] || 'var(--c7)');
    const w = el('span', 'tag'); w.append(el('span', null, label), g); return w;
  }
  // 能力5項目のグリッド（yoy=true で前年比も出す）
  function abGrid(src, role, yoy) {
    const ab = el('div', 'abs');
    const labs = role === '投手' ? LB.P : LB.B;
    AB_FIELDS.forEach((f, i) => {
      const v = num(src[f]); const tier = TIERS.find(z => v >= z[0]) || TIERS[TIERS.length - 1];
      const a = el('div', 'ab'); a.style.setProperty('--k', tier[1]);
      const mb = el('div', 'mb'); const mf = el('i'); mf.style.width = Math.max(0, Math.min(100, v)) + '%'; mb.append(mf);
      a.append(el('div', 'al', labs[i]), el('div', 'av', String(isNil(src[f]) ? '—' : src[f])));
      if (yoy) {
        const dv2 = src[f + '_前年比'];
        const dl = el('div', 'yd', isNil(dv2) ? '前年 —' : (Number(dv2) > 0 ? '▲' + String(dv2) : Number(dv2) < 0 ? '▼' + String(Math.abs(Number(dv2))) : '±0'));
        dl.style.setProperty('--d', isNil(dv2) || Number(dv2) === 0 ? 'var(--color-fg-muted)' : Number(dv2) > 0 ? 'var(--s-grow)' : 'var(--s-down)');
        a.append(dl);
      }
      a.append(mb);
      ab.append(a);
    });
    return ab;
  }
  function menuBox(text) {
    const mn = el('div', 'menu'); mn.append(el('span', 'ml', '三軍の練習メニュー'), el('span', 'mv', String(text))); return mn;
  }
  // 二刀流の片側（投手として／野手として）
  function sideBlock(sd, label, yoy) {
    const b = el('div', 'side'); b.style.setProperty('--pc', POS_C[sd['ポジ']] || 'var(--c7)');
    const h = el('div', 'sh');
    h.append(el('span', null, `${label}（${sd['役割']}）`));
    if (sd['参考値']) h.append(el('span', 'ref', '参考値'));
    if (sd['状態']) { const pl = el('span', 'pill', String(sd['状態'])); pl.style.setProperty('--k', ST_VAR[sd['状態']] || 'var(--c7)'); h.append(pl); }
    b.append(h);
    const st = el('div', 'stats');
    const stat = (lab, val, cls) => { const s = el('div', 'st' + (cls ? ' ' + cls : '')); s.append(el('div', 'sl', lab), el('div', 'sv', val)); st.append(s); return s; };
    stat('総合', String(sd['総合']));
    stat('予測最大', String(sd['予測最大']), 'pm');
    stat('到達年齢', String(sd['到達年齢']) + '歳');
    if (yoy) {
      const dv = sd['前年比'];
      const ys = stat('前年比', isNil(dv) ? '—' : (Number(dv) > 0 ? '+' : '') + String(dv), 'yoy');
      if (!isNil(dv)) ys.style.setProperty('--k', Number(dv) > 0 ? 'var(--s-grow)' : Number(dv) < 0 ? 'var(--s-down)' : 'var(--c7)');
    }
    stat('伸びしろ', '+' + String(isNil(sd['伸びしろ']) ? Math.max(0, num(sd['予測最大']) - num(sd['総合'])) : sd['伸びしろ']));
    stat('誤差', '±' + String(sd['誤差']));
    b.append(st);
    b.append(abGrid(sd, sd['役割'], yoy));
    if (sd['推奨メニュー']) b.append(menuBox(sd['推奨メニュー']));
    b.append(el('div', 'foot', `タイプ ${sd['タイプ']}・設定ピーク ${sd['設定ピーク年齢']}歳`));
    return b;
  }

  // ---------- ドラフト年セレクト ----------
  function drawDyear() {
    const sel = $('dyear');
    const ys = [...new Set(PLAYERS.map(r => String(r['ドラフト年'])))].sort((a, b) => (Number(b) || 0) - (Number(a) || 0));
    sel.replaceChildren(new Option('すべての年度', ''), ...ys.map(y => new Option(/^\d+$/.test(y) ? y + '年ドラフト' : y, y)));
    sel.value = BP.dy;
  }

  // ---------- 能力の色の凡例 ----------
  function drawAbLegend() {
    $('ablegend').replaceChildren(...TIERS.map((z, i) => {
      const s = el('span'); s.style.setProperty('--k', z[1]);
      const label = i === 0 ? `能力${z[0]}以上` : (z[0] === 0 ? `${TIERS[i - 1][0]}未満` : `${z[0]}〜${TIERS[i - 1][0] - 1}`);
      s.append(el('i'), document.createTextNode(label));
      return s;
    }));
  }

  // ---------- 質問ボックス ----------
  function drawQA() {
    const box = $('qalist');
    box.replaceChildren();
    setText('qa_n', QA ? QA.length : null);
    if (!QA) return;
    for (const q of QA) {
      const key = String(q['no']); const open = BP.qopen.has(key);
      const item = el('div', 'qi' + (open ? ' open' : ''));
      item.style.setProperty('--k', CAT_C[q['カテゴリ']] || 'var(--gold)');
      const h = el('button', 'qh'); h.type = 'button';
      h.setAttribute('aria-expanded', String(open));
      const meta = el('div', 'qm'); meta.append(el('span', 'qno', 'Q' + key), el('span', 'qcat', String(q['カテゴリ'])));
      h.append(meta, el('div', 'qt', String(q['質問'])), el('span', 'chev', open ? '▴' : '▾'));
      h.addEventListener('click', () => { if (BP.qopen.has(key)) BP.qopen.delete(key); else BP.qopen.add(key); drawQA(); });
      item.append(h);
      if (open) item.append(qaBody(q));
      box.append(item);
    }
  }
  // 本文の簡易記法： "|a|b|c" → 表、"- xxx" → 箇条書き、それ以外 → 段落
  function qaBody(q) {
    const body = el('div', 'qb');
    const c = el('div', 'qc'); c.append(el('span', 'qcl', '結論'), el('span', null, String(q['結論']))); body.append(c);
    const lines = String(q['本文'] || '').split('\n');
    let tbl = null, ul = null;
    for (const ln of lines) {
      if (ln.startsWith('|')) {
        ul = null;
        const cells = ln.slice(1).split('|');
        if (!tbl) {
          const wrap = el('div', 'qtw'); tbl = el('table', 'qtab'); wrap.append(tbl); body.append(wrap);
          const tr = el('tr'); cells.forEach(x => tr.append(el('th', null, x))); tbl.append(tr);
        } else { const tr = el('tr'); cells.forEach(x => tr.append(el('td', null, x))); tbl.append(tr); }
      } else if (ln.startsWith('- ')) {
        tbl = null;
        if (!ul) { ul = el('ul', 'qul'); body.append(ul); }
        ul.append(el('li', null, ln.slice(2)));
      } else if (ln.trim()) { tbl = null; ul = null; body.append(el('p', 'qp', ln)); }
    }
    return body;
  }

  // ---------- タブ ----------
  const TABS = ['growth', 'plan', 'draft', 'qa'];
  function showTab(name, push) {
    if (!TABS.includes(name)) name = 'growth';
    TABS.forEach(t => { const p = $('tab-' + t); if (p) p.hidden = t !== name; });
    document.querySelectorAll('.tab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    if (push) { try { history.replaceState(null, '', name === 'growth' ? location.pathname : '#' + name); } catch (e) { /* 無視 */ } }
  }
  function setupTabs() {
    document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
      showTab(b.dataset.tab, true);
      if (b.classList.contains('jump')) { const t = $('tabs'); if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    }));
    window.addEventListener('hashchange', () => showTab(location.hash.replace('#', ''), false));
    showTab(location.hash.replace('#', ''), false);
  }

  // ---------- オフの編成提案 ----------
  function jdPill(text) {
    const s = el('span', 'pill', text);
    s.style.setProperty('--k', JD_VAR[text] || 'var(--c7)');
    return s;
  }
  function cell(tr, label, content, cls) {
    const td = el('td', cls || '');
    td.dataset.l = label;
    if (content instanceof Node) td.append(content); else td.textContent = isNil(content) ? '—' : String(content);
    tr.append(td);
    return td;
  }
  function posMark(p) {
    const s = el('span', 'pz', String(p || '')); s.style.setProperty('--pc', POS_C[p] || 'var(--c7)'); return s;
  }
  function nameCell(r, extra) {
    const w = el('span');
    w.append(el('span', null, String(r['名前'])));
    if (!isNil(r['背番号'])) w.append(el('span', 'un', '（' + String(r['背番号']) + '）'));
    if (r['外国人']) w.append(el('span', 'fo', '外国人'));
    (extra || []).forEach(x => w.append(x));
    return w;
  }
  function numCell(tr, label, v, cls) {
    const b = el('b', null, isNil(v) ? '—' : String(v));
    return cell(tr, label, b, 'num ' + (cls || ''));
  }
  function playerTable(rows) {
    const t = el('table', 'ptab');
    const th = el('thead'); const hr = el('tr');
    ['選手（背番号）', '年齢', 'ポジ', '所属', '総合', '予測最大', '伸びしろ', '判定', '理由'].forEach(h => hr.append(el('th', null, h)));
    th.append(hr); t.append(th);
    const tb = el('tbody');
    for (const r of rows) {
      const tr = el('tr'); tr.style.setProperty('--k', JD_VAR[r['判定']] || 'var(--c7)');
      cell(tr, '選手', nameCell(r), 'nm');
      numCell(tr, '年齢', r['年齢']);
      cell(tr, 'ポジ', posMark(r['ポジ']));
      cell(tr, '所属', r['所属']);
      numCell(tr, '総合', r['総合']);
      numCell(tr, '予測最大', r['予測最大'], 'pm');
      numCell(tr, '伸びしろ', '+' + String(r['伸びしろ']), 'up');
      const jd = el('span'); jd.append(jdPill(r['判定']));
      if (r['境界']) { const m = el('span', 'bd', '境界'); m.title = '予測最大が基準に近い候補。予測の誤差で候補から外れることがあります'; jd.append(m); }
      cell(tr, '判定', jd, 'jd');
      cell(tr, '理由', el('small', null, String(r['理由'] || '') + (r['境界'] ? '（予測最大が基準に近い）' : '')), 'rs');
      tb.append(tr);
    }
    t.append(tb);
    return t;
  }
  function draftTable(rows) {
    const t = el('table', 'ptab dtab');
    const th = el('thead'); const hr = el('tr');
    ['選手', '年齢', 'ポジ', '経歴', '総合', '予測最大', '注目度', '関心数', '1位候補', '推奨'].forEach(h => hr.append(el('th', null, h)));
    th.append(hr); t.append(th);
    const tb = el('tbody');
    for (const r of rows) {
      const tr = el('tr' ); if (r['対象外']) tr.classList.add('dim');
      tr.style.setProperty('--k', r['推奨'] ? JD_VAR[r['推奨']] : r['対象外'] ? 'var(--c7)' : 'var(--p-p)');
      const marks = [];
      if (r['同姓']) { const m = el('span', 'mk', '同姓あり'); m.title = String(r['同姓']); marks.push(m); }
      if (r['公言']) { const m = el('span', 'mk', '1位公言あり'); m.title = String(r['公言']) + ' が1位指名を公言'; m.style.color = 'var(--c6)'; m.style.borderColor = 'var(--c6)'; marks.push(m); }
      cell(tr, '選手', nameCell(r, marks), 'nm');
      numCell(tr, '年齢', r['年齢']);
      cell(tr, 'ポジ', posMark(r['ポジ']));
      cell(tr, '経歴', r['経歴']);
      numCell(tr, '総合', r['総合']);
      numCell(tr, '予測最大', r['予測最大'], 'pm');
      const g = el('span', 'grd', String(r['注目度'] || '-')); g.style.setProperty('--k', GR_VAR[r['注目度']] || 'var(--c7)');
      cell(tr, '注目度', g);
      numCell(tr, '関心数', r['関心数']);
      numCell(tr, '1位候補', r['1位候補数']);
      const jd = el('span');
      if (r['推奨']) jd.append(jdPill(r['推奨'])); else if (r['対象外']) jd.append(el('small', null, '対象外（予測最大が低い）')); else jd.textContent = '';
      cell(tr, '推奨', jd, 'jd');
      if (r['同姓']) { const s = el('small', null, '同姓の候補：' + String(r['同姓'])); cell(tr, '', s, 'rs'); }
      tb.append(tr);
    }
    t.append(tb);
    return t;
  }
  // ドラフトの指名人数（入力欄）
  function planPicks() {
    const n = (id) => Math.max(0, Math.min(30, Math.floor(Number($(id).value) || 0)));
    return { '支配下': n('dp_reg'), '育成': n('dp_dev') };
  }
  // 指名人数から、戦力外にする人数と対象を決める（ドラフト後に目標人数になるように）
  function planCalc() {
    const hc = PLAN['人数'], R = PLAN['戦力外'], pk = planPicks();
    const mv = hc['移動後'], tg = hc['目標'];
    const one = (pool) => {
      const cands = R[pool] || [];
      const need = mv[pool] + pk[pool] - tg[pool];          // 減らす必要がある人数（マイナスなら空き）
      const n = Math.max(0, Math.min(need, cands.length));
      return { need, n, cut: cands.slice(0, n), next: cands.slice(n), short: Math.max(0, need - cands.length) };
    };
    const reg = one('支配下'), dev = one('育成');
    const pre = { '支配下': mv['支配下'] - reg.n, '育成': mv['育成'] - dev.n };
    const post = { '支配下': pre['支配下'] + pk['支配下'], '育成': pre['育成'] + pk['育成'] };
    for (const o of [pre, post]) { o['合計'] = o['支配下'] + o['育成']; o['三軍上限'] = o['合計'] - hc['上限']['三軍の基準']; }
    return { pk, reg, dev, pre, post };
  }
  function drawHeadcount(c) {
    const box = $('hc'); box.replaceChildren();
    const hc = PLAN['人数'], tg = hc['目標'], lim = hc['上限'];
    const t = el('table', 'hc');
    const hr = el('tr'); ['', '現在', 'ドラフト前', 'ドラフト後', '目標'].forEach(h => hr.append(el('th', null, h))); t.append(hr);
    const tgText = { '支配下': String(tg['支配下']), '育成': String(tg['育成']), '合計': String(tg['支配下'] + tg['育成']), '三軍上限': `合計−${lim['三軍の基準']}` };
    for (const k of ['支配下', '育成', '合計', '三軍上限']) {
      const tr = el('tr'); tr.append(el('td', null, k));
      const cur = el('td'); cur.append(el('b', null, String(hc['現在'][k]))); tr.append(cur);
      const pre = el('td'); pre.append(el('b', null, String(c.pre[k]))); tr.append(pre);
      const isPool = k === '支配下' || k === '育成';
      const post = el('td', isPool ? (c.post[k] > tg[k] ? 'over' : c.post[k] < tg[k] ? 'near' : 'ok') : '');
      post.append(el('b', null, String(c.post[k])));
      if (isPool && c.post[k] < tg[k]) post.append(el('small', null, `空き${tg[k] - c.post[k]}`));
      if (isPool && c.post[k] > tg[k]) post.append(el('small', null, `${c.post[k] - tg[k]}人多い`));
      tr.append(post);
      const tl = el('td'); tl.append(el('b', null, tgText[k])); tr.append(tl); t.append(tr);
    }
    box.append(t);
    const mv = hc['移動後'];
    const line = (pool, x) => {
      const d = el('div', 'count');
      let msg = `${pool}：入れ替え後 ${mv[pool]}人 ＋ 指名 ${c.pk[pool]}人 − 目標 ${tg[pool]}人 ＝ `;
      if (x.need <= 0) msg += `戦力外は不要（${x.need < 0 ? `あと${-x.need}人の空き` : 'ちょうど'}）`;
      else msg += `戦力外 ${x.need}人` + (x.short ? `。ただし候補は${x.n}人まで（総合${PLAN['戦力外']['見込みの総合']}以上の見込みがある選手は残すため、あと${x.short}人は選べません）` : '');
      d.textContent = msg; return d;
    };
    box.append(line('支配下', c.reg), line('育成', c.dev));
    const b = hc['内訳'] || {};
    box.append(el('div', 'count', `入れ替え ＝ 支配下→育成 ${b['支配下→育成']}人、育成→支配下 ${b['育成→支配下']}人。「ドラフト前」は入れ替えと戦力外をすべて実行した後の人数です。`));
  }
  function planSection(no, title, countText, desc, rows, emptyText) {
    const sec = el('div', 'pls');
    const h = el('h3'); h.append(el('span', 'no', String(no)), document.createTextNode(title), el('span', 'cnt', countText)); sec.append(h);
    if (desc) sec.append(el('p', 'desc', desc));
    if (rows.length) sec.append(playerTable(rows)); else sec.append(el('div', 'none', emptyText || '該当する選手はいません。'));
    return sec;
  }
  function drawPlanLists(c) {
    const X = PLAN['入れ替え'], R = PLAN['戦力外'], nextN = Number(R['次点の人数']) || 5;
    const mark = (r, jd, why) => Object.assign({}, r, { '判定': jd, '理由': why === undefined ? r['理由'] : why });
    const cutDev = new Set(c.dev.cut.map(r => r['id']));
    const devRank = {}; (R['育成'] || []).forEach(r => { devRank[r['id']] = r; });
    const lists = $('plan_lists'); lists.replaceChildren();

    // 1. 支配下 → 育成（育成へ移した後に戦力外になった選手は 2 へ）
    const l1 = X['支配下→育成'];
    const rows1 = l1['行'].filter(r => !cutDev.has(r['id']));
    lists.append(planSection(1, l1['題'], `${rows1.length}人`, l1['説明'], rows1));

    // 2. 支配下 → 自由契約
    const movers = c.dev.cut.filter(r => r['元']).map(r => mark(r, '戦力外', `${r['理由']}（${r['元']}）`));
    const rows2 = c.reg.cut.map(r => mark(r, '戦力外')).concat(movers);
    const next2 = c.reg.next.slice(0, nextN).map(r => mark(r, '次点'));
    lists.append(planSection(2, '支配下 → 自由契約', `戦力外 ${rows2.length}人` + (next2.length ? `・次点 ${next2.length}人` : ''), R['説明'], rows2.concat(next2),
      c.reg.need <= 0 ? '戦力外は不要です（支配下に空きがあります）。' : '候補がいません（総合80以上の見込みがある選手だけです）。'));

    // 3. 育成 → 支配下
    const l3 = X['育成→支配下'];
    lists.append(planSection(3, l3['題'], `${l3['行'].length}人`, l3['説明'], l3['行']));

    // 4. 育成 → 自由契約（契約満了の選手は 5、支配下2年目の選手は 2 に出す）
    const rows4 = c.dev.cut.filter(r => !r['満了'] && !r['元']).map(r => mark(r, '戦力外'));
    const next4 = c.dev.next.filter(r => !r['満了'] && !r['元']).slice(0, nextN).map(r => mark(r, '次点'));
    const keep4 = (R['例外'] || []).filter(r => !r['満了']);
    lists.append(planSection(4, '育成 → 自由契約', `戦力外 ${rows4.length}人` + (next4.length ? `・次点 ${next4.length}人` : ''),
      '育成の戦力外のうち、契約満了ではない選手。「次点」は今回の人数には入らなかった候補です。例外リストの選手は「残留（検証中）」。', rows4.concat(next4, keep4),
      c.dev.need <= 0 ? '戦力外は不要です（育成に空きがあります）。' : '該当する選手はいません。'));

    // 5. 育成契約満了
    const l5 = X['満了'];
    const rows5 = l5['行'].map(r => {
      if (r['判定'] === '支配下') return r;
      if (cutDev.has(r['id'])) return mark(r, '自由契約', devRank[r['id']] ? devRank[r['id']]['理由'] : r['理由']);
      return mark(r, '育成再契約', devRank[r['id']] ? `候補だが今回の人数には入らず（${devRank[r['id']]['理由']}）` : r['理由']);
    });
    const n5 = (jd) => rows5.filter(r => r['判定'] === jd).length;
    lists.append(planSection(5, l5['題'], `${rows5.length}人（支配下 ${n5('支配下')}・育成再契約 ${n5('育成再契約')}・自由契約 ${n5('自由契約')}）`, l5['説明'], rows5,
      '今オフに契約が満了する育成選手はいません。'));
  }
  function refreshPlan() {
    const c = planCalc();
    drawHeadcount(c);
    drawPlanLists(c);
    try { localStorage.setItem('bp_picks', JSON.stringify(c.pk)); } catch (e) { /* 保存できなくても動く */ }
  }
  function drawPlan() {
    const asof = $('plan_asof');
    if (!PLAN) { asof.textContent = '編成提案のデータ（data/roster_plan.json）がまだありません。セーブデータをアップロードすると自動で作られます。'; return; }
    const tg = PLAN['人数']['目標'];
    asof.textContent = `ゲーム内 ${PLAN['ゲーム内日付']}${PLAN['フェーズ'] ? '・' + PLAN['フェーズ'] : ''} のセーブデータから作成。ドラフト後に 支配下${tg['支配下']}人・育成${tg['育成']}人 になるように戦力外の人数を決めます。`;
    $('dpick').hidden = false;
    try {
      const saved = JSON.parse(localStorage.getItem('bp_picks') || 'null');
      if (saved) { $('dp_reg').value = Number(saved['支配下']) || 0; $('dp_dev').value = Number(saved['育成']) || 0; }
    } catch (e) { /* 無視 */ }
    $('plan_legend').replaceChildren(...[['戦力外・自由契約', 'var(--color-bad)'], ['次点・育成再契約', 'var(--color-warn)'], ['昇格・支配下', 'var(--color-ok)'], ['育成へ', 'var(--s-new)'], ['例外・残留', 'var(--c7)']].map(([t, c]) => { const s = el('span'); s.style.setProperty('--k', c); s.append(el('i'), document.createTextNode(t)); return s; }));
    refreshPlan();
    const D = PLAN['ドラフト'] || {}; const box = $('dft'); box.replaceChildren();
    const sec = el('div', 'pls');
    const h = el('h3'); h.append(el('span', 'no', '6'), document.createTextNode(`ドラフト候補（${(D['対象の経歴'] || ['高卒']).join('・')}で将来性A）`), el('span', 'cnt', `${(D['候補'] || []).length}人／全候補 ${D['候補数'] || 0}人`)); sec.append(h);
    sec.append(el('p', 'desc', `他球団（${D['他球団数'] || 0}球団）の関心一覧から「関心数」と「1位候補にしている球団数」を数えています。予測最大が低い候補は薄く表示。1位の推奨は、1位候補にしている球団が少ない候補の中で予測最大が最も高い選手と、その抽選に外れた場合の次点です。`));
    if (D['推奨'] && D['推奨']['文']) { const r = el('div', 'rec'); r.append(el('span', 'rl', '1位指名の推奨'), document.createTextNode(String(D['推奨']['文']))); sec.append(r); }
    if (D['公言'] && D['公言']['球団']) { const d = el('div', 'decl'); d.append(document.createTextNode('1位指名の公言：'), el('b', null, String(D['公言']['球団'])), document.createTextNode(' → '), el('b', null, String(D['公言']['選手'] || '?'))); sec.append(d); }
    if ((D['候補'] || []).length) sec.append(draftTable(D['候補'])); else sec.append(el('div', 'none', D['段階'] && D['段階'] !== 'scheduled' ? '今はドラフト候補の時期ではありません（ドラフト後のセーブデータ）。' : 'ドラフト候補のデータがありません。'));
    box.append(sec);
    $('plan_note').textContent = (PLAN['注意'] || '') + (D['予測誤差'] ? ` ドラフト候補の予測誤差（平均）：±${D['予測誤差']}。` : '');
    ['dp_reg', 'dp_dev'].forEach(id => $(id).addEventListener('input', refreshPlan));
  }

  // ---------- ドラフト候補タブ ----------
  function prospectItem(r, frameName) {
    const id = r['id'], open = DF.open.has(id);
    const item = el('div', 'pl' + (open ? ' open' : '') + (r['対象外'] ? ' dim' : ''));
    item.style.setProperty('--k', frameName ? (FRAME_VAR[frameName] || 'var(--gold)') : (POS_C[r['ポジ']] || 'var(--c7)'));
    const head = el('button', 'plh'); head.type = 'button';
    head.setAttribute('aria-expanded', String(open));
    const nm = el('span', 'nm', String(r['名前']));
    if (r['二刀流']) nm.append(document.createTextNode(' '), el('span', 'tw', '二刀流'));
    const pw = el('span', 'pos');
    const pm0 = el('span', 'pm0', String(r['ポジ'])); pm0.style.setProperty('--pc', POS_C[r['ポジ']] || 'var(--c7)'); pw.append(pm0);
    String(r['サブポジ'] || '').split('・').filter(Boolean).forEach(s => { const e = el('span', 'ps', s); e.style.setProperty('--pc', POS_C[s] || 'var(--c7)'); pw.append(e); });
    const g = el('span', 'grd', String(r['将来性'])); g.style.setProperty('--k', GR_VAR[r['将来性']] || 'var(--c7)'); g.title = '将来性';
    const sr = el('span', 'sr', isNil(r['スカウト順位']) ? '' : 'スカウト' + String(r['スカウト順位']) + '位');
    const tv = num(r['予測最大']); const tt = TIERS.find(z => tv >= z[0]) || TIERS[TIERS.length - 1];
    const ov = el('span', 'ov', String(r['予測最大'])); ov.style.setProperty('--t', tt[1]); ov.title = '予測最大';
    const lot = el('span', 'lot', `抽選${r['抽選']}・${r['関心数']}球団`); lot.style.setProperty('--k', LOT_VAR[r['抽選']] || 'var(--c7)');
    head.append(nm, pw, g, sr, lot, ov, el('span', 'ag', String(r['年齢']) + '歳'), el('span', 'chev', open ? '▴' : '▾'));
    head.addEventListener('click', () => { if (DF.open.has(id)) DF.open.delete(id); else DF.open.add(id); drawDraft(); });
    item.append(head);
    if (!open) return item;

    const d = el('div', 'pld');
    const tags = el('div', 'tags');
    (r['枠'] || []).forEach(f => { const pl = el('span', 'pill', f); pl.style.setProperty('--k', FRAME_VAR[f] || 'var(--gold)'); tags.append(pl); });
    if (r['推奨']) tags.append(jdPill(r['推奨']));
    tags.append(gradeTag('将来性', r['将来性']), gradeTag('注目度', r['注目度']));
    tags.append(el('span', 'tag', `${r['経歴']}${r['出身'] ? '・' + r['出身'] : ''}`));
    if (r['利き']) tags.append(el('span', 'tag', String(r['利き'])));
    tags.append(el('span', 'tag', 'タイプ ' + String(r['タイプ'])));
    if (r['補強方針']) { const f = el('span', 'fit'); f.append(el('span', null, '補強方針に合う'), el('b', null, String(r['補強方針']))); tags.append(f); }
    if (r['公言']) { const m = el('span', 'mk', '1位公言あり'); m.title = String(r['公言']) + ' が1位指名を公言'; m.style.color = 'var(--c6)'; m.style.borderColor = 'var(--c6)'; tags.append(m); }
    if (r['同姓']) { const m = el('span', 'mk', '同姓の候補あり'); m.title = String(r['同姓']); tags.append(m); }
    d.append(tags);

    const pl = el('div', 'posl');
    String(r['守備位置'] || '').split('／').filter(Boolean).forEach(s => {
      const [nm2, v] = s.trim().split(' ');
      const e = el('span', 'pp'); e.style.setProperty('--pc', POS_C[POS_CAT[nm2]] || 'var(--c7)');
      e.append(el('span', null, nm2), el('b', null, v || '')); pl.append(e);
    });
    d.append(pl);

    const st = el('div', 'stats');
    const stat = (lab, val, cls) => { const s = el('div', 'st' + (cls ? ' ' + cls : '')); s.append(el('div', 'sl', lab), el('div', 'sv', val)); st.append(s); return s; };
    stat('総合（今）', String(r['総合']));
    stat('予測最大', String(r['予測最大']), 'pm');
    stat('到達年齢', String(r['到達年齢']) + '歳');
    stat('誤差', '±' + String(r['誤差']));
    const li = stat('興味球団', String(r['関心数']) + '球団', 'yoy'); li.style.setProperty('--k', LOT_VAR[r['抽選']] || 'var(--c7)');
    stat('1位候補に', String(r['1位候補数']) + '球団');
    if (DRAFT && DRAFT['育成関心あり']) stat('育成枠で興味', String(r['育成関心数']) + '球団');
    d.append(st);

    const bar = el('div', 'bar');
    const cur = Math.max(0, Math.min(100, num(r['総合']))), pm = Math.max(0, Math.min(100, num(r['予測最大'])));
    const c1 = el('div', 'cur'); c1.style.width = cur + '%';
    const c2 = el('div', 'up'); c2.style.left = cur + '%'; c2.style.width = Math.max(0, pm - cur) + '%';
    bar.append(c1, c2); d.append(bar);

    if (r['二刀流'] && r['投手'] && r['野手']) {
      const sides = el('div', 'sides');
      sides.append(sideBlock(Object.assign({ '参考値': true }, r['投手']), '投手として', false), sideBlock(Object.assign({ '参考値': true }, r['野手']), '野手として', false));
      d.append(sides);
    } else {
      d.append(abGrid(r, r['役割'], false));
      d.append(el('div', 'foot', `設定ピーク ${r['設定ピーク年齢']}歳`));
    }
    if (r['同姓']) d.append(el('div', 'memo', '同姓の候補：' + String(r['同姓'])));
    if (r['メモ']) d.append(el('div', 'memo', 'スカウトのメモ：' + String(r['メモ'])));
    if (r['対象外']) d.append(el('div', 'memo', '予測最大が低いため、おすすめの枠からは外しています。'));
    item.append(d);
    return item;
  }
  function draftFiltered() {
    const q = DF.q.trim();
    const rows = (DRAFT['候補'] || []).filter(r =>
      (!DF.role || (DF.role === '二刀流' ? !!r['二刀流'] : r['役割'] === DF.role)) &&
      (!DF.grade || (DF.grade === 'D' ? ['D', 'E', '-'].includes(String(r['将来性'])) : r['将来性'] === DF.grade)) &&
      (!DF.attn || (DF.attn === 'D' ? ['D', 'E', '-'].includes(String(r['注目度'])) : r['注目度'] === DF.attn)) &&
      (!q || String(r['名前']).includes(q)));
    const k = DF.sort;
    rows.sort((a, b) => {
      let x = Number(a[k]), y = Number(b[k]);
      if (k === 'スカウト順位') { x = Number.isFinite(x) && x > 0 ? x : 9999; y = Number.isFinite(y) && y > 0 ? y : 9999; return (x - y) * -DF.dir || (num(b['予測最大']) - num(a['予測最大'])); }
      return (x - y) * DF.dir || (num(b['予測最大']) - num(a['予測最大']));
    });
    return rows;
  }
  function drawDraft() {
    const asof = $('dft_asof');
    if (!DRAFT) { asof.textContent = 'ドラフト候補のデータ（draft.json）がまだありません。セーブデータをアップロードすると自動で作られます。'; return; }
    setText('dft_year', DRAFT['ドラフト年'] ? `${DRAFT['ドラフト年']}年` : '');
    const base = `ゲーム内 ${DRAFT['ゲーム内日付']}${DRAFT['フェーズ'] ? '・' + DRAFT['フェーズ'] : ''} のセーブデータ`;
    if (!DRAFT['表示']) {
      asof.textContent = `${base}。今はドラフト候補の時期ではありません（日本一決定戦の後〜ドラフト前のセーブデータで表示されます）。` + (DRAFT['来年の候補数'] ? ` 来年の候補 ${DRAFT['来年の候補数']} 人は参考扱いのため表示していません。` : '');
      $('dft_needs').replaceChildren(); $('dft_frames').replaceChildren(); $('dft_allwrap').hidden = true; $('dft_note').textContent = '';
      return;
    }
    asof.textContent = `${base}。${(DRAFT['対象の経歴'] || ['高卒']).join('・')}の候補 ${(DRAFT['候補'] || []).length} 人（全候補 ${DRAFT['候補数']} 人）。他球団 ${DRAFT['他球団数']} 球団の関心一覧から「興味球団数」を数えています。`;
    // 補強方針
    const nd = $('dft_needs'); nd.replaceChildren();
    if ((DRAFT['補強方針'] || []).length || DRAFT['補強方針の見出し']) {
      nd.append(el('div', 'nh', '自チームの補強方針' + (DRAFT['補強方針の見出し'] ? '：' + DRAFT['補強方針の見出し'] : '')));
      (DRAFT['補強方針'] || []).forEach(n => { const i = el('div', 'ni'); i.append(el('b', null, String(n['枠'] || '')), el('span', 'nc', String(n['一言'] || ''))); nd.append(i); });
      if (DRAFT['補強方針のまとめ']) nd.append(el('div', 'nc', String(DRAFT['補強方針のまとめ'])));
    }
    if (DRAFT['公言'] && DRAFT['公言']['球団']) { const dcl = el('div', 'ni'); dcl.append(el('b', null, '1位指名の公言'), el('span', 'nc', `${DRAFT['公言']['球団']} → ${DRAFT['公言']['選手'] || '?'}`)); nd.append(dcl); }
    // 3つの枠
    const fr = $('dft_frames'); fr.replaceChildren();
    const byId = {}; (DRAFT['候補'] || []).forEach(r => { byId[r['id']] = r; });
    for (const name of ['1位候補', '狙い目', '育成候補']) {
      const sec = el('div', 'frame'); sec.style.setProperty('--k', FRAME_VAR[name]);
      const h = el('div', 'fh'); h.append(el('span', 'ft', name), el('span', 'fd', String((DRAFT['枠の説明'] || {})[name] || ''))); sec.append(h);
      const ids = (DRAFT['枠'] || {})[name] || [];
      if (!ids.length) sec.append(el('div', 'none', '該当する候補はいません。'));
      const list = el('div', 'plist');
      ids.map(i => byId[i]).filter(Boolean).forEach(r => list.append(prospectItem(r, name)));
      sec.append(list); fr.append(sec);
    }
    // 全候補
    $('dft_allwrap').hidden = false;
    const rows = draftFiltered();
    setText('dft_n', `表示中 ${rows.length} 人`);
    const box = $('dft_rows'); box.replaceChildren();
    if (!rows.length) box.append(el('div', 'wait', '条件に合う候補がいません。'));
    rows.forEach(r => box.append(prospectItem(r, null)));
    $('dft_note').textContent = (DRAFT['注意'] || '') + ' 「抽選」は興味を持つ球団数の目安（3球団以上＝高、1〜2＝中、0＝低）。1位候補にしている球団数は、各球団の関心一覧で先頭に置いている数です。';
  }
  function setupDraftControls() {
    document.querySelectorAll('.chip[data-dgroup]').forEach(btn => btn.addEventListener('click', () => {
      const g = btn.dataset.dgroup; DF[g] = g === 'dir' ? Number(btn.dataset.value) : btn.dataset.value;
      document.querySelectorAll(`.chip[data-dgroup="${g}"]`).forEach(o => o.setAttribute('aria-pressed', String(o === btn)));
      drawDraft();
    }));
    $('dft_search').addEventListener('input', (e) => { DF.q = e.target.value; drawDraft(); });
    $('dft_sort').addEventListener('change', (e) => { DF.sort = e.target.value; drawDraft(); });
  }

  // ---------- 操作イベント ----------
  function setupControls() {
    document.querySelectorAll('.chip').forEach(btn => btn.addEventListener('click', () => {
      const g = btn.dataset.group; BP[g] = g === 'dir' ? Number(btn.dataset.value) : btn.dataset.value;
      document.querySelectorAll(`.chip[data-group="${g}"]`).forEach(o => o.setAttribute('aria-pressed', String(o === btn)));
      drawRows();
    }));
    $('search').addEventListener('input', (e) => { BP.q = e.target.value; drawRows(); });
    $('sortsel').addEventListener('change', (e) => { BP.sort = e.target.value; drawRows(); });
    $('dyear').addEventListener('change', (e) => { BP.dy = e.target.value; drawRows(); });
    document.querySelectorAll('[data-jump]').forEach(b => b.addEventListener('click', () => {
      const t = $(b.dataset.jump); if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
  }

  // ---------- データ読み込み ----------
  async function loadJson(url) {
    const res = await fetch(url, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${url} を読み込めませんでした（HTTP ${res.status}）`);
    return res.json();
  }
  function showError(msg) {
    const box = $('rows');
    const e = el('div', 'error');
    e.append(el('div', null, msg));
    if (location.protocol === 'file:') {
      const p = el('div');
      p.append(document.createTextNode('index.html を直接ダブルクリックで開くと、ブラウザの安全機能でデータを読み込めません。GitHub Pages で公開したURLから開くか、ローカルサーバー経由で開いてください。'));
      e.append(p);
    }
    box.replaceChildren(e);
    setText('qa_n', null);
  }

  async function main() {
    setupControls();
    setupDraftControls();
    setupTabs();
    try {
      const [players, qa, meta, plan, draft] = await Promise.all([loadJson(PLAYERS_URL), loadJson(QA_URL).catch(() => []), loadJson(META_URL).catch(() => null), loadJson(PLAN_URL).catch(() => null), loadJson(DRAFT_URL).catch(() => null)]);
      if (!Array.isArray(players)) throw new Error('players.json の形式が違います（配列ではありません）');
      PLAYERS = players; QA = Array.isArray(qa) ? qa : []; META = meta && typeof meta === 'object' ? meta : null;
      PLAN = plan && typeof plan === 'object' && plan['戦力外'] && plan['入れ替え'] && plan['人数'] ? plan : null;
      DRAFT = draft && typeof draft === 'object' && Array.isArray(draft['候補']) ? draft : null;
    } catch (err) {
      console.error(err);
      showError('データの読み込みに失敗しました: ' + err.message);
      return;
    }
    drawAsof();
    drawSummary();
    drawNote();
    drawDyear();
    drawAbLegend();
    drawRows();
    drawQA();
    drawPlan();
    drawDraft();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', main); else main();
})();
