"""Generates static player pages (players/<id>/index.html) + sitemap.xml from the PLAYERS data in index.html."""
import re, json, os, html, datetime
root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
s=open(os.path.join(root,'index.html'),encoding='utf-8').read()
arr=re.search(r"const PLAYERS=\[(.*?)\n\];",s,re.S).group(1)
P=[]
for m in re.finditer(r"\{id:'([^']+)'(?:,t:'(\w)')?,n:(\d+),first:'([^']+)',last:'([^']+)',pos:'([^']+)',g:'[^']*',born:(\d+),h:\"([^\"]+)\",w:(\d+)(?:,highlights:'[^']*')?(?:,tag:'([^']+)')?",arr):
    i,t,n,f,l,pos,born,h,w,tag=m.groups()
    P.append(dict(id=i,t=t or 'a',n=int(n),first=f,last=l,pos=pos,born=int(born),h=h,w=int(w),tag=tag))
assert len(P)>=30,len(P)
NT=json.loads(re.search(r"const NT=(\{.*?\});",s).group(1))
CUT=set(json.loads(re.search(r"const CUT=new Set\((\[.*?\])\)",s).group(1)))
def cm(h):
    f,i=map(int,h.split("'"));return round((f*12+i)*2.54)
SITE='https://freedomuabasketball.com'
tpl=open(os.path.join(root,'scripts','player_tpl.html'),encoding='utf-8').read()
urls=[SITE+'/']
for p in P:
    name=f"{p['first']} {p['last']}"
    img='/img/'+p['id']+('.webp' if p['id'] in CUT else '.jpg')
    team='Freedom UA Basketball Academy'+(' (Juniors)' if p['t']=='j' else '')
    nt=NT.get(p['id'])
    ntb=''
    if nt: ntb='<h2>Ukraine national team</h2><ul>'+''.join(f'<li><b>{html.escape(a)}</b> {html.escape(b)} · {html.escape(c)}</li>' for a,b,c in nt)+'</ul>'
    desc=f"{name} (#{p['n']}) is a {p['pos'].lower()} for {team}. Born {p['born']}, {p['h']} ({cm(p['h'])} cm), {round(p['w']*0.4536)} kg."+(' Ukraine youth national team player.' if nt else '')
    ld={"@context":"https://schema.org","@type":"Person","name":name,"jobTitle":"Basketball player ("+p['pos']+")","birthDate":str(p['born']),"height":f"{cm(p['h'])} cm","weight":f"{round(p['w']*0.4536)} kg","image":SITE+img,"url":f"{SITE}/players/{p['id']}/","memberOf":{"@type":"SportsOrganization","name":"Freedom UA Basketball Academy","url":SITE+"/"}}
    page=tpl
    for k,v in {'{{NAME}}':html.escape(name),'{{FIRST}}':html.escape(p['first']),'{{LAST}}':html.escape(p['last']),'{{NUM}}':str(p['n']),'{{POS}}':html.escape(p['pos']),'{{BORN}}':str(p['born']),'{{H}}':f"{p['h']}\" · {cm(p['h'])} cm",'{{W}}':f"{p['w']} lbs · {round(p['w']*0.4536)} kg",'{{TEAM}}':html.escape(team),'{{ID}}':p['id'],'{{IMG}}':img,'{{DESC}}':html.escape(desc,quote=True),'{{NT}}':ntb,'{{LD}}':json.dumps(ld,ensure_ascii=False),'{{TAG}}':(' · '+html.escape(p['tag'])) if p['tag'] else ''}.items():
        page=page.replace(k,v)
    d=os.path.join(root,'players',p['id']);os.makedirs(d,exist_ok=True)
    open(os.path.join(d,'index.html'),'w',encoding='utf-8').write(page)
    urls.append(f"{SITE}/players/{p['id']}/")
today=datetime.date.today().isoformat()
sm='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+''.join(f"  <url>\n    <loc>{u}</loc>\n    <lastmod>{today}</lastmod>\n    <priority>{'1.0' if u.endswith('.com/') else '0.7'}</priority>\n  </url>\n" for u in urls)+'</urlset>\n'
open(os.path.join(root,'sitemap.xml'),'w').write(sm)
print(len(P),'players,',len(urls),'urls')
