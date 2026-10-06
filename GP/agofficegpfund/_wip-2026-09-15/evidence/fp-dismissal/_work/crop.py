import sys
from PIL import Image
S=r"C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad"
# usage: crop.py page x0 y0 x1 y1 outname scale
p=int(sys.argv[1]); x0,y0,x1,y1=map(int,sys.argv[2:6]); out=sys.argv[6]; sc=float(sys.argv[7]) if len(sys.argv)>7 else 1.0
im=Image.open(f"{S}/corpus/pages/fp-dismissal/p{p:03d}.jpg")
c=im.crop((x0,y0,x1,y1))
if sc!=1.0: c=c.resize((int(c.width*sc),int(c.height*sc)),Image.LANCZOS)
c.save(out)
print(out,c.size)
