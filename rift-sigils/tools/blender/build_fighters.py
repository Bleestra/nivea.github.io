import bpy, math
from mathutils import Vector
def v(p): return Vector((p[0],-p[2],p[1]))
def material(name,col,metal=.5,rough=.32,emit=0):
 m=bpy.data.materials.new(name);m.diffuse_color=(*col,1);m.use_nodes=True
 p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*col,1);p.inputs['Metallic'].default_value=metal;p.inputs['Roughness'].default_value=rough
 if emit:p.inputs['Emission Color'].default_value=(*col,1);p.inputs['Emission Strength'].default_value=emit
 return m
red=material('Dragon crimson lacquer',(.53,.018,.012))
scarlet=material('Dragon scarlet edges',(.9,.07,.015))
coal=material('Obsidian joints',(.024,.018,.032),.55,.45)
gold=material('Warm gold',(.93,.53,.12),.7,.25)
ivory=material('Ivory teeth',(.93,.8,.48),.3,.32)
membrane=material('Amber wing membrane',(.67,.22,.035),.12,.6)
orange=material('Ember core', (1,.22,.012),.25,.2,3)
plum=material('Knight violet steel',(.095,.035,.17),.7,.3)
purple=material('Knight amethyst edge',(.24,.08,.39),.62,.28)
black=material('Knight midnight armour',(.026,.024,.068),.75,.28)
cloth=material('Wine cape',(.17,.02,.09),.08,.75)
magenta=material('Void crystal',(.72,.012,1),.4,.18,3)
pale=material('Crystal heart',(1,.22,.83),.3,.18,4)
def group(name,parent=None,loc=(0,0,0)):
 o=bpy.data.objects.new(name,None);bpy.context.collection.objects.link(o);o.parent=parent;o.location=v(loc);return o
def mesh(name,vs,fs,mat,parent):
 d=bpy.data.meshes.new(name);d.from_pydata([v(p) for p in vs],[],fs);d.update()
 o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.data.materials.append(mat);o.parent=parent;return o
def ell(name,p,s,mat,parent,detail=1):
 bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=detail,radius=1)
 o=bpy.context.object;o.name=name;o.parent=parent;o.location=v(p);o.scale=(s[0],s[2],s[1]);o.data.materials.append(mat);return o
def bone(name,a,b,r1,r2,mat,parent,n=8):
 a,b=v(a),v(b);delta=b-a
 bpy.ops.mesh.primitive_cone_add(vertices=n,radius1=r1,radius2=r2,depth=delta.length)
 o=bpy.context.object;o.name=name;o.parent=parent;o.location=(a+b)/2;o.rotation_euler=delta.to_track_quat('Z','Y').to_euler();o.data.materials.append(mat);return o
def shard(name,p,w,h,d,mat,parent,lean=0):
 x,y,z=p
 vs=[(x,y+h*.6,z),(x-w*.5,y+h*.12,z),(x-w*.28,y-h*.4,z),(x,y-h*.55,z+lean),(x+w*.28,y-h*.4,z),(x+w*.5,y+h*.12,z),(x,y,z+d),(x,y,z-d*.3)]
 fs=[(i,(i+1)%6,6) for i in range(6)]+[((i+1)%6,i,7) for i in range(6)]
 return mesh(name,vs,fs,mat,parent)
def ribbon(name,points,widths,mat,parent):
 vs=[]
 for p,w in zip(points,widths):vs.extend([(p[0]-w,p[1],p[2]),(p[0],p[1]+.06,p[2]+.1),(p[0]+w,p[1],p[2])])
 fs=[]
 for i in range(len(points)-1):
  a=i*3;fs.extend([(a,a+3,a+4),(a,a+4,a+1),(a+1,a+4,a+5),(a+1,a+5,a+2)])
 o=mesh(name,vs,fs,mat,parent)
 sol=o.modifiers.new('Cloth thickness','SOLIDIFY');sol.thickness=.025
 return o
dragon=group('Dragonnus')
# Strong low body with layered ventral armour.
ell('Dragon pelvis',(0,2.5,-.7),(1.45,1.5,1.8),coal,dragon,2)
ell('Dragon thorax',(0,3.9,.25),(1.55,1.8,1.4),red,dragon,2)
for i in range(7):
 y=2.1+i*.43;z=.72+math.sin(i/6*math.pi)*.52
 shard('Dragon breast scale',(0,y,z),1.65-i*.09,.64,.23,gold if i%2==0 else ivory,dragon)
