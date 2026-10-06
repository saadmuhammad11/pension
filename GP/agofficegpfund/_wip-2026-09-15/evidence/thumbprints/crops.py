import fitz, json, io
from PIL import Image
E="C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad/evidence/thumbprints/"
D="C:/Users/ahmed.raza/Downloads/"
files={"fp-non-gazetted":"Final Payment Non-Gaztted  (1).pdf","fp-death":"Final Payment Death Case (1).pdf","fp-dismissal":"Final Payment Dissmiss from Service  (1).pdf","refundable":"Refundable Advance  (1).pdf","non-refundable":"Non Refundable   (1).pdf","residual":"Residual Payment  (1).pdf"}
meta=json.load(open(E+"native/meta.json"))
# mode 'disp': coords on corpus page JPEG displayed with 2.375 px/pt; mode 'prev': coords on native preview
C=[
 ("fpng_p3_cnic_front","fp-non-gazetted",3,"disp",(180,230,1190,1730)),
 ("fpng_p4_cnic_back","fp-non-gazetted",4,"disp",(50,50,1260,1880)),
 ("fpng_p4_printed_thumb","fp-non-gazetted",4,"disp",(430,1430,900,1840)),
 ("fpng_p7_sb_row","fp-non-gazetted",7,"disp",(200,760,1160,1200)),
 ("fpng_p7_sb_little","fp-non-gazetted",7,"disp",(215,780,350,900)),
 ("fpng_p7_sb_ring","fp-non-gazetted",7,"disp",(470,770,630,890)),
 ("fpng_p7_sb_middle","fp-non-gazetted",7,"disp",(895,825,1060,950)),
 ("fpng_p7_sb_fore","fp-non-gazetted",7,"disp",(250,1055,410,1175)),
 ("fpng_p7_sb_thumb","fp-non-gazetted",7,"disp",(940,1050,1145,1190)),
 ("death_p1_thumb","fp-death",1,"disp",(930,1320,1130,1460)),
 ("death_p5_cnic_front","fp-death",5,"disp",(490,200,1270,670)),
 ("death_p5_cnic_back","fp-death",5,"disp",(380,1090,1160,1660)),
 ("death_p6_cnic_back","fp-death",6,"disp",(250,150,1080,680)),
 ("death_p6_cnic_front","fp-death",6,"disp",(240,1090,1070,1630)),
 ("death_p6_sigbox","fp-death",6,"disp",(830,1440,1060,1610)),
 ("death_p12_impressions","fp-death",12,"disp",(980,1470,1210,1800)),
 ("dism_p1_impressions","fp-dismissal",1,"disp",(1090,1210,1310,1650)),
 ("dism_p6_thumb","fp-dismissal",6,"disp",(300,1470,570,1610)),
 ("dism_p6_cnic","fp-dismissal",6,"disp",(130,130,510,580)),
 ("dism_p6_sigbox","fp-dismissal",6,"disp",(370,455,510,565)),
 ("refund_p2_sigbox","refundable",2,"prev",(790,200,1010,490)),
 ("nonref_p2_sigbox","non-refundable",2,"prev",(730,260,930,530)),
 ("resid_p4_sigbox","residual",4,"prev",(1210,740,1550,1000)),
]
out={}
docs={k:fitz.open(D+v) for k,v in files.items()}
imgs={}
for name,slug,pn,mode,box in C:
    key=f"{slug}_p{pn:03d}.jpeg"
    if key not in imgs: imgs[key]=Image.open(E+"native/"+key); imgs[key].load()
    im=imgs[key]; m=meta[key]
    if mode=="prev":
        s=m["preview_scale"]; nb=[int(b*s) for b in box]
    else:
        p=docs[slug][pn-1]
        info=max(p.get_image_info(xrefs=True), key=lambda i:i['width']*i['height'])
        bx=info['bbox']; sx=info['width']/(bx[2]-bx[0]); sy=info['height']/(bx[3]-bx[1])
        pt=[box[0]/2.375,box[1]/2.375,box[2]/2.375,box[3]/2.375]
        nb=[int((pt[0]-bx[0])*sx),int((pt[1]-bx[1])*sy),int((pt[2]-bx[0])*sx),int((pt[3]-bx[1])*sy)]
    nb=[max(0,nb[0]),max(0,nb[1]),min(im.width,nb[2]),min(im.height,nb[3])]
    cr=im.crop(nb)
    cr.save(E+name+".png")
    # viewing copy: cap long side 1400 (downscale big), upscale small ones x2
    L=max(cr.size)
    if L>1400: v=cr.resize((int(cr.width*1400/L),int(cr.height*1400/L)),Image.LANCZOS)
    elif L<500: v=cr.resize((cr.width*2,cr.height*2),Image.LANCZOS)
    else: v=cr
    v.save(E+"view_"+name+".png")
    out[name]={"src":key,"native_box":nb,"w":cr.width,"h":cr.height,"dpi":m["dpi"]}
    print(name,nb,cr.size,m["dpi"])
json.dump(out,open(E+"crops.json","w"),indent=1)
