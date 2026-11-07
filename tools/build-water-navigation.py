"""Trace boat courses through the map's blue water and measure bank clearance.

Run from the repository: node tools/sample-boat-courses.cjs /tmp/reef-courses.json
then python tools/build-water-navigation.py /tmp/reef-courses.json.
Requires Pillow, NumPy and SciPy. The raster remains unchanged; the small
Mud Bayou junction overlay is mirrored below for the geometry checks.
"""
import base64
import heapq
import io
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'map-source.html').read_text()
png = re.search(r"quad: \{ full: 'data:image/png;base64,([^']+)'", source)[1]
im = Image.open(io.BytesIO(base64.b64decode(png))).convert('RGB')
draw = ImageDraw.Draw(im)
draw.line([(2770,2850),(2773,2856),(2776,2870)], fill='#7bc3e5', width=9)
draw.line([(2770,2850),(2773,2856),(2776,2870)], fill='#e1f3ff', width=6)
rgb = np.asarray(im).astype(np.int16)
r,g,b = rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
blue = (b>r+12) & (b>g+3) & (g>r+5)
# Reconnect tiny gaps left by antialiasing, contours and map lettering.
map_ink = (rgb.max(axis=2)-rgb.min(axis=2)<18) & (r<205)
covered_water = map_ink & (ndi.distance_transform_edt(~blue)<=4)
water = ndi.binary_closing(blue | covered_water, iterations=3)
# The railroad symbol covers the narrow bayou at this surveyed bridge.
# It is navigable underneath the bridge; this does not alter the map image.
water[1840:1857,2849:2852] = True
clearance = ndi.distance_transform_edt(water)
snapped = {}

def snap(x,y):
    key = (round(x,3),round(y,3))
    if key in snapped:
        return snapped[key]
    ix,iy = round(x),round(y)
    for radius in (8,24,60):
        ys,xs = np.where(water[iy-radius:iy+radius+1,ix-radius:ix+radius+1])
        if not len(xs):
            continue
        xs,ys = xs+ix-radius,ys+iy-radius
        # Prefer a position with room around it, without changing the route.
        scores = (xs-x)**2 + (ys-y)**2 + 24/np.maximum(1,clearance[ys,xs])**2
        j = np.argmin(scores)
        snapped[key] = (int(xs[j]),int(ys[j]))
        return snapped[key]
    raise ValueError(('No water near boat',x,y))

routes = {}
neighbors = [(dx,dy,math.hypot(dx,dy)) for dy in (-1,0,1) for dx in (-1,0,1) if dx or dy]
def route(a,b):
    if a == b:
        return [a]
    key = (a,b)
    if key in routes:
        return routes[key]
    if (b,a) in routes:
        return routes[(b,a)][::-1]
    for padding in (12,40,120):
        x0,x1 = min(a[0],b[0])-padding,max(a[0],b[0])+padding
        y0,y1 = min(a[1],b[1])-padding,max(a[1],b[1])+padding
        queue = [(math.dist(a,b),0,a)]
        costs,previous = {a:0},{}
        while queue:
            _,cost,p = heapq.heappop(queue)
            if cost != costs[p]:
                continue
            if p == b:
                result = [b]
                while result[-1] != a:
                    result.append(previous[result[-1]])
                result.reverse()
                routes[key] = result
                return result
            for dx,dy,length in neighbors:
                x,y = p[0]+dx,p[1]+dy
                if not (x0<=x<=x1 and y0<=y<=y1 and water[y,x]):
                    continue
                # A diagonal cannot cut a dry corner.
                if dx and dy and not (water[p[1],x] and water[y,p[0]]):
                    continue
                q = (x,y)
                value = cost + length*(1+2/max(1,clearance[y,x])**2)
                if value < costs.get(q,math.inf):
                    costs[q] = value
                    previous[q] = p
                    heapq.heappush(queue,(value+math.dist(q,b),value,q))
    raise ValueError(('Disconnected boat course',a,b))

if '--validate' in sys.argv:
    navigation=json.loads((ROOT/'water-navigation.json').read_text())
    checked=0
    for key,knots in navigation.items():
        assert knots[0][0]==0 and knots[-1][0]==1, key
        for a,b in zip(knots,knots[1:]):
            assert a[0]<b[0], (key,'non-increasing time')
            for t in np.linspace(0,1,5):
                x,y=round(a[1]+t*(b[1]-a[1])),round(a[2]+t*(b[2]-a[2]))
                assert water[y,x], (key,'boat on dry land',x,y)
                assert min(a[3],b[3])<=clearance[y,x], (key,'hull exceeds water clearance')
                checked+=1
    print(f'PASS: {len(navigation)} unique courses; {checked} positions and hull clearances checked.')
    sys.exit(0)

navigation = {}
for track in json.loads(Path(sys.argv[1]).read_text()):
    key = track['scene']+':'+track['actor']
    if key in navigation:
        continue
    points = track['points']
    knots = []
    for left,right in zip(points,points[1:]):
        course = route(snap(left['x'],left['y']),snap(right['x'],right['y']))
        distances = [0]
        for a,b in zip(course,course[1:]):
            distances.append(distances[-1]+math.dist(a,b))
        for i,(x,y) in enumerate(course):
            fraction = distances[i]/distances[-1] if distances[-1] else 0
            t = left['t']+(right['t']-left['t'])*fraction
            # One-pixel margin covers rounding and line interpolation.
            radius = max(.15,float(clearance[y,x])-1)
            knot = [round(t,7),x,y,round(radius,2)]
            if not knots or knot[0] > knots[-1][0]:
                knots.append(knot)
        if len(course)==1:
            knots.append([round(right['t'],7),*course[0],knots[-1][3]])
    if knots[-1][0] < 1:
        p = snap(points[-1]['x'],points[-1]['y'])
        knots.append([1,*p,max(.15,round(float(clearance[p[1],p[0]])-1,2))])
    navigation[key] = knots

target = ROOT / 'water-navigation.json'
target.write_text(json.dumps(navigation,separators=(',',':'))+'\n')
print(f'{len(navigation)} boat courses, {sum(map(len,navigation.values()))} water waypoints')
