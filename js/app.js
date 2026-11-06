/* ============================================================
   ESY 選手成長予測  アプリ本体
   - data/players.json と data/qa.json を読み込んで表示する
   - 毎年の更新は data/players.json を差し替えるだけでOK
   ============================================================ */
(function () {
  'use strict';

  // ---------- 設定（ここを変えると表示が変わる） ----------
  const STAR = 90;                 // 「予測最大が◯以上」のしきい値
  const PLAYERS_URL = 'data/players.json';
  const QA_URL = 'data/qa.json';
  // セーブ時点・前年比の基準の文言。{Y} はシーズン年（最新ドラフト年＋1）、{Y1} はその前年に置き換わる。
  const NOTE_SAVE = '{Y}年2月・ウィンターリーグ後';
  const NOTE_BASE = '{Y1}年開幕時';

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

  // ---------- 小さな道具 ----------
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };
  const isNil = (v) => v === null || v === undefined || v === '';
  const num = (v) => Number(v);
  const setText = (id, v) => { const e = $(id); if (e) e.textContent = isNil(v) ? '—' : String(v); };

  // ---------- テーマ切り替え ----------
  function currentTheme() {
    const t = document.documentElement.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function setupTheme() {
    const btn = $('themeBtn');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('bp-theme', next); } catch (e) { /* 保存できなくても動く */ }
    });
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
    setText('t_grow', s['伸び盛り人数']);
    setText('t_star', s['主力候補人数']);
    setText('t_peak', s['ピーク以降人数']);
    setText('th_star', STAR);
  }

  // シーズン年 ＝ データ内の最大ドラフト年＋1（例：2156年ドラフトの新人がいれば 2157年）
  function seasonYear() {
    const ys = PLAYERS.map(r => Number(r['ドラフト年'])).filter(y => Number.isFinite(y) && y > 0);
    return ys.length ? Math.max(...ys) + 1 : null;
  }
  function drawNote() {
    const y = seasonYear();
    const save = y ? NOTE_SAVE.replace('{Y}', y).replace('{Y1}', y - 1) : 'セーブ時点';
    const base = y ? NOTE_BASE.replace('{Y}', y).replace('{Y1}', y - 1) : '前年開幕時';
    $('note').textContent =
      `能力・総合はセーブ時点（${save}）の値です。選手名をタップすると詳細が開きます。` +
      '名前の右は、ポジション（塗りつぶし＝本職、枠だけ＝守れる別ポジション）・ドラフト順位・総合・年齢です。' +
      `前年比（各能力も同じ）は${base}からの伸びです。誤差は予測最大のずれの目安です。将来性の丸の色は等級（A〜E）ごとに分けています。` +
      '「三軍推奨」は、一軍以外・24歳以下・伸びしろ5以上の選手を、新人→伸びしろ10以上→その他の順に予測最大の高い選手から74人選んだものです。' +
      '練習メニューは一番低い能力を伸ばすものです。「入団時ハズレ」は、入団時の実際の能力がスカウト評価を大きく下回った選手です。';
    const info = $('datainfo');
    if (info) info.textContent = `選手 ${PLAYERS.length} 人${y ? `・${y}年シーズン時点のデータ` : ''}`;
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
    if (!rows.length) { box.append(el('div', 'loading', '条件に合う選手がいません。')); return; }
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
    tags.append(el('span', 'badge', String(r['状態'])));
    if (r['入団時ハズレ'] === 'ハズレ') tags.append(el('span', 'miss', '入団時ハズレ'));
    if (r['三軍推奨'] === '推奨') tags.append(el('span', 'trirec', '三軍推奨'));
    const g = el('span', 'grade', String(r['将来性'])); g.style.setProperty('--k', GR_VAR[r['将来性']] || 'var(--c7)');
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
    setupTheme();
    setupControls();
    try {
      const [players, qa] = await Promise.all([loadJson(PLAYERS_URL), loadJson(QA_URL).catch(() => [])]);
      if (!Array.isArray(players)) throw new Error('players.json の形式が違います（配列ではありません）');
      PLAYERS = players; QA = Array.isArray(qa) ? qa : [];
    } catch (err) {
      console.error(err);
      showError('データの読み込みに失敗しました: ' + err.message);
      return;
    }
    drawSummary();
    drawNote();
    drawDyear();
    drawAbLegend();
    drawRows();
    drawQA();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', main); else main();
})();
