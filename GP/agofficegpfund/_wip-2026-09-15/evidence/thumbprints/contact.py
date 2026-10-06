from PIL import Image, ImageDraw
import glob, os
P="C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad/corpus/pages/"
E="C:/Users/AHMED~1.RAZ/AppData/Local/Temp/claude/C--Users-ahmed-raza-AppData-Roaming-Claude-scratch-workspaces-00a19eb6-744e-4e37-8084-438d55a51b19-60477492-cdc5-4d76-b11a-06ae5a1c58de-scratch-2026-09-15-d5e195/afda43d7-8df6-4241-b08e-d32fab97ced3/scratchpad/evidence/thumbprints/"
for slug in ["fp-non-gazetted","fp-death","fp-dismissal","refundable","non-refundable","residual"]:
    fs=sorted(glob.glob(P+slug+"/p*.jpg"))
    tw,th=340,480
    cols=5; rows=(len(fs)+cols-1)//cols
    sheet=Image.new("RGB",(cols*tw,rows*(th+20)),"white")
    d=ImageDraw.Draw(sheet)
    for i,f in enumerate(fs):
        im=Image.open(f); im.thumbnail((tw,th))
        x=(i%cols)*tw; y=(i//cols)*(th+20)
        sheet.paste(im,(x,y+20)); d.text((x+5,y+3),os.path.basename(f),fill="red")
    sheet.save(E+"contact_"+slug+".jpg",quality=80); print(slug,len(fs))
