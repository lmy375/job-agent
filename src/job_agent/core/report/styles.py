"""报告的内联样式表。

不依赖任何外部 JS/CSS：图表全部用行内 SVG / CSS 条形画出来，
配色与刻度遵循 dataviz 规范（分类色按固定顺序取，单序列统一用 slot 1）。
"""

from __future__ import annotations

CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --surface-1:#fcfcfb; --plane:#f9f9f7;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --series-1:#2a78d6; --series-2:#eb6834; --series-3:#1baf7a;
  --series-4:#eda100; --series-5:#e87ba4; --series-6:#008300;
  --good:#0ca30c; --warn:#fab219; --crit:#d03b3b;
  --track:rgba(11,11,11,.055);
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --surface-1:#1a1a19; --plane:#0d0d0d;
    --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
    --series-4:#c98500; --series-5:#d55181; --series-6:#008300;
    --track:rgba(255,255,255,.07);
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --surface-1:#1a1a19; --plane:#0d0d0d;
  --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70;
  --series-4:#c98500; --series-5:#d55181; --series-6:#008300;
  --track:rgba(255,255,255,.07);
}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--plane);color:var(--text-primary);
  font:15px/1.7 system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
}
.wrap{max-width:1080px;margin:0 auto;padding:48px 20px 96px}
header.hero{border-bottom:1px solid var(--border);padding-bottom:28px;margin-bottom:8px}
h1{font-size:clamp(26px,4.4vw,38px);line-height:1.25;margin:0 0 10px;letter-spacing:-.02em}
.hero p{color:var(--text-secondary);margin:0;max-width:70ch}
.meta{color:var(--muted);font-size:13px;margin-top:14px}
h2{font-size:clamp(20px,3vw,26px);margin:56px 0 6px;letter-spacing:-.01em;
   padding-top:20px;border-top:1px solid var(--border)}
#overview>h2{margin-top:28px;padding-top:0;border-top:none}
h2 .sub{display:block;font-size:14px;font-weight:400;color:var(--text-secondary);
        letter-spacing:0;margin-top:4px}
h3{font-size:17px;margin:36px 0 12px}
h4{font-size:13px;margin:0 0 12px;color:var(--text-secondary);font-weight:600;
   letter-spacing:.02em}
p{margin:0 0 12px}
a{color:var(--series-1)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
       gap:12px;margin:20px 0}
.stat{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
      padding:16px 18px}
.stat-v{font-size:26px;font-weight:640;letter-spacing:-.02em;line-height:1.2}
.stat-l{font-size:12.5px;color:var(--text-secondary);margin-top:4px}
.stat-n{font-size:11.5px;color:var(--muted);margin-top:2px}
.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.card-grid.g2{grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
      padding:18px}
.bars{display:flex;flex-direction:column;gap:7px}
.bar-row{display:grid;grid-template-columns:minmax(84px,150px) 1fr 46px;
         align-items:center;gap:10px;min-height:22px}
.bar-label{font-size:12.5px;color:var(--text-secondary);overflow-wrap:anywhere;line-height:1.35}
.bar-track{background:var(--track);border-radius:4px;height:11px;overflow:hidden}
.bar-fill{height:100%;border-radius:0 4px 4px 0;min-width:2px}
.bar-val{font-size:12px;color:var(--text-secondary);text-align:right;
         font-variant-numeric:tabular-nums}
.bar-val .pct{color:var(--muted);font-size:10.5px}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:6px 0 14px;font-size:12.5px;
        color:var(--text-secondary)}
