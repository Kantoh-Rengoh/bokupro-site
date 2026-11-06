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
  // 判定の色（推奨＝赤系、検討＝黄系、昇格＝緑系、例外＝灰色、育成へ＝青系）
  const JD_VAR = { '推奨': 'var(--color-bad)', '自由契約': 'var(--color-bad)', '検討': 'var(--color-warn)', '育成再契約': 'var(--color-warn)',
    '即昇格': 'var(--color-ok)', '先行昇格': 'var(--color-ok)', '支配下': 'var(--color-ok)', '育成へ': 'var(--s-new)',
    '残留（例外）': 'var(--c7)', '残留（検証中）': 'var(--c7)', '1位': 'var(--gold)', '外れ1位': 'var(--c5)' };

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
  function drawNote() {
    const y = seasonYear();
    const save = META && META['ゲーム内日付'] ? `ゲーム内 ${META['ゲーム内日付']}${META['フェーズ'] ? '・' + META['フェーズ'] : ''}` : (y ? NOTE_SAVE.replace('{Y}', y) : 'セーブ時点');
    const base = y ? NOTE_BASE.replace('{Y}', y) : '今季開幕時';
    const tri = PLAYERS.filter(r => r['三軍推奨'] === '推奨').length;
    $('note').textContent =
      `能力・総合はセーブ時点（${save}）の値です。選手名をタップすると詳細が開きます。` +
      '名前の右は、ポジション（塗りつぶし＝本職、枠だけ＝守れる別ポジション）・ドラフト順位・総合・年齢です。' +
      `前年比（各能力も同じ）は${base}からの伸びです。誤差は予測最大のずれの目安です。将来性の丸の色は等級（A〜E）ごとに分けています。` +
      `「三軍推奨」は、一軍以外・24歳以下・伸びしろ5以上の選手を、新人→伸びしろ10以上→その他の順に予測最大の高い選手から${tri}人（全選手数−70）選んだものです。` +
      '練習メニューは、その役割の総合への影響が大きく、まだ低い能力を伸ばすものです。「入団時ハズレ」は、入団時の実際の能力がスカウト評価を大きく下回った選手です。';
    const info = $('datainfo');
    if (info) info.textContent = `選手 ${PLAYERS.length} 人${y ? `・${y}年シーズン時点のデータ` : ''}${META && META['セーブファイル'] ? `・${META['セーブファイル']}` : ''}`;
  }

  // ---------- 絞り込み・並び替え ----------
  function filtered() {
    if (!PLAYERS) return null;
    const q = BP.q.trim();
    const rows = PLAYERS.filter(r =>
      (!BP.status || r['状態'] === BP.status) &&
      (!BP.role || r['役割'] === BP.role) &&
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
      return (x < y ? -1 : x > y ? 1 : 0) * BP.dir || (num(b['予測最大']) - num(a['予測最大']));
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
    head.append(el('span', 'nm', String(r['名前'])), pw, rk, ov, el('span', 'ag', String(r['年齢']) + '歳'), el('span', 'chev', open ? '▴' : '▾'));
    head.addEventListener('click', () => { if (BP.open.has(id)) BP.open.delete(id); else BP.open.add(id); drawRows(); });
    item.append(head);
    if (!open) return item;

    // 詳細
    const d = el('div', 'pld');
    const tags = el('div', 'tags');
    tags.append(el('span', 'pill', String(r['状態'])));
    if (r['入団時ハズレ'] === 'ハズレ') tags.append(el('span', 'miss', '入団時ハズレ'));
    if (r['三軍推奨'] === '推奨') tags.append(el('span', 'trirec', '三軍推奨'));
    const g = el('span', 'grd', String(r['将来性'])); g.style.setProperty('--k', GR_VAR[r['将来性']] || 'var(--c7)');
    const gw = el('span', 'tag'); gw.append(el('span', null, '将来性'), g); tags.append(gw);
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

    const ab = el('div', 'abs');
    const labs = r['役割'] === '投手' ? LB.P : LB.B;
    AB_FIELDS.forEach((f, i) => {
      const v = num(r[f]); const tier = TIERS.find(z => v >= z[0]) || TIERS[TIERS.length - 1];
      const a = el('div', 'ab'); a.style.setProperty('--k', tier[1]);
      const mb = el('div', 'mb'); const mf = el('i'); mf.style.width = Math.max(0, Math.min(100, v)) + '%'; mb.append(mf);
      const dv2 = r[f + '_前年比'];
      const dl = el('div', 'yd', isNil(dv2) ? '前年 —' : (Number(dv2) > 0 ? '▲' + String(dv2) : Number(dv2) < 0 ? '▼' + String(Math.abs(Number(dv2))) : '±0'));
      dl.style.setProperty('--d', isNil(dv2) || Number(dv2) === 0 ? 'var(--color-fg-muted)' : Number(dv2) > 0 ? 'var(--s-grow)' : 'var(--s-down)');
      a.append(el('div', 'al', labs[i]), el('div', 'av', String(r[f])), dl, mb);
      ab.append(a);
    });
    d.append(ab);

    if (r['推奨メニュー']) { const mn = el('div', 'menu'); mn.append(el('span', 'ml', '三軍の練習メニュー'), el('span', 'mv', String(r['推奨メニュー']))); d.append(mn); }
    d.append(el('div', 'foot', `設定ピーク ${r['設定ピーク年齢']}歳`));
    item.append(d);
    return item;
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
  const TABS = ['growth', 'plan', 'qa'];
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
      if (r['境界']) { const m = el('span', 'bd', '境界'); m.title = '予測最大がしきい値ぎりぎり（±1）。予測の誤差で判定が入れ替わることがあります'; jd.append(m); }
      cell(tr, '判定', jd, 'jd');
      cell(tr, '理由', el('small', null, String(r['理由'] || '') + (r['境界'] ? '（しきい値ぎりぎり）' : '')), 'rs');
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
  function hcClass(kind, v, lim) {
    if (kind === '支配下' || kind === '育成') { if (v > lim['支配下' === kind ? '支配下' : '育成']) return 'over'; }
    if (kind === '育成' && v > lim['育成目標']) return 'near';
    if (kind === '支配下' || kind === '育成') return 'ok';
    return '';
  }
  function drawHeadcount() {
    const box = $('hc'); box.replaceChildren();
    const hc = PLAN['人数']; if (!hc) return;
    const lim = hc['上限'];
    const dpReg = Math.max(0, Number($('dp_reg').value) || 0), dpDev = Math.max(0, Number($('dp_dev').value) || 0);
    const after = hc['提案後'];
    const post = { '支配下': after['支配下'] + dpReg, '育成': after['育成'] + dpDev };
    post['合計'] = post['支配下'] + post['育成']; post['三軍上限'] = post['合計'] - lim['三軍の基準'];
    const t = el('table', 'hc');
    const hr = el('tr'); ['', '現在', '提案後', 'ドラフト後', '上限'].forEach(h => hr.append(el('th', null, h))); t.append(hr);
    const limText = { '支配下': String(lim['支配下']), '育成': `${lim['育成']}`, '合計': '—', '三軍上限': `合計−${lim['三軍の基準']}` };
    for (const k of ['支配下', '育成', '合計', '三軍上限']) {
      const tr = el('tr'); tr.append(el('td', null, k));
      for (const src of [hc['現在'], after, post]) {
        const td = el('td', hcClass(k, src[k], lim)); td.append(el('b', null, String(src[k]))); tr.append(td);
      }
      const tl = el('td'); tl.append(el('b', null, limText[k]));
      if (k === '育成') tl.append(el('small', null, `目標${lim['育成目標']}以下`));
      tr.append(tl); t.append(tr);
    }
    box.append(t);
    const b = PLAN['人数']['内訳'] || {};
    const note = el('div', 'count');
    note.textContent = `提案後 ＝ 支配下→育成 ${b['支配下→育成']}人、支配下→自由契約 ${b['支配下→自由契約']}人（検討 ${b['支配下→自由契約（検討）']}人は含めず）、育成→支配下 ${b['育成→支配下']}人、育成→自由契約 ${b['育成→自由契約']}人、満了→支配下 ${b['満了→支配下']}人・育成再契約 ${b['満了→育成再契約']}人・自由契約 ${b['満了→自由契約']}人 を実行した場合`;
    box.append(note);
  }
  function drawPlan() {
    const asof = $('plan_asof');
    if (!PLAN) { asof.textContent = '編成提案のデータ（data/roster_plan.json）がまだありません。セーブデータをアップロードすると自動で作られます。'; return; }
    asof.textContent = `ゲーム内 ${PLAN['ゲーム内日付']}${PLAN['フェーズ'] ? '・' + PLAN['フェーズ'] : ''} のセーブデータから作成`;
    $('dpick').hidden = false;
    drawHeadcount();
    $('plan_legend').replaceChildren(...[['推奨・自由契約', 'var(--color-bad)'], ['検討・育成再契約', 'var(--color-warn)'], ['昇格・支配下', 'var(--color-ok)'], ['育成へ', 'var(--s-new)'], ['例外・残留', 'var(--c7)']].map(([t, c]) => { const s = el('span'); s.style.setProperty('--k', c); s.append(el('i'), document.createTextNode(t)); return s; }));
    const lists = $('plan_lists'); lists.replaceChildren();
    for (const L of PLAN['一覧'] || []) {
      const sec = el('div', 'pls');
      const h = el('h3'); h.append(el('span', 'no', String(L['番号'])), document.createTextNode(String(L['題'])), el('span', 'cnt', `${L['行'].length}人`)); sec.append(h);
      sec.append(el('p', 'desc', String(L['説明'] || '')));
      if (L['行'].length) sec.append(playerTable(L['行'])); else sec.append(el('div', 'none', '該当する選手はいません。'));
      lists.append(sec);
    }
    const D = PLAN['ドラフト'] || {}; const box = $('dft'); box.replaceChildren();
    const sec = el('div', 'pls');
    const h = el('h3'); h.append(el('span', 'no', '6'), document.createTextNode('ドラフト候補（中卒・高卒で将来性A）'), el('span', 'cnt', `${(D['候補'] || []).length}人／全候補 ${D['候補数'] || 0}人`)); sec.append(h);
    sec.append(el('p', 'desc', `他球団（${D['他球団数'] || 0}球団）の関心一覧から「関心数」と「1位候補にしている球団数」を数えています。予測最大が低い候補は薄く表示。1位の推奨は、1位候補にしている球団が少ない候補の中で予測最大が最も高い選手と、その抽選に外れた場合の次点です。`));
    if (D['推奨'] && D['推奨']['文']) { const r = el('div', 'rec'); r.append(el('span', 'rl', '1位指名の推奨'), document.createTextNode(String(D['推奨']['文']))); sec.append(r); }
    if (D['公言'] && D['公言']['球団']) { const d = el('div', 'decl'); d.append(document.createTextNode('1位指名の公言：'), el('b', null, String(D['公言']['球団'])), document.createTextNode(' → '), el('b', null, String(D['公言']['選手'] || '?'))); sec.append(d); }
    if ((D['候補'] || []).length) sec.append(draftTable(D['候補'])); else sec.append(el('div', 'none', 'ドラフト候補のデータがありません（ドラフト後のセーブデータなど）。'));
    box.append(sec);
    $('plan_note').textContent = (PLAN['注意'] || '') + (D['予測誤差'] ? ` ドラフト候補の予測誤差（平均）：±${D['予測誤差']}。` : '');
    ['dp_reg', 'dp_dev'].forEach(id => $(id).addEventListener('input', drawHeadcount));
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
    setupTabs();
    try {
      const [players, qa, meta, plan] = await Promise.all([loadJson(PLAYERS_URL), loadJson(QA_URL).catch(() => []), loadJson(META_URL).catch(() => null), loadJson(PLAN_URL).catch(() => null)]);
      if (!Array.isArray(players)) throw new Error('players.json の形式が違います（配列ではありません）');
      PLAYERS = players; QA = Array.isArray(qa) ? qa : []; META = meta && typeof meta === 'object' ? meta : null;
      PLAN = plan && typeof plan === 'object' && Array.isArray(plan['一覧']) ? plan : null;
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
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', main); else main();
})();
