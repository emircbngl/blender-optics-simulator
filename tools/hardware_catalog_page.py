"""Build the user-facing catalog from the generated manifest (no hand-maintained product list)."""
from pathlib import Path
import json
import html


def write_catalog(folder, target=None, prefix=''):
    folder=Path(folder)
    data=json.loads((folder/'catalog.json').read_text())
    cards=[]
    for p in data['products']:
        name=html.escape(p['name'].replace('_',' '))
        img=prefix+(p['preview'] or '')
        features=' · '.join(p['features']).replace('_',' ')
        cards.append(f'<article data-name="{name.lower()}"><img loading="lazy" src="{img}" alt="{name}"><div><h2>{name}</h2><p>{html.escape(features)}</p><a href="{prefix+p["file"]}">Blender presetini aç</a></div></article>')
    page='''<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Optomekanik kataloğu</title>
<style>*{box-sizing:border-box}body{background:#14171c;color:#eef0f2;font:16px system-ui;margin:0}main{max-width:1420px;margin:auto;padding:48px 28px}h1{font-size:38px;font-weight:500;letter-spacing:-1px}header p{max-width:820px;color:#b9c0cb;line-height:1.7}nav{display:flex;gap:20px;flex-wrap:wrap;margin:24px 0}a{color:#9cceff;text-underline-offset:4px}input{font:inherit;padding:14px 18px;background:#222830;border:1px solid #46505f;border-radius:8px;color:white;width:100%;margin:16px 0 28px}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:20px}article{border:1px solid #313844;border-radius:12px;overflow:hidden;background:#1c2128}article img{width:100%;display:block;aspect-ratio:1}article div{padding:18px}h2{font-size:18px;margin:0 0 10px}article p{font-size:13px;color:#a6b1c0;min-height:38px;line-height:1.6}article[hidden]{display:none}small{color:#abb6c6}</style><main><header>
<h1>Optomekanik kataloğu · COUNT preset</h1><p>Simülasyonda sade geometri, renderda ayrıntılı mekanik. Eski ve yeni ürünlerin tamamı aynı üretim hattından yenilendi. Yeni genel modeller üretim CAD'i değildir; gövde ölçüleri ve hareket sınırları yaklaşık tasarım değerleridir.</p>
<nav><a href="ZIP">Tüm presetleri indir</a><a href="ADDON">Güncel eklenti önizlemesi</a><a href="SCENE">Örnek Blender sahnesi</a></nav>
<small>Asset Browser: paketi çıkar → Preferences / File Paths / Asset Libraries → klasörü ekle → Append.</small></header>
<label for="search">Ürün ara</label><input id="search" type="search" placeholder="Örn. cage, XYZ, lens, RSP1">
<section>CARDS</section></main><script>document.getElementById('search').addEventListener('input',e=>{let q=e.target.value.toLowerCase().trim();document.querySelectorAll('article').forEach(c=>c.hidden=!c.dataset.name.includes(q));});</script></html>'''
    page=page.replace('COUNT',str(data['count'])).replace('CARDS','\n'.join(cards))
    base='' if prefix else '../'
    page=page.replace('ZIP',base+'optomechanics-assets.zip').replace('ADDON',base+'optics-hardware-preview.zip').replace('SCENE',base+'optomechanics-showcase/optomechanics-showcase.blend')
    Path(target or folder/'index.html').write_text(page)


if __name__=='__main__':
    import sys
    write_catalog(sys.argv[1])
