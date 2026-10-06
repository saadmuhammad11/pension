import zxingcpp, numpy as np, cv2
S=r"C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad"
im=cv2.imread(f"{S}/corpus/pages/fp-dismissal/p004.jpg",0)
roi=im[60:330,840:1120]
_,bw=cv2.threshold(roi,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
ys,xs=np.where(bw<128)
# restrict to QR body (exclude signature on the left): take columns > 60 in roi
m=xs>60
x0,x1,y0,y1=xs[m].min(),xs[m].max(),ys[m].min(),ys[m].max()
print("bbox roi",x0,y0,x1,y1,"page",840+x0,60+y0,840+x1,60+y1)
q=roi[y0:y1+1,x0:x1+1]
hits=set()
for n in [21,25,29,33,37]:
  for off in [0.3,0.4,0.5,0.6,0.7]:
    h,w=q.shape; ms=w/n; mh=h/n
    grid=np.zeros((n,n),np.uint8)
    for i in range(n):
      for j in range(n):
        cy=int((i+off)*mh); cx=int((j+off)*ms)
        cy=min(cy,h-1); cx=min(cx,w-1)
        grid[i,j]=0 if q[max(cy-1,0):cy+2,max(cx-1,0):cx+2].mean()<150 else 255
    big=cv2.resize(grid,(n*12,n*12),interpolation=cv2.INTER_NEAREST)
    big=cv2.copyMakeBorder(big,48,48,48,48,cv2.BORDER_CONSTANT,value=255)
    for r in zxingcpp.read_barcodes(big):
      hits.add((n,off,r.text))
print("grid hits:",hits)
