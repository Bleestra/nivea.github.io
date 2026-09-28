import bpy, math
from mathutils import Vector
def v(p): return Vector((p[0],-p[2],p[1]))
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

dragon=bpy.data.objects['Dragonnus'];knight=bpy.data.objects['Tenebris']
red=bpy.data.materials['Dragon crimson lacquer'];scarlet=bpy.data.materials['Dragon scarlet edges'];gold=bpy.data.materials['Warm gold'];plum=bpy.data.materials['Knight violet steel'];black=bpy.data.materials['Knight midnight armour']
for s in [-1,1]:
 for row in range(5):
  y=2.4+row*.48
  for col in range(3):
   x=s*(.62+col*.34);z=.94-col*.23
   shard('Dragon overlapping flank scale',(x,y,z),.6,.85,.16,scarlet if (row+col)%3 else gold,dragon)
 for row in range(3):
  shard('Dragon arm armour',(s*(1.65+row*.23),3.55-row*.59,1.3+row*.42),.7,.95,.28,scarlet,dragon)
  shard('Dragon haunch lamella',(s*1.6,2.55-row*.47,.18+row*.26),1.05,.86,.35,red if row%2 else gold,dragon)
 for row in range(3):
  bone('Knight greave gold inlay',(s*(.75+row*.04),1.65-row*.43,.5),(s*(.8+row*.04),1.23-row*.43,.49),.035,.018,gold,knight,5)
 bone('Knight breast gilt trim',(s*.78,5.32,.67),(s*.12,4.95,1.0),.045,.025,gold,knight,5)
 bone('Knight mask gilt trim',(s*.35,6.53,.66),(s*.1,6.05,.66),.033,.022,gold,knight,5)
for r,minor,mat in [(.49,.09,gold),(.36,.035,scarlet)]:
 bpy.ops.mesh.primitive_torus_add(major_radius=r,minor_radius=minor,major_segments=24,minor_segments=6)
 o=bpy.context.object;o.name='Dragon core bezel';o.parent=dragon;o.location=v((0,3.7,1.6));o.rotation_euler.x=math.pi/2;o.data.materials.append(mat)
# Broader arms read as weight-bearing limbs, not straight rods.
for o in dragon.children:
 if o.name.startswith('Dragon forearm'):o.scale.x*=1.18;o.scale.y*=1.18
result={'parts':{r.name:len(r.children_recursive) for r in [dragon,knight]}}

