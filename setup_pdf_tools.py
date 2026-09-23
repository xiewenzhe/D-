"""Download the PDF audit binaries into this project only."""
from pathlib import Path
import hashlib, json, re, zipfile
import requests

root=Path(__file__).resolve().parent / '.tools'
root.mkdir(exist_ok=True)
url='https://github.com/oschwartz10612/poppler-windows/releases/expanded_assets/v26.09.0-0'
r=requests.get(url,timeout=60)
r.raise_for_status()
links=re.findall(r'href="([^"]+\.zip)"',r.text)
asset=next(x for x in links if '/releases/download/' in x)
source='https://github.com'+asset
target=root/'poppler.zip'
with requests.get(source,timeout=120,stream=True) as response:
    response.raise_for_status()
    with target.open('wb') as f:
        for block in response.iter_content(1024*1024):
            f.write(block)
            print(f'{f.tell()/1024**2:.1f} MiB',flush=True)
with zipfile.ZipFile(target) as z:
    for n in z.namelist():
        p=(root/n).resolve()
        if not p.is_relative_to(root.resolve()):
            raise ValueError('Unsafe archive path')
    z.extractall(root)
(root/'poppler-source.json').write_text(json.dumps({'source':source,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()},indent=2),encoding='utf-8')
print('PDF tools:',list(root.rglob('pdftoppm.exe')))