for side in [-1,1]:
 # Rear weight-bearing legs, knees and broad three-clawed feet.
 ell('Dragon haunch',(side*1.35,2.1,-.55),(.98,1.25,1.12),red,dragon,2)
 bone('Dragon shin',(side*1.5,1.9,-.3),(side*1.8,.55,1.0),.65,.42,red,dragon)
 ell('Dragon foot',(side*1.82,.36,1.55),(.77,.35,1.12),red,dragon,1)
 shard('Dragon kneecap',(side*1.7,1.7,.65),.85,1.1,.26,gold,dragon)
 for i in range(3):
  x=side*1.82+(i-1)*.45
  bone('Dragon foot talon',(x,.3,2.15),(x,.1,2.85),.19,.015,ivory,dragon)
 # Powerful arms pitched forward.
 bone('Dragon upper arm',(side*1.15,4.15,.6),(side*2.05,2.85,1.35),.62,.43,red,dragon)
 bone('Dragon forearm',(side*2.05,2.85,1.35),(side*2.45,1.55,2.45),.46,.26,red,dragon)
 ell('Dragon claw palm',(side*2.45,1.35,2.48),(.42,.4,.46),coal,dragon)
 for j in range(3):
  bone('Dragon hand talon',(side*2.45+(j-1)*.22,1.35,2.65),(side*2.45+(j-1)*.3,.72,3.05),.12,.01,ivory,dragon)
 for j in range(3):
  shard('Dragon shoulder scale',(side*(1.3+j*.18),4.3-j*.34,.62),.95,.9,.45,scarlet,dragon)
  bone('Dragon shoulder thorn',(side*(1.3+j*.17),4.45-j*.3,.05),(side*(2.4+j*.16),5.0-j*.38,-.3),.24,.01,gold,dragon)
# Curved neck and a unmistakable long dragon skull.
bone('Dragon neck',(0,4.2,.1),(0,5.65,1.15),.88,.65,red,dragon,10)
head=group('DragonHead',dragon,(0,5.6,1.1))
ell('Dragon cranium',(0,.65,.55),(.85,.79,1.25),red,head,2)
# Sharp muzzle and separated lower jaw.
mesh('Dragon upper snout',[(-.64,.7,.5),(.64,.7,.5),(-.46,.42,2.25),(.46,.42,2.25),(-.42,.95,1.8),(.42,.95,1.8),(0,1.13,.7)],[(0,2,4,6),(1,6,5,3),(2,3,5,4),(0,1,3,2),(4,5,6),(0,6,1)],scarlet,head)
mesh('Dragon lower jaw',[(-.55,-.18,.55),(.55,-.18,.55),(-.36,-.02,2.02),(.36,-.02,2.02),(-.45,-.42,.8),(.45,-.42,.8),(0,-.29,2.1)],[(0,2,3,1),(0,4,6,2),(1,3,6,5),(4,5,6)],red,head)
for s in [-1,1]:
 ell('Dragon eye socket',(s*.66,.85,1.04),(.19,.2,.44),coal,head)
 ell('Dragon molten eye',(s*.78,.86,1.1),(.055,.1,.28),orange,head)
 bone('Dragon brow',(s*.46,1.08,1.52),(s*.9,1.2,.55),.2,.29,gold,head)
 for j in range(5):
  z=.7+j*.29;x=s*(.47-j*.015)
  bone('Dragon upper fang',(x,.43,z),(x,.13,z+.04),.09,.008,ivory,head,5)
  bone('Dragon lower fang',(x,-.07,z),(x,.12,z),.06,.005,ivory,head,5)
 bone('Dragon great horn',(s*.52,1.0,.0),(s*.95,2.2,-.6),.3,.05,gold,head)
 bone('Dragon horn tip',(s*.95,2.2,-.6),(s*.82,2.8,-1.0),.08,0,ivory,head)
 for j in range(3):
  bone('Dragon cheek blade',(s*.65,.6-j*.3,.05),(s*1.3,.9-j*.22,-1.1-j*.15),.22,0,scarlet,head)