.lg{display:inline-flex;align-items:center;gap:6px}
.lg i{width:10px;height:10px;border-radius:2px;display:inline-block}
.lg-n{color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.grp{display:flex;flex-direction:column;gap:10px}
.grp-row{display:grid;grid-template-columns:minmax(90px,150px) 1fr;gap:12px;align-items:center}
.grp-cells{display:flex;flex-direction:column;gap:3px}
.mini-row{display:grid;grid-template-columns:1fr 38px;gap:8px;align-items:center}
.mini{background:var(--track);border-radius:3px;height:12px;overflow:hidden}
.mini-fill{height:100%;border-radius:0 3px 3px 0;min-width:2px}
.mini-v{font-size:11px;color:var(--text-secondary);text-align:right;
        font-variant-numeric:tabular-nums}
.insight{background:var(--surface-1);border:1px solid var(--border);
         border-left:3px solid var(--series-1);border-radius:0 10px 10px 0;
         padding:16px 20px;margin:18px 0 24px}
.insight.warn{border-left-color:var(--warn)}
.insight ul{margin:8px 0 0;padding-left:22px}
.insight li{margin-bottom:7px}
.insight strong{color:var(--text-primary)}
details.tbl{margin:18px 0;border:1px solid var(--border);border-radius:10px;
            background:var(--surface-1)}
details.tbl>summary{cursor:pointer;padding:13px 18px;font-size:13.5px;
                    color:var(--text-secondary);font-weight:600}
details.tbl[open]>summary{border-bottom:1px solid var(--border)}
.tbl table{width:100%;border-collapse:collapse;font-size:13px}
.tbl th,.tbl td{padding:8px 18px;text-align:left;border-bottom:1px solid var(--grid);
                vertical-align:top}
.tbl th{color:var(--muted);font-weight:600;font-size:11.5px;letter-spacing:.03em;
        text-transform:uppercase}
.tbl td.num,.tbl th.num{text-align:right;font-variant-numeric:tabular-nums}
.tbl tbody tr:last-child td{border-bottom:none}
.scroll{overflow-x:auto}
.empty{color:var(--muted);font-size:12.5px;margin:0}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0 0}
.toc a{display:inline-block;padding:6px 13px;border:1px solid var(--border);
       border-radius:999px;font-size:13px;text-decoration:none;color:var(--text-secondary);
       background:var(--surface-1)}
.toc a:hover{color:var(--text-primary);border-color:var(--axis)}
.matrix{width:100%;border-collapse:collapse;font-size:13.5px;background:var(--surface-1)}
.matrix th,.matrix td{padding:11px 14px;border-bottom:1px solid var(--grid);text-align:left}
.matrix th{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.matrix td:first-child{font-weight:600}
.matrix td.num,.matrix th.num{text-align:right;font-variant-numeric:tabular-nums}
/* 「与上一版相比变了什么」的旁注：视觉上要弱于正文，否则会和结论抢注意力 */
.note{font-size:12.5px;color:var(--text-secondary);border-top:1px solid var(--grid);
      margin-top:12px;padding-top:10px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;
      font-weight:600;white-space:nowrap}
.p-strong{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good)}
.p-mid{background:color-mix(in srgb,var(--warn) 22%,transparent);color:var(--text-primary)}
.p-gap{background:color-mix(in srgb,var(--crit) 15%,transparent);color:var(--crit)}
.plan{counter-reset:step;padding:0;list-style:none;margin:16px 0 0}
.plan>li{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
         padding:18px 20px 18px 60px;margin-bottom:12px;position:relative}
.plan>li::before{counter-increment:step;content:counter(step);position:absolute;
  left:18px;top:17px;width:26px;height:26px;border-radius:50%;background:var(--series-1);
  color:#fff;font-size:13px;font-weight:700;display:grid;place-items:center}
.plan h4{font-size:15px;color:var(--text-primary);margin-bottom:6px}
.plan .when{font-size:11.5px;color:var(--muted);margin-bottom:8px}
.plan ul{margin:8px 0 0;padding-left:20px;font-size:13.5px;color:var(--text-secondary)}
.plan li{margin-bottom:5px}
footer{margin-top:64px;padding-top:24px;border-top:1px solid var(--border);
       color:var(--muted);font-size:12.5px}
@media (max-width:640px){
  .wrap{padding:28px 14px 64px}
  .bar-row{grid-template-columns:minmax(72px,110px) 1fr 40px}
  .grp-row{grid-template-columns:1fr;gap:4px}
  .tbl th,.tbl td{padding:8px 12px}
}
"""
