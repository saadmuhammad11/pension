import fitz, os, json
E="C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad/evidence/thumbprints/"
os.makedirs(E+"native",exist_ok=True)
D="C:/Users/ahmed.raza/Downloads/"
files={"fp-non-gazetted":"Final Payment Non-Gaztted  (1).pdf","fp-death":"Final Payment Death Case (1).pdf","fp-dismissal":"Final Payment Dissmiss from Service  (1).pdf","refundable":"Refundable Advance  (1).pdf","non-refundable":"Non Refundable   (1).pdf","residual":"Residual Payment  (1).pdf"}
pages={"fp-non-gazetted":[3,4,7],"fp-death":[1,5,6,12],"fp-dismissal":[1,6],"refundable":[2,3],"non-refundable":[2,3],"residual":[4]}
meta={}
from PIL import Image
import io
for k,f in files.items():
    doc=fitz.open(D+f)
    for pn in pages[k]:
        p=doc[pn-1]
        best=max(p.get_image_info(xrefs=True), key=lambda i:i['width']*i['height'])
        d=doc.extract_image(best['xref'])
        fn=f"{k}_p{pn:03d}.{d['ext']}"
        open(E+"native/"+fn,"wb").write(d['image'])
        bw=best['bbox'][2]-best['bbox'][0]
        dpi=best['width']/bw*72
        im=Image.open(io.BytesIO(d['image']))
        # smaller preview for locating
        s=1600/max(im.size)
        im.resize((int(im.width*s),int(im.height*s))).save(E+"native/prev_"+fn.replace('.jpeg','.jpg'),quality=85)
        meta[fn]={"w":best['width'],"h":best['height'],"dpi":round(dpi,1),"preview_scale":round(1/s,4),"jpeg_bytes":len(d['image'])}
json.dump(meta,open(E+"native/meta.json","w"),indent=1)
print(json.dumps(meta,indent=1))