# Sinuous tail made of overlapping tapered armour, with a bladed tip.
tail=group('DragonTail',dragon)
points=[(0,2.1,-1.5),(.2,1.5,-2.7),(.5,.95,-3.8),(1.3,.55,-4.8),(2.3,.65,-5.5),(3.1,1.05,-5.6)]
for i in range(len(points)-1):
 bone('Dragon tail armour',points[i],points[i+1],.65-i*.1,.55-i*.1,red,tail)
 a=points[i];bone('Dragon tail crest',(a[0],a[1]+.4,a[2]),(a[0],a[1]+1.15-i*.13,a[2]-.25),.23-i*.025,0,gold,tail)
bone('Dragon tail blade',points[-1],(4,1.6,-5.3),.35,0,gold,tail)
# Wings have real tessellated membranes, spars and bright leading edges.
for s in [-1,1]:
 wing=group('DragonWingL' if s<0 else 'DragonWingR',dragon)
 A=(s*.85,4.35,-.6);B=(s*2.8,7.3,-1.0)
 tips=[(s*6.5,8.1,-1.65),(s*6.2,5.55,-2.4),(s*4.65,3.85,-2.5),(s*2.55,3.05,-1.75)]
 bone('Wing humerus',A,B,.31,.23,red,wing)
 for j,t in enumerate(tips):
  bone('Wing finger',B,t,.16,.015,gold if j==0 else red,wing,6)
 for j in range(3):
  t1,t2=tips[j],tips[j+1];mid=((t1[0]+t2[0])*.44,(t1[1]+t2[1])*.5+.35,(t1[2]+t2[2])*.5+.3)
  vs=[B,t1,mid,t2,A]
  mesh('Amber wing sail',vs,[(0,1,2),(0,2,4),(4,2,3)],membrane,wing)
  # Narrow red trailing border catches the silhouette.
  bone('Wing trailing rib',t1,mid,.07,.06,red,wing,5);bone('Wing trailing rib',mid,t2,.06,.045,red,wing,5)
 bone('Wing thumb',B,(s*3.0,8.35,-.8),.22,0,gold,wing)
for j in range(5):
 bone('Dragon spinal blade',(0,3.1+j*.4,-1.2),(0,3.7+j*.5,-1.95),.3,0,gold,dragon)
ell('Dragon burning chest core',(0,3.7,1.55),(.38,.45,.2),orange,dragon,2)
# Armoured abyss hunter, tall, narrow, with a readable face and sharp silhouette.
knight=group('Tenebris')
ell('Knight hip',(0,3.2,0),(.75,.65,.48),black,knight)
ell('Knight torso',(0,4.65,0),(1.0,1.25,.62),black,knight,2)
for s in [-1,1]:
 bone('Knight upper leg',(s*.43,3.25,0),(s*.66,1.8,.22),.38,.26,black,knight)
 bone('Knight greave',(s*.66,1.8,.22),(s*.88,.35,.03),.32,.18,plum,knight)
 shard('Knight thigh plate',(s*.47,2.65,.4),.72,1.6,.24,plum,knight)
 shard('Knight shin blade',(s*.77,1.0,.32),.56,1.65,.34,black,knight)
 shard('Knight knee gold edge',(s*.66,1.83,.52),.59,.65,.17,gold,knight)
 ell('Knight sabaton',(s*.88,.18,.35),(.3,.19,.72),black,knight)
 bone('Knight toe blade',(s*.88,.2,.65),(s*.94,.07,1.13),.15,0,gold,knight)
 bone('Knight upper arm',(s*.9,5.15,0),(s*1.45,4.1,.13),.3,.23,black,knight)
 bone('Knight vambrace',(s*1.45,4.1,.13),(s*1.6,3.25,.48),.27,.15,plum,knight)
 shard('Knight gauntlet',(s*1.58,3.45,.58),.43,1.15,.3,black,knight)
 ell('Knight hand',(s*1.61,3.0,.51),(.2,.27,.2),black,knight)
 for j in range(3):
  shard('Knight layered pauldron',(s*(.85+j*.3),5.25-j*.13,.15-j*.13),1.05,1.25,.45,plum if j%2==0 else black,knight)
  bone('Knight shoulder lance',(s*(1.05+j*.22),5.45-j*.1,-.18),(s*(1.3+j*.45),6.65-j*.16,-.55),.22,0,gold if j==0 else purple,knight)
 # Layered skirt armour and gold chevrons.
 for j in range(3):
  shard('Knight skirt tasset',(s*(.38+j*.26),2.96-j*.2,.48-j*.22),.58,1.8+j*.3,.23,plum if j%2 else black,knight,lean=.3)
  bone('Knight gold breast chevron',(s*.82,5.05,.57),(s*.12,4.55,.77),.06,.045,gold,knight,5)
