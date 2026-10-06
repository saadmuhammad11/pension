import zxingcpp, numpy as np, cv2
S=r"C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad"
im=cv2.imread(f"{S}/corpus/pages/fp-dismissal/p004.jpg",0)
roi=im[60:330,840:1120]
cv2.imwrite(f"{S}/evidence/fp-dismissal/_work/p4_qr_roi.png",cv2.resize(roi,None,fx=3,fy=3,interpolation=cv2.INTER_NEAREST))
hits=set()
for sc in [1,1.5,2,3,4,5,6]:
  r=cv2.resize(roi,None,fx=sc,fy=sc,interpolation=cv2.INTER_CUBIC)
  for blur in [0,3,5]:
    rb=cv2.GaussianBlur(r,(blur,blur),0) if blur else r
    variants=[rb]
    for t in [90,110,130,150,170,190]:
      variants.append(((rb>t)*255).astype(np.uint8))
    variants.append(cv2.adaptiveThreshold(rb,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,51,10))
    k=np.ones((3,3),np.uint8)
    variants.append(cv2.morphologyEx(((rb>150)*255).astype(np.uint8),cv2.MORPH_OPEN,k))
    variants.append(cv2.morphologyEx(((rb>150)*255).astype(np.uint8),cv2.MORPH_CLOSE,k))
    for v in variants:
      for res in zxingcpp.read_barcodes(v, try_rotate=True, try_downscale=True):
        hits.add((res.format.name,res.text))
print("p4 hits:",hits)
d=cv2.QRCodeDetector()
for sc in [2,3,4,6]:
  r=cv2.resize(roi,None,fx=sc,fy=sc,interpolation=cv2.INTER_CUBIC)
  t,pts,_=d.detectAndDecode(r)
  print(sc,repr(t),pts is not None)
