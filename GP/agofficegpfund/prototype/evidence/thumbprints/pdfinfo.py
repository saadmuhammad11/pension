import fitz, glob, os
D="C:/Users/ahmed.raza/Downloads/"
files={"fp-non-gazetted":"Final Payment Non-Gaztted  (1).pdf","fp-death":"Final Payment Death Case (1).pdf","fp-dismissal":"Final Payment Dissmiss from Service  (1).pdf","refundable":"Refundable Advance  (1).pdf","non-refundable":"Non Refundable   (1).pdf","residual":"Residual Payment  (1).pdf"}
pages={"fp-non-gazetted":[3,4,7],"fp-death":[1,5,6,12],"fp-dismissal":[1,6],"refundable":[2,3],"non-refundable":[2,3],"residual":[4]}
for k,f in files.items():
    doc=fitz.open(D+f)
    print(k, doc.page_count)
    for pn in pages[k]:
        p=doc[pn-1]
        infos=p.get_image_info(xrefs=True)
        for i in infos:
            bw=i['bbox'][2]-i['bbox'][0]; bh=i['bbox'][3]-i['bbox'][1]
            print(f"  p{pn} page={p.rect.width:.0f}x{p.rect.height:.0f}pt rot={p.rotation} img xref={i['xref']} {i['width']}x{i['height']} bbox={[round(x) for x in i['bbox']]} dpi={i['width']/bw*72:.1f}x{i['height']/bh*72:.1f} cs={i.get('colorspace')} bpc={i.get('bpc')} xres={i.get('xres')}")
            if i['xref']:
                d=doc.extract_image(i['xref']); print("     ext",d['ext'],len(d['image']),"bytes")