shard('Knight breastplate',(0,4.9,.58),1.65,1.9,.4,plum,knight)
shard('Knight chest crystal',(0,4.9,1.0),.47,.91,.16,magenta,knight)
for j in range(3):shard('Knight abdominal lamella',(0,4.02-j*.29,.53),1.03-j*.12,.5,.24,black,knight)
shard('Knight belt jewel',(0,3.28,.64),.36,.5,.14,magenta,knight)
helmet=group('KnightHead',knight,(0,6.14,0))
ell('Knight helmet core',(0,.2,0),(.55,.72,.48),black,helmet,1)
shard('Knight face mask',(0,.15,.38),.88,1.25,.36,plum,helmet)
shard('Knight brow crest',(0,.65,.51),.23,1.7,.22,gold,helmet)
for s in [-1,1]:
 shard('Knight cheek guard',(s*.42,-.05,.2),.33,1.2,.31,black,helmet)
 bone('Knight glowing visor',(s*.06,.35,.69),(s*.43,.47,.46),.055,.07,magenta,helmet,5)
 bone('Knight crown horn',(s*.38,.66,-.12),(s*.62,1.95,-.4),.2,0,gold,helmet)
 bone('Knight side crest',(s*.48,.35,-.22),(s*.95,1.13,-.85),.21,0,purple,helmet)
# Five flowing cape panels; rear silhouettes are deliberately asymmetric.
cape=group('KnightCape',knight)
for i in range(5):
 x=(i-2)*.43
 ribbon('Knight cape panel',[(x,5.45,-.5),(x*1.7,4.5,-1.05),(x*2.6+.4,2.9,-1.7),(x*3.4+.8,.5+abs(i-2)*.42,-2.6)], [.36,.52,.66,.1],cloth if i%2 else plum,cape)
 bone('Cape gold clasp',(x,5.5,-.44),(x,5.08,-.72),.12,.07,gold,knight)
# Long spear and a magenta spearhead.
bone('Knight spear shaft',(1.65,.2,.55),(1.65,6.95,.55),.075,.065,gold,knight,8)
shard('Knight spear blade',(1.65,7.2,.55),.7,2.0,.15,black,knight)
shard('Knight spear crystal',(1.65,7.2,.73),.28,1.4,.07,magenta,knight)
for i,(x,y,z) in enumerate([(-2.7,6.7,-.25),(2.7,5.85,-.8),(-2.1,4.3,-.6)]):
 f=group('VoidBlade'+str(i),knight,(x,y,z))
 shard('Floating obsidian blade',(0,0,0),.7,2.25,.28,black,f)
 shard('Floating amethyst blade',(0,.06,.29),.28,1.45,.11,magenta,f)
 bone('Floating blade gilt ridge',(-.31,-.25,.03),(0,1.35,.05),.05,0,gold,f,5)
# Display both models side by side; roots reset to zero when loaded by the game.
dragon.location=v((-6,0,0));knight.location=v((6,0,0))
scene=bpy.context.scene;scene.world=bpy.data.worlds.new('Studio');scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.12,.17,.25,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.55
bpy.ops.object.camera_add(location=v((19,12,27)));cam=bpy.context.object;cam.name='Fighter review camera';cam.rotation_euler=(v((0,4,0))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=48;scene.camera=cam
for name,loc,energy,col in [('Key',(8,15,12),3,(1,.86,.69)),('Rim',(-8,10,-9),2,(.5,.63,1))]:
 bpy.ops.object.light_add(type='SUN',location=v(loc));o=bpy.context.object;o.name=name;o.data.energy=energy;o.data.color=col;o.rotation_euler=(v((0,3,0))-o.location).to_track_quat('-Z','Y').to_euler();o.data.angle=.12
scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=1200;scene.render.resolution_y=800;scene.render.resolution_percentage=100
result={'roots':[dragon.name,knight.name],'objects':len(bpy.data.objects),'parts':{r.name:len(r.children_recursive) for r in [dragon,knight]}}

