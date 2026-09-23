from pathlib import Path
from io import BytesIO
import json, hashlib, re
import requests
from docx import Document
from lxml import html

out=Path(__file__).resolve().parent/'results'/'q1'/'official'
out.mkdir(parents=True,exist_ok=True)
sources={
 'announcement.html':'https://cpipc.acge.org.cn/cw/contestNews/detail/4/2c90801ca06f016101a0a47e06b77d9b?page=0',
 'format_2026.docx':'https://cpipc.acge.org.cn/sysFile/downFile.do?fileId=97a93e3a9e074738aea95eea986508f2',
 'template_2026.doc':'https://cpipc.acge.org.cn/sysFile/downFile.do?fileId=a730b312331e492baad17b248bad6b51'}
meta={}
for name,url in sources.items():
 r=requests.get(url,timeout=60);r.raise_for_status()
 (out/name).write_bytes(r.content)
 meta[name]={'url':url,'sha256':hashlib.sha256(r.content).hexdigest()}
 if name.endswith('docx'):
  content='\n'.join(p.text for p in Document(BytesIO(r.content)).paragraphs)
 elif name.endswith('html'):
  content=html.fromstring(r.content).text_content()
 else:continue
 (out/(name+'.txt')).write_text(content,encoding='utf-8')
 print(name,content if name.endswith('docx') else '\n'.join(x.strip() for x in content.splitlines() if any(t in x for t in ['截止','论文要求','格式要求','论文必须','首页','摘要','50M'])))
(out/'sources.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
