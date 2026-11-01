import struct
from pathlib import Path

icon=Path(__file__).resolve().parents[1]/"Kam3Tweaks.ico"
data=icon.read_bytes()
reserved,kind,count=struct.unpack_from("<HHH",data,0)
assert (reserved,kind)==(0,1)
entries=[]
for i in range(count):
    width,height,_,_,planes,bpp,length,offset=struct.unpack_from("<BBBBHHII",data,6+i*16)
    width=width or 256; height=height or 256
    frame=data[offset:offset+length]
    assert planes==1 and bpp==32 and frame.startswith(b"\x89PNG\r\n\x1a\n")
    png_width,png_height=struct.unpack_from(">II",frame,16)
    assert (png_width,png_height)==(width,height)
    entries.append((width,height))
assert entries==[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
print("PASS: Kam3Tweaks.ico contains valid PNG-backed 16, 24, 32, 48, 64, 128, and 256 pixel frames.")
