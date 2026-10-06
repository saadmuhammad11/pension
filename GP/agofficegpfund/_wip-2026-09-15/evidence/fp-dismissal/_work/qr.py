import zxingcpp, numpy as np, cv2
from PIL import Image
S=r"C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad"
def pg(p): return cv2.imread(f"{S}/corpus/pages/fp-dismissal/p{p:03d}.jpg")
for p in range(1,10):
    im=pg(p)
    g=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
    r=zxingcpp.read_barcodes(g)
    print(p,[(b.format.name,b.text[:120],str(b.position)) for b in r])
