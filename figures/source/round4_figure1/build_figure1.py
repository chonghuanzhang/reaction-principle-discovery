"""Deterministic Figure 1 replacement from author supplied layout.

The raster composition is retained; edited text and chart marks are drawn at
2x source scale. The S–H structures are copied from the previously validated
N-phenyl amide illustration, with no changes to molecular connectivity.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import csv, math, json, hashlib

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCALE = 2
ref = Image.open(HERE/'user_reference.png').convert('RGB')
W,H = ref.size
im = ref.resize((W*SCALE,H*SCALE), Image.Resampling.LANCZOS)
D = ImageDraw.Draw(im)
BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
REG='/System/Library/Fonts/Supplemental/Arial.ttf'
INK='#071c4d'

def box(v): return tuple(round(x*SCALE) for x in v)
def font(n,bold=False):return ImageFont.truetype(BOLD if bold else REG,round(n*SCALE))
def rect(v,fill,outline=None,width=1,radius=0):
 if radius:D.rounded_rectangle(box(v),radius=round(radius*SCALE),fill=fill,outline=outline,width=round(width*SCALE))
 else:D.rectangle(box(v),fill=fill,outline=outline,width=round(width*SCALE))
def line(points,fill,width=1):D.line([(round(x*SCALE),round(y*SCALE)) for x,y in points],fill=fill,width=round(width*SCALE))
def text(x,y,t,n=17,fill=INK,bold=False,anchor='mm'):
 D.text((x*SCALE,y*SCALE),t,font=font(n,bold),fill=fill,anchor=anchor,stroke_width=0)
def multi(x,y,ls,n=17,fill=INK,bold=False,step=None,anchor='mm'):
 for i,t in enumerate(ls):text(x,y+i*(step or n*1.18),t,n,fill,bold,anchor)

# Remove weak AI-generated grey mottling on the white canvas. Saturated ink,
# structures, connectors and shaded icon details are outside this threshold.
pix=im.load()
for y in range(im.height):
 for x in range(im.width):
  r,g,b=pix[x,y]
  if min(r,g,b)>238 and max(r,g,b)-min(r,g,b)<10:pix[x,y]=(255,255,255)

# Flat fills for each large panel and subcard. Only pale background pixels are
# remapped; lettering, bonds, shaded icons and dark borders are retained.
def flatten_region(bounds,color,threshold=215,spread=62,radius=0):
 x0,y0,x1,y1=box(bounds); col=tuple(bytes.fromhex(color.lstrip('#')))
 mask=Image.new('L',im.size,0);m=ImageDraw.Draw(mask)
 m.rounded_rectangle((x0,y0,x1,y1),radius=round(radius*SCALE),fill=255)
 for y in range(y0,y1+1):
  for x in range(x0,x1+1):
   if not mask.getpixel((x,y)):continue
   r,g,b=pix[x,y]
   if min(r,g,b)>threshold and max(r,g,b)-min(r,g,b)<spread:pix[x,y]=col

for bounds,color,radius in [
 ((36,57,667,377),'#f3effb',43),
 ((885,15,1644,324),'#f2f8f6',41),
 ((900,63,1252,175),'#eaf6fc',14),
 ((1265,63,1633,176),'#f1f7e9',14),
 ((901,186,1253,307),'#fff2df',14),
 ((1266,187,1634,307),'#fceaf0',14),
 ((1022,349,1656,601),'#f0f7e9',43),
 ((1040,397,1647,588),'#ffffff',30),
 ((849,626,1657,857),'#fff5eb',42),
 ((865,673,1647,843),'#ffffff',29),
 ((9,449,605,857),'#eff5fe',42),
 ((22,651,595,844),'#ffffff',23),
]:flatten_region(bounds,color,radius=radius)
# Remove all remnants of the redundant block-1 LLM illustration, and replace
# the uneven right-hand card by a single clean, aligned content field.
rect((353,158,658,367),'#f3effb')
rect((363,174,652,344),'#ffffff','#dfd5f6',0.7,17)
checks=[('Extract reaction knowledge',205),('Connect related evidence',259),('Propose transferable principles',313)]
for t,y in checks:
 D.ellipse(box((381,y-8,397,y+8)),fill='#0866c6')
 line([(385,y),(389,y+3),(394,y-4)],'#ffffff',1.8)
 text(408,y,t,15.4,INK,True,'lm')
# Update source count using the same purple typographic hierarchy.
rect((113,256,282,288),'#f3effb')
text(197,274,'370 sources',23.5,'#6543bd',True)
# Clean the column divider and preserve the two column headings.
line([(340,132),(340,354)],'#cbbde9',0.8)
# Swap only the block numerals, retaining the original panel positions.
for cx,cy,num,color in [(68,474,'4','#4b607c'),(924,646,'5','#ee8d14')]:
 D.ellipse(box((cx-22,cy-22,cx+22,cy+22)),fill=color)
 text(cx,cy-0.5,num,32,'#ffffff',True)

# Restore correct S–H model chemistry from the validated previous figure.
rect((21,500,594,647),'#ffffff',radius=17)
chem=Image.open(HERE/'verified_SH_reaction.png').convert('RGB')
chem=chem.resize((round(560*SCALE),round(560*SCALE*chem.height/chem.width)),Image.Resampling.LANCZOS)
im.paste(chem,(round(27*SCALE),round(501*SCALE)))
D=ImageDraw.Draw(im)
rect((148,615,482,645),'#e9f2fe',radius=12)
text(315,630,'Fixed S–H pair · 96 reaction conditions',16.4,INK,True)

# Replace illustrative plate and reversed boxplots by source-derived marks.
rect((20,651,596,845),'#ffffff','#cddff7',0.7,23)
text(178,667,'96-condition HTE screen',15.7,INK,True)
text(472,666,'Bayesian vs. random selection',14.8,INK,True)
text(472,686,'S–H benchmark · 100 paired seeds',12.6,'#435372')
line([(342,667),(342,829)],'#c4d2e5',0.8)
rows=list(csv.DictReader((REPO/'optimization/figures/source_data/SH_PL40_full_measured_grid_seed5010.csv').open()))
# The plate is laid out as the 12 bases (columns) by 8 solvents (rows), not as
# sequential wrapped source rows. This matches the deposited 12×8 factor grid.
vals=[float(r['measured_uv_response']) for r in rows]
colours=['#cbd3de','#8ebdf0','#1467c4']
for c in range(12):text(68+c*13.3,696,str(c+1),10.8,INK,True)
for r in range(8):
 text(46,711+r*14.2,chr(65+r),11.5,INK,True)
 for c in range(12):
  v=vals[c*8+r]; cat=2 if v>=1 else 1 if v>=0.2 else 0
  cx,cy=68+c*13.3,711+r*14.2
  D.ellipse(box((cx-4.6,cy-4.6,cx+4.6,cy+4.6)),fill=colours[cat])
text(145,834,'Bases 1–12 · solvents A–H',10.8,'#4b5d76')
for y,c,t in [(721,colours[2],'High'),(752,colours[1],'Moderate'),(783,colours[0],'Low')]:
 D.ellipse(box((247,y-5,257,y+5)),fill=c)
 text(265,y,t,11.8,INK,False,'lm')
text(278,808,'UV response',10.6,'#435372')

paired=list(csv.DictReader((REPO/'optimization/figures/source_data/SH_100_paired_budgets.csv').open()))
series={'Bayesian':[int(r['bo_exact_budget']) for r in paired], 'Random':[int(r['random_exact_budget']) for r in paired]}
def percentile(v,p):
 a=sorted(v);i=(len(a)-1)*p;k=math.floor(i);return a[k]+(a[min(k+1,len(a)-1)]-a[k])*(i-k)
chart={'x0':422,'x1':583,'axis_y':803}
fx=lambda v:chart['x0']+(chart['x1']-chart['x0'])*v/96
stats={}
for name,y,color in [('Bayesian',728,'#7354d1'),('Random',771,'#5a6b82')]:
 a=series[name];q1,med,q3=(percentile(a,p) for p in (.25,.5,.75));iqr=q3-q1
 lo=min(v for v in a if v>=q1-1.5*iqr);hi=max(v for v in a if v<=q3+1.5*iqr)
 stats[name]={'n':len(a),'q1':q1,'median':med,'q3':q3,'whisker_min':lo,'whisker_max':hi}
 text(412,y,name,11.5,INK,False,'rm')
 line([(fx(lo),y),(fx(hi),y)],color,1.2)
 for v in (lo,hi):line([(fx(v),y-5),(fx(v),y+5)],color,1.1)
 rect((fx(q1),y-8,fx(q3),y+8),'#eee8fa' if name=='Bayesian' else '#e8edf3',color,1.2)
 line([(fx(med),y-8),(fx(med),y+8)],color,2)
 text(fx(med),y-17,str(int(med)),10.9,color,True)
 for j,v in enumerate(sorted(set(v for v in a if v<lo or v>hi))):
  D.ellipse(box((fx(v)-2,y-2,fx(v)+2,y+2)),fill='#ffffff',outline=color,width=SCALE)
line([(fx(0),803),(fx(96),803)],'#7c8b9d',1)
for v in (0,24,48,72,96):
 line([(fx(v),803),(fx(v),807)],'#7c8b9d',0.8)
 text(fx(v),817,str(v),10.5,'#435372')
text(503,836,'Evaluations to measured optimum',10.3,'#435372')

# Rebuild small icons on their flat card backgrounds. This prevents the pale
# shading in the AI reference from turning into residual coloured patches.
# Three literature sheets.
rect((59,153,288,255),'#f3effb')
for x,y in [(68,160),(145,163),(221,167)]:
 rect((x-3,y+4,x+63,y+88),'#dce0e7',radius=1)
 rect((x,y,x+63,y+84),'#ffffff','#b7bfcb',0.7)
 line([(x+9,y+24),(x+53,y+24)],'#819cc5',0.8)
 for yy in range(y+33,y+73,4):line([(x+9,yy),(x+53,yy)],'#b7c5d9',0.55)
text(305,192,'···',26,'#6543bd',True)
# Reactive donor icon: a simple Nu label rather than damaged metallic shading.
rect((1548,94,1590,137),'#f1f7e9')
D.ellipse(box((1552,98,1584,130)),fill='#ffffff',outline='#cbdaba',width=1*SCALE)
text(1568,114,'Nu',15.5,'#2d7c35',True)
# Human selector icon.
rect((1387,401,1442,454),'#ffffff')
D.ellipse(box((1392,405,1438,451)),fill='#e6f0fc')
D.ellipse(box((1408,414,1423,429)),fill='#0c244b')
D.rounded_rectangle(box((1401,428,1430,443)),radius=6*SCALE,fill='#0c244b')
# Candidate structures use the verified drawing components from the preceding
# accepted figure, rearranged into three columns for the supplied compact box.
rect((1060,427,1355,582),'#ffffff')
cand=Image.open(HERE/'candidate_graphics.png').convert('RGB')
parts=[(0,0,363,280),(400,15,725,285),(0,310,365,510),
       (400,310,725,515),(0,565,365,745),(400,565,725,745)]
for i,bb in enumerate(parts):
 z=cand.crop(bb); maxw,maxh=92*SCALE,68*SCALE
 ratio=min(maxw/z.width,maxh/z.height)
 z=z.resize((round(z.width*ratio),round(z.height*ratio)),Image.Resampling.LANCZOS)
 xx=(1063+(i%3)*97)*SCALE+(92*SCALE-z.width)//2
 yy=(430+(i//3)*75)*SCALE+(68*SCALE-z.height)//2
 im.paste(z,(round(xx),round(yy)))
D=ImageDraw.Draw(im)
# Clean, uniform nucleophile class strip.
rect((893,772,1181,838),'#fff1dc',radius=11)
text(1037,787,'Nu = N, O or S nucleophile',15.2,'#7c450a',True)
for xx,lab,col in [(965,'N','#1268c6'),(1038,'O','#bc344d'),(1111,'S','#d0870d')]:
 D.ellipse(box((xx-19,817-19,xx+19,817+19)),fill='#ffffff',outline=col,width=1*SCALE)
 text(xx,817,lab,22,col,True)
# Restore pictorial and hub shading from the reference after flat-background
# operations; only near-white canvas pixels are cleaned within these crops.
for bb in [(656,380,946,581),(1220,685,1410,836)]:
 z=ref.crop(bb).resize(((bb[2]-bb[0])*SCALE,(bb[3]-bb[1])*SCALE),Image.Resampling.LANCZOS)
 pp=z.load()
 for yy in range(z.height):
  for xx in range(z.width):
   rr,gg,bbv=pp[xx,yy]
   if min(rr,gg,bbv)>247 and max(rr,gg,bbv)-min(rr,gg,bbv)<9:pp[xx,yy]=(255,255,255)
 im.paste(z,(bb[0]*SCALE,bb[1]*SCALE))
D=ImageDraw.Draw(im)

out=REPO/'figures/main/Figure_1.png'
im.save(out,dpi=(300,300),optimize=True)
report={
 'source':'user_reference.png','output':str(out.relative_to(REPO)),
 'dimensions':list(im.size),'scale':SCALE,'boxplot_statistics':stats,
 'changes':['swapped block 4/5 numerals only','removed block-1 LLM icon; center icon retained','uniform pale panel and card backgrounds','370 literature sources','validated N-phenyl amide S–H benchmark reaction','actual paired-seed boxplot distributions and source-derived plate','UV response legend'],
 'plate_bins':{'low':'UV response < 0.2','moderate':'0.2 ≤ UV response < 1.0','high':'UV response ≥ 1.0'},
 'chemical_source':'verified_SH_reaction.png (previously validated C9H8F3NO substrate, C19H20FNOS product)',
 'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
}
(HERE/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
